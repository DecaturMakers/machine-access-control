"""Status-change webhook notifier for external consumers (e.g. the ESB)."""

import logging
import os
from asyncio import CancelledError
from asyncio import Task
from asyncio import create_task
from asyncio import sleep
from time import time
from typing import TYPE_CHECKING
from typing import Any
from typing import Dict
from typing import Optional
from typing import Set
from urllib.parse import urlsplit

import aiohttp

if TYPE_CHECKING:  # pragma: no cover
    from dm_mac.models.machine import Machine
    from dm_mac.models.users import User


logger: logging.Logger = logging.getLogger(__name__)


class WebhookNotifier:
    """Fire status-change webhooks to a configured URL.

    Enabled only when ``STATUS_WEBHOOK_URL`` is set (see :meth:`from_env`).
    Deliveries are fire-and-forget: :meth:`notify` spawns an
    :func:`asyncio.create_task` so callers -- the MCU update handler and the
    Slack command handlers -- never block on the HTTP request, exactly as the
    Slack notifications do. Each delivery retries with exponential backoff and a
    per-attempt timeout; once the retries are exhausted the failure is logged
    and dropped (external consumers can reconcile via ``GET /api/machines``).

    The webhook only fires on meaningful status changes (login, logout,
    unauthorized/unknown fob, override login, oops, un-oops, lockout, unlock,
    reboot) because :meth:`notify` is called only from those code paths, never
    from ordinary MCU heartbeat updates.
    """

    #: Total number of POST attempts per event (initial try plus retries).
    MAX_ATTEMPTS: int = 4
    #: Base backoff in seconds; before attempt N (1-indexed) we wait
    #: ``BACKOFF_BASE_SEC * 2 ** (N - 2)`` (no wait before the first attempt).
    BACKOFF_BASE_SEC: float = 1.0
    #: Per-attempt HTTP timeout in seconds.
    REQUEST_TIMEOUT_SEC: float = 5.0

    def __init__(self, url: str):
        """Initialize a WebhookNotifier posting to ``url``."""
        self.url: str = url
        #: Strong references to in-flight delivery tasks. ``asyncio`` only
        #: holds a *weak* reference to tasks created via
        #: :func:`asyncio.create_task`, so without this a long-running
        #: :meth:`_deliver` (up to ~27 s of backoff + timeouts) could be
        #: garbage-collected mid-flight. Each task removes itself via a
        #: done-callback (the pattern from the asyncio docs).
        self._tasks: Set["Task[None]"] = set()

    @staticmethod
    def _safe_url(url: str) -> str:
        """Return ``scheme://host[:port]`` of ``url`` for safe logging.

        Strips any userinfo, path, and query string so credentials embedded
        in the URL (userinfo or query params) are never written to logs.
        """
        parts = urlsplit(url)
        host: str = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        return f"{parts.scheme}://{host}" if parts.scheme else host

    @classmethod
    def from_env(cls) -> Optional["WebhookNotifier"]:
        """Build a notifier from ``STATUS_WEBHOOK_URL``, or None if unset."""
        url: str = os.environ.get("STATUS_WEBHOOK_URL", "").strip()
        if not url:
            return None
        # Log only scheme+host: the URL may contain secrets (userinfo/query).
        logger.info("Status-change webhook enabled; posting to %s", cls._safe_url(url))
        return cls(url)

    def build_payload(
        self, machine: "Machine", event: str, user: Optional["User"] = None
    ) -> Dict[str, Any]:
        """Build the webhook payload for ``event`` on ``machine``.

        The payload is :py:attr:`Machine.status_dict <dm_mac.models.machine.
        Machine.status_dict>` (so ``current_user`` means the same thing here as
        in ``GET /api/machines``) plus three fields:

        * ``event`` -- the status-change event name.
        * ``timestamp`` -- epoch seconds when the event fired.
        * ``user`` -- the user *involved in this event* (the actor), as
          ``{"account_id", "full_name"}`` or ``None``. This differs from
          ``current_user`` for events like ``logout``/``unauthorized`` where a
          user acted but is not (or no longer) logged in.
        """
        payload: Dict[str, Any] = machine.status_dict
        payload["event"] = event
        payload["timestamp"] = time()
        payload["user"] = (
            None
            if user is None
            else {"account_id": user.account_id, "full_name": user.full_name}
        )
        return payload

    def notify(
        self, machine: "Machine", event: str, user: Optional["User"] = None
    ) -> None:
        """Build the payload and spawn a fire-and-forget delivery task."""
        payload: Dict[str, Any] = self.build_payload(machine, event, user=user)
        task: "Task[None]" = create_task(self._deliver(payload))
        # Hold a strong reference until the task completes so the event loop's
        # weak reference cannot let it be garbage-collected mid-delivery.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(self, payload: Dict[str, Any]) -> None:
        """Deliver one webhook with retries and exponential backoff.

        Returns as soon as an attempt gets a non-error (< 400) response. On
        network errors or 4xx/5xx responses it retries up to
        :data:`MAX_ATTEMPTS` times, backing off exponentially between attempts,
        then logs a single error and gives up. A single
        :class:`aiohttp.ClientSession` is reused across attempts so retries can
        benefit from connection pooling.
        """
        timeout: aiohttp.ClientTimeout = aiohttp.ClientTimeout(
            total=self.REQUEST_TIMEOUT_SEC
        )
        last_err: Optional[str] = None
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(1, self.MAX_ATTEMPTS + 1):
                if attempt > 1:
                    await sleep(self.BACKOFF_BASE_SEC * (2 ** (attempt - 2)))
                try:
                    async with session.post(self.url, json=payload) as resp:
                        if resp.status < 400:
                            return
                        last_err = f"HTTP {resp.status}"
                except CancelledError:  # pragma: no cover
                    raise
                except Exception as ex:
                    last_err = repr(ex)
        logger.error(
            "Failed to deliver status webhook for machine %s event %s after "
            "%d attempts: %s",
            payload.get("name"),
            payload.get("event"),
            self.MAX_ATTEMPTS,
            last_err,
        )
