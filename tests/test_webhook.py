"""Tests for dm_mac.webhook.WebhookNotifier."""

import asyncio
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

from dm_mac.webhook import WebhookNotifier

pbm: str = "dm_mac.webhook"


def _machine(status_dict: Optional[Dict[str, Any]] = None) -> Mock:
    """Build a fake Machine whose status_dict returns a fresh dict each call."""
    if status_dict is None:
        status_dict = {
            "name": "planer",
            "display_name": "Planer",
            "status": "idle",
            "relay": False,
            "oops": False,
            "locked_out": False,
            "current_user": None,
            "last_checkin": 100.0,
            "last_update": 200.0,
        }
    mach = Mock()
    # Return a copy each access so build_payload's mutation doesn't leak.
    mach.status_dict = dict(status_dict)
    return mach


class _FakePost:
    """Async context manager standing in for ``session.post(...)``."""

    def __init__(self, status: Optional[int] = None, exc: Optional[Exception] = None):
        self.status = status
        self._exc = exc

    async def __aenter__(self) -> "_FakePost":
        if self._exc is not None:
            raise self._exc
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False


class _FakeSession:
    """Async context manager standing in for ``aiohttp.ClientSession(...)``."""

    #: Records ``(url, json)`` for every post across all instances.
    calls: List[Any] = []

    def __init__(self, outcomes: List[Any]):
        self._outcomes = outcomes
        self._i = 0

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False

    def post(self, url: str, json: Dict[str, Any]) -> _FakePost:
        _FakeSession.calls.append((url, json))
        outcome = self._outcomes[self._i]
        self._i += 1
        if isinstance(outcome, Exception):
            return _FakePost(exc=outcome)
        return _FakePost(status=outcome)


class TestFromEnv:
    """Tests for WebhookNotifier.from_env."""

    def test_unset_returns_none(self) -> None:
        """Notifier is disabled (None) when STATUS_WEBHOOK_URL is unset."""
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("STATUS_WEBHOOK_URL", None)
            assert WebhookNotifier.from_env() is None

    def test_blank_returns_none(self) -> None:
        """Whitespace-only URL is treated as unset."""
        with patch.dict("os.environ", {"STATUS_WEBHOOK_URL": "   "}):
            assert WebhookNotifier.from_env() is None

    def test_set_returns_instance(self) -> None:
        """A configured URL yields a notifier pointed at it."""
        with patch.dict("os.environ", {"STATUS_WEBHOOK_URL": "https://esb/hook"}):
            notifier = WebhookNotifier.from_env()
        assert notifier is not None
        assert notifier.url == "https://esb/hook"


class TestBuildPayload:
    """Tests for WebhookNotifier.build_payload."""

    def test_payload_no_user(self) -> None:
        """Payload is status_dict plus event, timestamp, and null user."""
        notifier = WebhookNotifier("https://esb/hook")
        with patch(f"{pbm}.time", return_value=1234.5):
            payload = notifier.build_payload(_machine(), "lockout")
        assert payload["event"] == "lockout"
        assert payload["timestamp"] == 1234.5
        assert payload["user"] is None
        assert payload["current_user"] is None
        assert payload["name"] == "planer"
        assert payload["status"] == "idle"

    def test_payload_with_actor_user(self) -> None:
        """The acting user populates ``user`` distinct from ``current_user``."""
        notifier = WebhookNotifier("https://esb/hook")
        user = Mock(account_id="42", full_name="Jane Doe")
        # logout: nobody is currently logged in, but Jane is the actor.
        payload = notifier.build_payload(_machine(), "logout", user=user)
        assert payload["event"] == "logout"
        assert payload["user"] == {"account_id": "42", "full_name": "Jane Doe"}
        assert payload["current_user"] is None


class TestNotify:
    """Tests for WebhookNotifier.notify (fire-and-forget scheduling)."""

    async def test_notify_spawns_delivery(self) -> None:
        """notify builds the payload and schedules _deliver with it."""
        notifier = WebhookNotifier("https://esb/hook")
        user = Mock(account_id="1", full_name="Ashley")
        with patch.object(
            WebhookNotifier, "_deliver", new_callable=AsyncMock
        ) as mock_deliver:
            notifier.notify(_machine(), "login", user=user)
            await asyncio.sleep(0)  # let the scheduled task run
        mock_deliver.assert_awaited_once()
        payload = mock_deliver.await_args.args[0]
        assert payload["event"] == "login"
        assert payload["user"] == {"account_id": "1", "full_name": "Ashley"}


class TestDeliver:
    """Tests for WebhookNotifier._deliver (retry/backoff)."""

    def setup_method(self) -> None:
        """Reset the shared post-call recorder before each test."""
        _FakeSession.calls = []

    async def test_success_first_try(self) -> None:
        """A 2xx on the first attempt posts once with no backoff."""
        notifier = WebhookNotifier("https://esb/hook")
        session = _FakeSession([200])
        sleep_mock = AsyncMock()
        with patch(f"{pbm}.aiohttp.ClientSession", return_value=session), patch(
            f"{pbm}.sleep", sleep_mock
        ):
            await notifier._deliver({"name": "planer", "event": "login"})
        assert len(_FakeSession.calls) == 1
        sleep_mock.assert_not_awaited()

    async def test_retries_then_succeeds(self) -> None:
        """A network error then a 200 retries once (with one backoff)."""
        notifier = WebhookNotifier("https://esb/hook")
        session = _FakeSession([OSError("boom"), 200])
        sleep_mock = AsyncMock()
        with patch(f"{pbm}.aiohttp.ClientSession", return_value=session), patch(
            f"{pbm}.sleep", sleep_mock
        ):
            await notifier._deliver({"name": "planer", "event": "login"})
        assert len(_FakeSession.calls) == 2
        sleep_mock.assert_awaited_once()
        # First backoff uses BACKOFF_BASE_SEC * 2**0 == BACKOFF_BASE_SEC.
        assert sleep_mock.await_args.args[0] == notifier.BACKOFF_BASE_SEC

    async def test_http_error_retried(self) -> None:
        """A 4xx/5xx status is treated as failure and retried."""
        notifier = WebhookNotifier("https://esb/hook")
        session = _FakeSession([500, 503, 200])
        with patch(f"{pbm}.aiohttp.ClientSession", return_value=session), patch(
            f"{pbm}.sleep", AsyncMock()
        ):
            await notifier._deliver({"name": "planer", "event": "oops"})
        assert len(_FakeSession.calls) == 3

    async def test_all_attempts_fail_logs_error(self) -> None:
        """After MAX_ATTEMPTS failures it gives up and logs a single error."""
        notifier = WebhookNotifier("https://esb/hook")
        outcomes: List[Any] = [OSError("x")] * notifier.MAX_ATTEMPTS
        session = _FakeSession(outcomes)
        with patch(f"{pbm}.aiohttp.ClientSession", return_value=session), patch(
            f"{pbm}.sleep", AsyncMock()
        ), patch(f"{pbm}.logger") as mock_logger:
            await notifier._deliver({"name": "planer", "event": "login"})
        assert len(_FakeSession.calls) == notifier.MAX_ATTEMPTS
        mock_logger.error.assert_called_once()
