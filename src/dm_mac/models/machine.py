"""Model representing a machine."""

import asyncio
import logging
import os
import pickle
from collections import deque
from contextlib import nullcontext
from logging import Logger
from logging import getLogger
from threading import Lock
from time import monotonic
from time import time
from typing import TYPE_CHECKING
from typing import Any
from typing import Deque
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import cast

from filelock import FileLock
from humanize import naturaldelta
from jsonschema import validate
from quart import current_app

from dm_mac.models.users import User
from dm_mac.models.users import UsersConfig
from dm_mac.utils import load_json_config

if TYPE_CHECKING:  # pragma: no cover
    from dm_mac.slack_handler import SlackHandler
    from dm_mac.webhook import WebhookNotifier


logger: Logger = getLogger(__name__)


#: Maximum wall-clock seconds we will spend persisting machine state to disk
#: before raising :class:`StateSaveTimeoutError`. Keeps a single hung disk
#: write from blocking the request handler long enough to wedge the firmware
#: (see ``docs/2026-05-05-mcu-lockup-analysis.md``).
STATE_SAVE_TIMEOUT_SEC: float = 2.0

#: Window over which to count distinct machines that hit state-save timeouts
#: for the fleet-wide Slack alert (see :class:`FleetTimeoutTracker`).
FLEET_TIMEOUT_WINDOW_SEC: float = 60.0

#: Minimum distinct machines within :data:`FLEET_TIMEOUT_WINDOW_SEC` that
#: triggers the fleet-wide Slack notification.
FLEET_TIMEOUT_THRESHOLD: int = 2

#: Minimum spacing between consecutive fleet-wide Slack notifications, to
#: avoid spamming the channel during a sustained disk hang.
FLEET_TIMEOUT_COOLDOWN_SEC: float = 300.0


class StateSaveTimeoutError(Exception):
    """Raised when persisting machine state to disk exceeds the budget.

    Surfaced to MCU clients as HTTP 503 by the ``/api/machine/update``
    view (and by ``/api/machine/oops/<name>`` and
    ``/api/machine/locked_out/<name>``) so the firmware sees a clean
    error and recovers on its next heartbeat.
    """


class FleetTimeoutTracker:
    """Cross-machine accounting for state-save timeouts.

    The per-machine Slack notification in
    :meth:`MachineState._notify_save_timeout` only fires on the
    transition to 2 *lifetime* timeouts for a single machine, which
    is the right signal for "this machine is repeatedly slow". It is
    the *wrong* signal for "the disk on the mac-server host just
    hung", which produces the 2026-05-11 pattern: N distinct machines
    each hit their first lifetime timeout simultaneously, every per-
    machine counter goes 0 → 1, and no Slack message fires.

    This tracker fills that gap. Each timeout records
    ``(machine_name, monotonic_ts)``; when at least
    :data:`FLEET_TIMEOUT_THRESHOLD` *distinct* machines have recorded
    a timeout within :data:`FLEET_TIMEOUT_WINDOW_SEC`, the tracker
    signals that a fleet-wide notification should fire, subject to
    :data:`FLEET_TIMEOUT_COOLDOWN_SEC` between consecutive
    notifications.

    See ``docs/2026-05-11-mcu-lockup-analysis.md`` for the
    motivating incident.
    """

    def __init__(
        self,
        window_sec: float = FLEET_TIMEOUT_WINDOW_SEC,
        threshold: int = FLEET_TIMEOUT_THRESHOLD,
        cooldown_sec: float = FLEET_TIMEOUT_COOLDOWN_SEC,
    ) -> None:
        self.window_sec: float = window_sec
        self.threshold: int = threshold
        self.cooldown_sec: float = cooldown_sec
        self._events: Deque[Tuple[str, float]] = deque()
        self._last_notification_ts: Optional[float] = None

    def record(self, machine_name: str, now: Optional[float] = None) -> Optional[int]:
        """Record a state-save timeout for ``machine_name``.

        :param machine_name: Internal machine name (not display name).
        :param now: Override the current monotonic timestamp; used by
            tests. Production callers should omit this.
        :returns: ``None`` if no fleet-wide notification should fire;
            otherwise the count of *distinct* machines within the
            window at the moment the threshold was crossed. A non-None
            return implicitly arms the cooldown.
        """
        ts: float = monotonic() if now is None else now
        cutoff: float = ts - self.window_sec
        while self._events and self._events[0][1] < cutoff:
            self._events.popleft()
        self._events.append((machine_name, ts))
        distinct: int = len({name for name, _ in self._events})
        if distinct < self.threshold:
            return None
        if (
            self._last_notification_ts is not None
            and (ts - self._last_notification_ts) < self.cooldown_sec
        ):
            return None
        self._last_notification_ts = ts
        return distinct


_SECOND_RELAY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["authorizations_or"],
    "properties": {
        "authorizations_or": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
            "description": "List of authorizations any one of which is "
            "sufficient to energize the second relay. Must "
            "be non-empty.",
        },
        "unauthorized_warn_only": {
            "type": "boolean",
            "description": "If true, the second relay energizes for "
            "primary-authorized operators lacking secondary "
            "auth, with a warning emitted to logs and Slack.",
        },
        "always_enabled": {
            "type": "boolean",
            "description": "If true, the second relay tracks the primary "
            "relay's energized state regardless of "
            "operator's secondary authorization.",
        },
        "alias": {
            "type": "string",
            "minLength": 1,
            "description": "Human-readable name for the accessory governed "
            "by the second relay.",
        },
    },
    "additionalProperties": False,
}


CONFIG_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "patternProperties": {
        "^[a-z0-9_-]+$": {
            "type": "object",
            "required": ["authorizations_or"],
            "properties": {
                "authorizations_or": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of authorizations required to "
                    "operate machine, any one of which "
                    "is sufficient.",
                },
                "unauthorized_warn_only": {
                    "type": "boolean",
                    "description": "If set, allow anyone to operate machine "
                    "but log and display a warning if the "
                    "operator is not authorized.",
                },
                "always_enabled": {
                    "type": "boolean",
                    "description": "If set, machine is always enabled and "
                    "does not require RFID authentication. "
                    "Displays 'Always On' and relay is always "
                    "on unless Oopsed or Locked.",
                },
                "alias": {
                    "type": "string",
                    "description": "Optional human-friendly alias for the machine. "
                    "Used in Slack messages and logs instead of the machine name.",
                },
                "second_relay": _SECOND_RELAY_SCHEMA,
            },
            "additionalProperties": False,
            "description": "Unique machine name, alphanumeric _ and - only.",
        }
    },
}


class SecondRelayConfig:
    """Authorization rules governing a machine's second relay."""

    def __init__(
        self,
        authorizations_or: List[str],
        unauthorized_warn_only: bool = False,
        always_enabled: bool = False,
        alias: Optional[str] = None,
    ):
        """Initialize a new SecondRelayConfig instance."""
        self.authorizations_or: List[str] = authorizations_or
        self.unauthorized_warn_only: bool = unauthorized_warn_only
        self.always_enabled: bool = always_enabled
        self.alias: Optional[str] = alias

    @property
    def as_dict(self) -> Dict[str, Any]:
        """Return a dict representation of this second relay config."""
        return {
            "authorizations_or": self.authorizations_or,
            "unauthorized_warn_only": self.unauthorized_warn_only,
            "always_enabled": self.always_enabled,
            "alias": self.alias,
        }


class Machine:
    """Object representing a machine and its state and configuration."""

    def __init__(
        self,
        name: str,
        authorizations_or: List[str],
        unauthorized_warn_only: bool = False,
        always_enabled: bool = False,
        alias: Optional[str] = None,
        second_relay: Optional[SecondRelayConfig] = None,
    ):
        """Initialize a new MachineState instance."""
        #: The name of the machine
        self.name: str = name
        #: List of OR'ed authorizations, any of which is sufficient
        self.authorizations_or: List[str] = authorizations_or
        #: Whether to allow anyone to operate machine regardless of
        #: authorization, just logging/displaying a warning if unauthorized
        self.unauthorized_warn_only: bool = unauthorized_warn_only
        #: Whether machine is always enabled without RFID authentication
        self.always_enabled: bool = always_enabled
        #: Optional human-friendly alias for the machine
        self.alias: Optional[str] = alias
        #: Optional second-relay configuration
        self.second_relay: Optional[SecondRelayConfig] = second_relay
        #: state of the machine
        self.state: "MachineState" = MachineState(self)

    async def update(
        self, users: UsersConfig, **kwargs: Any
    ) -> Dict[str, str | bool | float | List[float]]:
        """Pass directly to self.state and return result."""
        return await self.state.update(users, **kwargs)

    async def lockout(self, slack: Optional["SlackHandler"] = None) -> None:
        """Pass directly to self.state."""
        self.state.lockout()
        source = "Slack"
        if not slack:
            slack = current_app.config.get("SLACK_HANDLER")
            source = "API"
        self.state._notify_status_webhook("lockout", slack=slack)
        if not slack:
            # Slack integration is not enabled
            return
        await slack.log_lock(self, source)

    async def unlock(self, slack: Optional["SlackHandler"] = None) -> None:
        """Pass directly to self.state."""
        self.state.unlock()
        source = "Slack"
        if not slack:
            slack = current_app.config.get("SLACK_HANDLER")
            source = "API"
        self.state._notify_status_webhook("unlock", slack=slack)
        if not slack:
            # Slack integration is not enabled
            return
        await slack.log_unlock(self, source)

    async def oops(self, slack: Optional["SlackHandler"] = None) -> None:
        """Pass directly to self.state."""
        self.state.oops()
        source = "Slack"
        if not slack:
            slack = current_app.config.get("SLACK_HANDLER")
            source = "API"
        self.state._notify_status_webhook("oops", slack=slack)
        if not slack:
            # Slack integration is not enabled
            return
        await slack.log_oops(self, source)

    async def unoops(self, slack: Optional["SlackHandler"] = None) -> None:
        """Pass directly to self.state."""
        self.state.unoops()
        source = "Slack"
        if not slack:
            slack = current_app.config.get("SLACK_HANDLER")
            source = "API"
        self.state._notify_status_webhook("unoops", slack=slack)
        if not slack:
            # Slack integration is not enabled
            return
        await slack.log_unoops(self, source)

    @property
    def display_name(self) -> str:
        """Return the display name for this machine (alias if present, else name)."""
        return self.alias if self.alias else self.name

    @property
    def status(self) -> str:
        """Return a single-word derived status string for this machine.

        One of ``locked_out``, ``oops``, ``in_use``, ``idle``, or ``unknown``
        (the latter only when the machine has never checked in and is not in
        any other state). Used by the ``GET /api/machines`` endpoint and the
        status-change webhook so both share a single source of truth.
        """
        state: "MachineState" = self.state
        if state.is_locked_out:
            return "locked_out"
        if state.is_oopsed:
            return "oops"
        if state.relay_desired_state:
            return "in_use"
        if state.last_checkin is None:
            return "unknown"
        return "idle"

    @property
    def status_dict(self) -> Dict[str, Any]:
        """Return the shared ESB status representation for this machine.

        Consumed by both ``GET /api/machines`` and the status-change webhook
        (which adds ``event`` and ``timestamp`` fields). ``current_user`` is
        ``{"account_id": ..., "full_name": ...}`` when a user is logged in, or
        ``None`` otherwise.
        """
        state: "MachineState" = self.state
        current_user: Optional[Dict[str, str]] = None
        if state.current_user is not None:
            current_user = {
                "account_id": state.current_user.account_id,
                "full_name": state.current_user.full_name,
            }
        return {
            "name": self.name,
            "display_name": self.display_name,
            "status": self.status,
            "relay": state.relay_desired_state,
            "oops": state.is_oopsed,
            "locked_out": state.is_locked_out,
            "current_user": current_user,
            "last_checkin": state.last_checkin,
            "last_update": state.last_update,
        }

    @property
    def as_dict(self) -> Dict[str, Any]:
        """Return a dict representation of this machine."""
        d: Dict[str, Any] = {
            "name": self.name,
            "authorizations_or": self.authorizations_or,
            "unauthorized_warn_only": self.unauthorized_warn_only,
            "always_enabled": self.always_enabled,
            "alias": self.alias,
        }
        if self.second_relay is not None:
            d["second_relay"] = self.second_relay.as_dict
        return d


class MachinesConfig:
    """Class representing machines configuration file."""

    def __init__(self) -> None:
        """Initialize MachinesConfig."""
        logger.debug("Initializing MachinesConfig")
        self.machines_by_name: Dict[str, Machine] = {}
        self.machines_by_alias: Dict[str, Machine] = {}
        #: Case-insensitive lookup maps (lowercased name/alias -> Machine), used
        #: by :py:meth:`get_machine` so Slack commands can match regardless of case.
        self.machines_by_name_lower: Dict[str, Machine] = {}
        self.machines_by_alias_lower: Dict[str, Machine] = {}
        self.machines: List[Machine] = []
        mdict: Dict[str, Any]
        mname: str
        for mname, mdict in self._load_and_validate_config().items():
            if "second_relay" in mdict:
                mdict["second_relay"] = SecondRelayConfig(**mdict["second_relay"])
            mach: Machine = Machine(name=mname, **mdict)
            self.machines.append(mach)
            self.machines_by_name[mach.name] = mach
            self.machines_by_name_lower[mach.name.lower()] = mach
            if mach.alias:
                self.machines_by_alias[mach.alias] = mach
        # Populate the case-insensitive alias map in a second pass, after every
        # machine name is known, so a collision is detected regardless of config
        # order. Two machines whose aliases (or an alias and another machine's
        # name) differ only by case would make lookups ambiguous, so we fail
        # fast rather than silently overwrite an entry.
        for mach in self.machines:
            if not mach.alias:
                continue
            alias_key: str = mach.alias.lower()
            existing: Optional[Machine] = self.machines_by_name_lower.get(
                alias_key
            ) or self.machines_by_alias_lower.get(alias_key)
            if existing is not None and existing is not mach:
                raise ValueError(
                    f"Machine alias '{mach.alias}' (machine '{mach.name}') "
                    f"collides case-insensitively with machine "
                    f"'{existing.name}'. Machine names and aliases must be "
                    f"unique when compared case-insensitively."
                )
            self.machines_by_alias_lower[alias_key] = mach
        self.load_time: float = time()

    def get_machine(self, name_or_alias: str) -> Optional[Machine]:
        """Get a machine by name or alias (case-insensitive)."""
        key: str = name_or_alias.lower()
        return self.machines_by_name_lower.get(key) or self.machines_by_alias_lower.get(
            key
        )

    def _load_and_validate_config(self) -> Dict[str, Dict[str, Any]]:
        """Load and validate the config file."""
        config: Dict[str, Dict[str, Any]] = cast(
            Dict[str, Dict[str, Any]],
            load_json_config("MACHINES_CONFIG", "machines.json"),
        )
        MachinesConfig.validate_config(config)
        return config

    @staticmethod
    def validate_config(config: Dict[str, Dict[str, Any]]) -> None:
        """Validate configuration via jsonschema."""
        logger.debug("Validating Users config")
        validate(config, CONFIG_SCHEMA)
        logger.debug("Users is valid")


class MachineState:
    """Object representing frozen state in time of a machine."""

    DEFAULT_DISPLAY_TEXT: str = "Please Insert\nRFID Card"

    OOPS_DISPLAY_TEXT: str = "Oops!! Please\ncheck/post Slack"

    LOCKOUT_DISPLAY_TEXT: str = "Down for\nmaintenance"

    ALWAYS_ON_DISPLAY_TEXT: str = "Always On"

    STATUS_LED_BRIGHTNESS: float = 0.5

    def __init__(self, machine: Machine, load_state: bool = True):
        """Initialize a new MachineState instance."""
        logger.debug("Instantiating new MachineState for %s", machine)
        self._lock: Lock = Lock()
        #: The Machine that this state is for
        self.machine: Machine = machine
        #: Float timestamp of the machine's last checkin time
        self.last_checkin: float | None = None
        #: Float timestamp of the last time that machine state changed in a
        #: meaningful way, i.e. RFID value or Oops
        self.last_update: float | None = None
        #: Value of the RFID card/fob in use, or None if not present.
        self.rfid_value: str | None = None
        #: Float timestamp when `rfid_value` last changed to a non-None value.
        self.rfid_present_since: float | None = None
        #: Current user logged in to the machine
        self.current_user: Optional[User] = None
        #: Whether the output relay should be on or not.
        self.relay_desired_state: bool = False
        #: Whether the machine's Oops button has been pressed.
        self.is_oopsed: bool = False
        #: Whether the machine is locked out from use.
        self.is_locked_out: bool = False
        #: Whether the machine is in an override login state
        self.is_override_login: bool = False
        #: Last reported output ammeter reading (if equipped).
        self.current_amps: float = 0
        #: Text currently displayed on the machine LCD screen
        self.display_text: str = self.DEFAULT_DISPLAY_TEXT
        #: Uptime of the machine's ESP32 in seconds
        self.uptime: float = 0.0
        #: RGB values for status LED; floats 0 to 1
        self.status_led_rgb: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        #: status LED brightness value; float 0 to 1
        self.status_led_brightness: float = 0.0
        #: ESP32 WiFi signal strength in dB
        self.wifi_signal_db: Optional[float] = None
        #: ESP32 WiFi signal strength in percent
        self.wifi_signal_percent: Optional[float] = None
        #: ESP32 internal temperature in °C
        self.internal_temperature_c: Optional[float] = None
        #: Whether the server wants the second relay energized.
        self.second_relay_desired_state: bool = False
        #: Authorization decision outcome for the second relay
        #: (granted/denied/warn/always_enabled), or None if no second relay.
        self.second_relay_authorization: Optional[str] = None
        #: Lifetime count of state-save timeouts for this machine. Persisted
        #: with the rest of the machine state (best-effort: a write that
        #: itself times out cannot persist the increment until the next
        #: successful save); surfaced as the
        #: ``mac_state_save_timeouts_total`` Prometheus counter from the
        #: in-memory value, which is always increment-correct because
        #: :meth:`save_cache` is single-flight per machine.
        self.state_save_timeouts: int = 0
        #: Tracks the in-flight ``asyncio.to_thread`` task spawned by
        #: :meth:`save_cache`. While this task is running (or hung on a
        #: stuck disk) subsequent calls to :meth:`save_cache` *join*
        #: the existing task instead of spawning more threads, so a
        #: single hung disk write cannot exhaust the default thread
        #: pool. Each joiner gets its own :data:`STATE_SAVE_TIMEOUT_SEC`
        #: budget, so brief overlap finishes successfully while a
        #: sustained hang produces independent timeout events on each
        #: subsequent request (which is what drives the
        #: :func:`mac_state_save_timeouts_total <prometheus>` counter
        #: and the Slack-on-second-timeout rule).
        self._save_task: Optional["asyncio.Task[None]"] = None
        #: Guards the check-and-set of :attr:`_save_task` so two
        #: concurrent callers cannot both observe ``_save_task`` as
        #: ``None``/``done()`` and spawn separate workers. Lazily
        #: created on first use so we don't bind to a specific event
        #: loop at construction time.
        self._save_spawn_lock: Optional[asyncio.Lock] = None
        #: Path to the directory to save machine state in
        self._state_dir: str = os.environ.get("MACHINE_STATE_DIR", "machine_state")
        os.makedirs(self._state_dir, exist_ok=True)
        #: Path to pickled state file
        self._state_path: str = os.path.join(
            self._state_dir, f"{self.machine.name}-state.pickle"
        )
        if load_state:
            self._load_from_cache()
        else:
            logger.warning("State loading disabled for machine %s", self.machine.name)

    def _save_cache(self) -> None:
        """Save machine state cache to disk (synchronous).

        Acquires the in-process lock and on-disk filelock, builds the state
        dict, and writes the pickle. Used directly by maintenance tools and
        tests; request handlers should call :meth:`save_cache` instead so
        the write is bounded by :data:`STATE_SAVE_TIMEOUT_SEC`.
        """
        logger.debug("Getting lock for state file: %s", self._state_path + ".lock")
        with self._lock:
            lock = FileLock(self._state_path + ".lock")
            with lock:
                data: Dict[str, Any] = {
                    "machine_name": self.machine.name,
                    "last_checkin": self.last_checkin,
                    "last_update": self.last_update,
                    "rfid_value": self.rfid_value,
                    "rfid_present_since": self.rfid_present_since,
                    "relay_desired_state": self.relay_desired_state,
                    "is_oopsed": self.is_oopsed,
                    "is_locked_out": self.is_locked_out,
                    "is_override_login": self.is_override_login,
                    "current_amps": self.current_amps,
                    "display_text": self.display_text,
                    "uptime": self.uptime,
                    "status_led_rgb": self.status_led_rgb,
                    "status_led_brightness": self.status_led_brightness,
                    "wifi_signal_db": self.wifi_signal_db,
                    "wifi_signal_percent": self.wifi_signal_percent,
                    "internal_temperature_c": self.internal_temperature_c,
                    "current_user": self.current_user,
                    "second_relay_desired_state": self.second_relay_desired_state,
                    "second_relay_authorization": self.second_relay_authorization,
                    "state_save_timeouts": self.state_save_timeouts,
                }
                logger.debug("Saving state to: %s", self._state_path)
                with open(self._state_path, "wb") as f:
                    pickle.dump(data, f, pickle.HIGHEST_PROTOCOL)
        logger.debug("State saved.")

    async def save_cache(self) -> None:
        """Save machine state cache to disk with a timeout.

        Single-flight per machine: only one save *thread* is
        outstanding at a time. Concurrent callers see the existing
        in-flight task and *join* it (awaiting the same task) rather
        than spawning a second thread that would also block on the
        same disk lock; this prevents thread-pool exhaustion under a
        sustained disk hang while heartbeats keep arriving.

        Whether the caller spawned the task or joined an existing
        one, it then awaits with its own :data:`STATE_SAVE_TIMEOUT_SEC`
        budget. Brief overlap (the existing save finishes within the
        joiner's budget) returns success without counting a timeout.
        A sustained hang produces an independent timeout event on
        each request that exceeds its budget; the second such event
        triggers the Slack notification.

        On timeout, the underlying thread is *shielded* and continues
        running (Python cannot cancel a thread blocked on file I/O);
        :attr:`state_save_timeouts` is incremented and
        :class:`StateSaveTimeoutError` is raised.
        """
        if self._save_spawn_lock is None:
            self._save_spawn_lock = asyncio.Lock()
        async with self._save_spawn_lock:
            existing = self._save_task
            if existing is not None and not existing.done():
                # Join the in-flight save: brief overlap finishes
                # quickly without spawning a second thread, while a
                # sustained hang lets us hit our own budget below.
                task = existing
            else:
                # Spawn the worker as a Task so we can both `shield`
                # it (so that wait_for cancelling does not propagate
                # to the underlying thread, which cannot be cancelled
                # anyway) and check `.done()` on subsequent calls.
                task = asyncio.create_task(asyncio.to_thread(self._save_cache))
                # If the underlying thread eventually completes after
                # we've timed out, consume any exception it produced
                # so the event loop doesn't log "Task exception was
                # never retrieved". Also clear our reference so
                # subsequent save_cache calls can spawn a new worker.
                task.add_done_callback(self._on_save_task_done)
                self._save_task = task

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=STATE_SAVE_TIMEOUT_SEC)
        except asyncio.TimeoutError as exc:
            count = self._record_save_timeout(reason="exceeded budget")
            raise StateSaveTimeoutError(
                f"State save for {self.machine.name} exceeded "
                f"{STATE_SAVE_TIMEOUT_SEC:.1f}s budget "
                f"(lifetime timeout count: {count})"
            ) from exc

    def _on_save_task_done(self, task: "asyncio.Task[None]") -> None:
        """Done-callback for the in-flight save task.

        Logs (and thus consumes) any exception the underlying
        :meth:`_save_cache` raised, so a thread that finishes after we
        have already timed out cannot leak unhandled exceptions into
        the event loop. Also clears :attr:`_save_task` if this is still
        the current task, so a subsequent successful save can run.
        """
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            exc = None
        if exc is not None:
            logger.warning(
                "Background state save for machine %s finished with "
                "an exception: %r",
                self.machine.name,
                exc,
            )
        if self._save_task is task:
            self._save_task = None

    def _record_save_timeout(self, reason: str) -> int:
        """Increment the timeout counter, log, and notify Slack.

        Returns the post-increment lifetime count so callers can
        include it in the raised exception.
        """
        self.state_save_timeouts += 1
        count = self.state_save_timeouts
        logger.error(
            "State save for machine %s timed out (%s); " "lifetime timeout count: %d",
            self.machine.name,
            reason,
            count,
        )
        self._notify_save_timeout(count)
        self._notify_fleet_save_timeout()
        return count

    def _notify_save_timeout(self, count: int) -> None:
        """Fire a fire-and-forget Slack notification on the 2nd save timeout.

        Skipped on the first timeout to tolerate single transient stalls;
        fired *exactly once* on the transition to 2 to avoid spamming
        ``SLACK_CONTROL_CHANNEL_ID`` under a sustained disk hang (where
        timeouts can arrive every ~10 s as MCU heartbeats keep coming).
        Operators monitoring the ``mac_state_save_timeouts_total``
        Prometheus counter can alert on sustained increase from there.
        """
        if count != 2:
            return
        slack: Optional["SlackHandler"] = current_app.config.get("SLACK_HANDLER")
        if slack is None:
            return
        msg = (
            f":warning: Machine `{self.machine.display_name}` had a state-save "
            f"timeout (>{STATE_SAVE_TIMEOUT_SEC:.1f}s); lifetime count is now "
            f"{count}. Disk may be hung; firmware was returned HTTP 503."
        )
        try:
            asyncio.create_task(
                slack.app.client.chat_postMessage(
                    channel=slack.control_channel_id,
                    text=msg,
                )
            )
        except RuntimeError:  # pragma: no cover - no running loop
            logger.debug(
                "No running event loop; skipping Slack save-timeout notification"
            )

    def _notify_fleet_save_timeout(self) -> None:
        """Fire a Slack alert if multiple machines hit timeouts in a short window.

        Complements :meth:`_notify_save_timeout`: that rule pages on
        the *second lifetime* timeout for one machine ("this machine
        is slow"); this rule pages when
        :data:`FLEET_TIMEOUT_THRESHOLD` *distinct* machines hit any
        timeout within :data:`FLEET_TIMEOUT_WINDOW_SEC` ("the disk is
        slow"). Cooldown via the tracker prevents re-paging during a
        sustained hang.
        """
        tracker: Optional[FleetTimeoutTracker] = current_app.config.get(
            "FLEET_TIMEOUT_TRACKER"
        )
        if tracker is None:
            return
        distinct: Optional[int] = tracker.record(self.machine.name)
        if distinct is None:
            return
        slack: Optional["SlackHandler"] = current_app.config.get("SLACK_HANDLER")
        if slack is None:
            return
        msg = (
            f":rotating_light: Fleet-wide state-save timeouts: "
            f"{distinct} distinct machines hit state-save timeouts within "
            f"{tracker.window_sec:.0f}s. Disk on the mac-server host is "
            f"likely saturated or hung. See "
            f"`mac_state_save_timeouts_total` in Prometheus."
        )
        try:
            asyncio.create_task(
                slack.app.client.chat_postMessage(
                    channel=slack.control_channel_id,
                    text=msg,
                )
            )
        except RuntimeError:  # pragma: no cover - no running loop
            logger.debug(
                "No running event loop; skipping fleet-wide save-timeout "
                "notification"
            )

    def _notify_status_webhook(
        self,
        event: str,
        user: Optional[User] = None,
        slack: Optional["SlackHandler"] = None,
    ) -> None:
        """Fire a status-change webhook, if a notifier is configured.

        No-op when ``WEBHOOK_NOTIFIER`` is unset (``STATUS_WEBHOOK_URL`` not
        configured). Called only from meaningful status-change code paths so
        the webhook never fires on ordinary MCU heartbeats. ``user`` is the
        actor involved in the event (e.g. the user who just logged out), which
        may differ from the machine's post-event ``current_user``.

        The notifier lives in the Quart app config. MCU-update and API request
        handlers run within a request context so it is reachable via
        :data:`current_app`; the Slack command handlers do **not** run within a
        request context, so when a :class:`SlackHandler` is passed we fall back
        to its held app reference (``slack.quart``).
        """
        notifier: Optional["WebhookNotifier"] = None
        try:
            notifier = current_app.config.get("WEBHOOK_NOTIFIER")
        except RuntimeError:
            # No application context (Slack command path, or a unit test
            # invoking a state method directly). Use the app held by the
            # Slack handler if we have one; otherwise there is nothing to do.
            if slack is not None:
                notifier = slack.quart.config.get("WEBHOOK_NOTIFIER")
        if notifier is None:
            return
        notifier.notify(self.machine, event, user=user)

    def _load_from_cache(self) -> None:
        """Load machine state cache from disk."""
        if not os.path.exists(self._state_path):
            logger.info("State file does not yet exist: %s", self._state_path)
            return
        logger.debug("Getting lock for state file: %s", self._state_path + ".lock")
        with self._lock:
            lock = FileLock(self._state_path + ".lock")
            with lock:
                logger.debug("Loading state from: %s", self._state_path)
                with open(self._state_path, "rb") as f:
                    data = pickle.load(f)
                for k, v in data.items():
                    if hasattr(self, k):
                        setattr(self, k, v)
        logger.debug("State loaded.")

    async def _handle_reboot(self) -> None:
        """Handle when the ESP32 (MCU) has rebooted since last checkin.

        This logs out the current user if logged in and resets the machine state.
        For always-enabled machines, restores the always-on state.
        """
        logging.getLogger("AUTH").warning(
            "Machine %s rebooted; resetting relay and RFID state",
            self.machine.display_name,
        )
        # locking handled in update()
        prior_user: Optional[User] = self.current_user
        self.current_user = None
        self.is_override_login = False
        # Restore always-enabled state if applicable
        if self.machine.always_enabled:
            self.relay_desired_state = True
            self.display_text = self.ALWAYS_ON_DISPLAY_TEXT
            self.status_led_rgb = (0.0, 1.0, 0.0)
            self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
        else:
            self.relay_desired_state = False
            self.display_text = self.DEFAULT_DISPLAY_TEXT
            self.status_led_rgb = (0.0, 0.0, 0.0)
            self.status_led_brightness = 0.0
        self._resolve_second_relay()
        self._notify_status_webhook("reboot", user=prior_user)
        # log to Slack, if enabled
        slack: Optional["SlackHandler"] = current_app.config.get("SLACK_HANDLER")
        if not slack:
            # Slack integration is not enabled
            return
        await slack.admin_log(f"Machine {self.machine.display_name} has rebooted.")

    def lockout(self) -> None:
        """Lock-out the machine."""
        logging.getLogger("OOPS").warning(
            "Machine %s was locked out for maintenance.", self.machine.display_name
        )
        with self._lock:
            self.is_locked_out = True
            self.relay_desired_state = False
            self.current_user = None
            self.display_text = self.LOCKOUT_DISPLAY_TEXT
            self.status_led_rgb = (1.0, 0.5, 0.0)
            self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
            self._resolve_second_relay()

    def unlock(self) -> None:
        """Un-lock-out the machine."""
        logging.getLogger("OOPS").warning(
            "Machine %s was removed from maintenance lock-out.",
            self.machine.display_name,
        )
        with self._lock:
            self.is_locked_out = False
            self.current_user = None
            # Restore always-enabled state if applicable
            if self.machine.always_enabled:
                self.relay_desired_state = True
                self.display_text = self.ALWAYS_ON_DISPLAY_TEXT
                self.status_led_rgb = (0.0, 1.0, 0.0)
                self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
            else:
                self.relay_desired_state = False
                self.display_text = self.DEFAULT_DISPLAY_TEXT
                self.status_led_rgb = (0.0, 0.0, 0.0)
                self.status_led_brightness = 0.0
            self._resolve_second_relay()

    def oops(self, do_locking: bool = True) -> None:
        """Oops the machine."""
        logging.getLogger("OOPS").warning(
            "Machine %s was Oopsed.", self.machine.display_name
        )
        locker = self._lock if do_locking else nullcontext()
        with locker:
            self.is_oopsed = True
            self.relay_desired_state = False
            self.current_user = None
            self.display_text = self.OOPS_DISPLAY_TEXT
            self.status_led_rgb = (1.0, 0.0, 0.0)
            self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
            self._resolve_second_relay()

    def unoops(self, do_locking: bool = True) -> None:
        """Un-oops the machine."""
        logging.getLogger("OOPS").warning(
            "Machine %s was un-Oopsed.", self.machine.display_name
        )
        locker = self._lock if do_locking else nullcontext()
        with locker:
            self.is_oopsed = False
            self.current_user = None
            # Restore always-enabled state if applicable
            if self.machine.always_enabled:
                self.relay_desired_state = True
                self.display_text = self.ALWAYS_ON_DISPLAY_TEXT
                self.status_led_rgb = (0.0, 1.0, 0.0)
                self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
            else:
                self.relay_desired_state = False
                self.display_text = self.DEFAULT_DISPLAY_TEXT
                self.status_led_rgb = (0.0, 0.0, 0.0)
                self.status_led_brightness = 0
            self._resolve_second_relay()

    async def update(
        self,
        users: UsersConfig,
        oops: bool = False,
        rfid_value: Optional[str] = None,
        uptime: Optional[float] = None,
        wifi_signal_db: Optional[float] = None,
        wifi_signal_percent: Optional[float] = None,
        internal_temperature_c: Optional[float] = None,
        amps: Optional[float] = None,
        second_relay_state: Optional[bool] = None,
    ) -> Dict[str, str | bool | float | List[float]]:
        """Handle an update to the machine via API."""
        if second_relay_state is not None and self.machine.second_relay is None:
            logger.debug(
                "MCU %s reported second_relay_state=%s but no second_relay "
                "configured; ignoring.",
                self.machine.name,
                second_relay_state,
            )
        if rfid_value is not None:
            rfid_value = rfid_value.rjust(10, "0")
        with self._lock:
            if amps is not None:
                self.current_amps = amps
            if uptime is not None:
                if uptime < self.uptime:
                    logger.warning(
                        "Uptime of %s is less than last uptime of %s; machine "
                        "control unit has rebooted",
                        uptime,
                        self.uptime,
                    )
                    await self._handle_reboot()
                self.uptime = uptime
            if wifi_signal_db is not None:
                self.wifi_signal_db = wifi_signal_db
            if wifi_signal_percent is not None:
                self.wifi_signal_percent = wifi_signal_percent
            if internal_temperature_c is not None:
                self.internal_temperature_c = internal_temperature_c
            self.last_checkin = time()
            if oops:
                # Set last_update *before* the handler runs: the handler fires
                # the status-change webhook synchronously (from status_dict), so
                # last_update must already reflect this event for the webhook
                # payload's last_update to match its own timestamp.
                self.last_update = time()
                await self._handle_oops(users)
            # Handle always-enabled machines - track RFID but maintain always-on state
            if (
                self.machine.always_enabled
                and not self.is_oopsed
                and not self.is_locked_out
            ):
                self.relay_desired_state = True
                self.display_text = self.ALWAYS_ON_DISPLAY_TEXT
                self.status_led_rgb = (0.0, 1.0, 0.0)
                self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
                self.last_update = time()
                # Track RFID changes for logging/auditing purposes
                if rfid_value != self.rfid_value:
                    await self._handle_rfid_tracking_always_enabled(users, rfid_value)
            elif rfid_value != self.rfid_value:
                # Set last_update *before* the handler for the same reason as
                # the oops branch above: the handler fires the webhook and the
                # payload reads last_update from status_dict.
                self.last_update = time()
                if rfid_value is None:
                    await self._handle_rfid_remove()
                else:
                    await self._handle_rfid_insert(users, rfid_value)
            else:
                # No RFID change - check for stale always-enabled state.
                # This handles the case where always_enabled config was changed
                # from true to false: the cached state has relay on but there's
                # no authorized user and the machine is no longer always-enabled.
                if (
                    self.relay_desired_state
                    and self.current_user is None
                    and not self.machine.always_enabled
                    and not self.is_oopsed
                    and not self.is_locked_out
                ):
                    logger.info(
                        "Resetting stale always-enabled state for machine %s",
                        self.machine.display_name,
                    )
                    self.relay_desired_state = False
                    self.display_text = self.DEFAULT_DISPLAY_TEXT
                    self.status_led_rgb = (0.0, 0.0, 0.0)
                    self.status_led_brightness = 0.0
                    self.last_update = time()
            self._resolve_second_relay()
        await self.save_cache()
        return self.machine_response

    async def _handle_oops(self, users: UsersConfig) -> None:
        """Handle oops button press."""
        ustr: str = ""
        uname: Optional[str] = None
        oops_user: Optional[User] = None
        if self.rfid_value:
            ustr = " RFID card is present but unknown."
            if user := users.users_by_fob.get(self.rfid_value):
                ustr = f" Current user is: {user.full_name}."
                uname = user.full_name
                oops_user = user
        logging.getLogger("OOPS").warning(
            "Machine %s was Oopsed.%s", self.machine.display_name, ustr
        )
        # locking handled in update()
        self.oops(do_locking=False)
        self._notify_status_webhook("oops", user=oops_user)
        # log to Slack, if enabled
        slack: Optional["SlackHandler"] = current_app.config.get("SLACK_HANDLER")
        if not slack:
            # Slack integration is not enabled
            return
        src = "Oops button"
        if self.rfid_value:
            src += " with RFID present"
        else:
            src += " without RFID present"
        await slack.log_oops(self.machine, src, user_name=uname)

    async def _handle_rfid_remove(self) -> None:
        """Handle RFID card removed."""
        was_override: bool = self.is_override_login
        departed_user: Optional[User] = self.current_user
        logging.getLogger("AUTH").info(
            "RFID logout on %s by %s; session duration %d seconds%s",
            self.machine.display_name,
            self.current_user.full_name if self.current_user else self.rfid_value,
            int(time() - cast(float, self.rfid_present_since)),
            " (override session)" if was_override else "",
        )
        log_str: str = (
            f"RFID logout on {self.machine.display_name} by "
            + (self.current_user.full_name if self.current_user else "unknown")
            + "; session duration "
            + naturaldelta(time() - cast(float, self.rfid_present_since))
        )
        if was_override:
            log_str += " (override session)"
        if self.machine.second_relay is not None:
            log_str += "; both relays off"
        # locking handled in update()
        self.rfid_value = None
        self.rfid_present_since = None
        self.current_user = None
        self.relay_desired_state = False
        self.is_override_login = False
        if was_override:
            # Restore oops/lockout display state
            if self.is_oopsed:
                self.display_text = self.OOPS_DISPLAY_TEXT
                self.status_led_rgb = (1.0, 0.0, 0.0)
                self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
            elif self.is_locked_out:
                self.display_text = self.LOCKOUT_DISPLAY_TEXT
                self.status_led_rgb = (1.0, 0.5, 0.0)
                self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
            else:
                # Admin cleared oops/lockout during override
                self.display_text = self.DEFAULT_DISPLAY_TEXT
                self.status_led_rgb = (0.0, 0.0, 0.0)
                self.status_led_brightness = 0.0
        elif not self.is_oopsed and not self.is_locked_out:
            self.display_text = self.DEFAULT_DISPLAY_TEXT
            self.status_led_rgb = (0.0, 0.0, 0.0)
            self.status_led_brightness = 0.0
        self._notify_status_webhook("logout", user=departed_user)
        # log to Slack, if enabled
        slack: Optional["SlackHandler"] = current_app.config.get("SLACK_HANDLER")
        if not slack:
            # Slack integration is not enabled
            return
        await slack.admin_log(log_str)

    async def _handle_rfid_insert(self, users: UsersConfig, rfid_value: str) -> None:
        """Handle change in the RFID value."""
        # locking handled in update()
        self.rfid_present_since = time()
        self.rfid_value = rfid_value
        user: Optional[User] = users.users_by_fob.get(rfid_value)
        slack: Optional["SlackHandler"] = current_app.config.get("SLACK_HANDLER")
        if not user:
            logging.getLogger("AUTH").warning(
                "RFID login attempt on %s by unknown fob %s",
                self.machine.display_name,
                rfid_value,
            )
            if self.is_oopsed or self.is_locked_out:
                if slack:
                    await slack.admin_log(
                        f"RFID login attempt on {self.machine.display_name} "
                        "by unknown fob when oopsed or locked out."
                    )
                return
            self.display_text = "Unknown RFID"
            self.status_led_rgb = (1.0, 0.0, 0.0)
            self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
            self._notify_status_webhook("unknown_fob")
            if slack:
                await slack.admin_log(
                    f"RFID login attempt on {self.machine.display_name} by unknown fob"
                )
            return
        # ok, we have a known user
        logname = f"{user.full_name} ({rfid_value})"
        # Check for override login on oopsed/locked-out machine
        if user.oops_override and (self.is_oopsed or self.is_locked_out):
            logging.getLogger("AUTH").info(
                "Override login on %s by %s",
                self.machine.display_name,
                logname,
            )
            self.is_override_login = True
            self.current_user = user
            self.relay_desired_state = True
            self.display_text = f"OVERRIDE BY\n{user.preferred_name}"
            self.status_led_rgb = (0.0, 1.0, 0.0)
            self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
            self._notify_status_webhook("override_login", user=user)
            if slack:
                await slack.log_override_login(self.machine, user.full_name)
            return
        if self.is_oopsed:
            logging.getLogger("AUTH").warning(
                "RFID login attempt while oopsed on %s by %s",
                self.machine.display_name,
                logname,
            )
            # don't change anything
            if slack:
                await slack.admin_log(
                    f"RFID login attempt on {self.machine.display_name} by "
                    f"{user.full_name} when oopsed."
                )
            return
        if self.is_locked_out:
            logging.getLogger("AUTH").warning(
                "RFID login attempt while locked out on %s by %s",
                self.machine.display_name,
                logname,
            )
            # don't change anything
            if slack:
                await slack.admin_log(
                    f"RFID login attempt on {self.machine.display_name} by "
                    f"{user.full_name} when machine locked-out."
                )
            return
        if await self._user_is_authorized(user, slack=slack):
            logging.getLogger("AUTH").info(
                "User %s (%s) authorized for %s; session start",
                user.full_name,
                user.account_id,
                self.machine.display_name,
            )
            self.current_user = user
            self.relay_desired_state = True
            self.display_text = f"Welcome,\n{user.preferred_name}"
            self.status_led_rgb = (0.0, 1.0, 0.0)
            self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
            # Compute second-relay decision now (no log yet) so we can craft
            # the Slack message with the accessory clause; update() will emit
            # the structured AUTH log later.
            self._resolve_second_relay(emit_log=False)
            self._notify_status_webhook("login", user=user)
            if slack:
                msg = (
                    f"RFID login on {self.machine.display_name} by authorized user "
                    f"{user.full_name}"
                )
                sr = self.machine.second_relay
                if sr is not None:
                    accessory = sr.alias if sr.alias else "second relay"
                    authz = self.second_relay_authorization
                    if authz == "granted":
                        msg += f"; {accessory} authorized"
                    elif authz == "denied":
                        msg += f"; {accessory} NOT authorized — relay off"
                    elif authz == "warn":
                        msg += f"; {accessory} WARN-ONLY override — relay on"
                    elif authz == "always_enabled":
                        msg += f"; {accessory} always-enabled — relay on"
                await slack.admin_log(msg)
        else:
            logging.getLogger("AUTH").info(
                "User %s (%s) UNAUTHORIZED for %s",
                user.full_name,
                user.account_id,
                self.machine.display_name,
            )
            self.relay_desired_state = False
            self.display_text = "Unauthorized"
            self.status_led_rgb = (1.0, 0.5, 0.0)  # orange
            self.status_led_brightness = self.STATUS_LED_BRIGHTNESS
            self._notify_status_webhook("unauthorized", user=user)
            if slack:
                await slack.admin_log(
                    f"rejected RFID login on {self.machine.display_name} by "
                    f"UNAUTHORIZED user {user.full_name}"
                )

    async def _handle_rfid_tracking_always_enabled(
        self, users: UsersConfig, rfid_value: Optional[str]
    ) -> None:
        """Track RFID changes for always-enabled machines without changing state.

        This method logs RFID insertions and removals for auditing purposes while
        maintaining the always-on state of the machine.
        """
        # locking handled in update()
        if rfid_value is None:
            # RFID removed
            logging.getLogger("AUTH").info(
                "RFID removed on always-enabled machine %s (was %s); session duration %d seconds",
                self.machine.display_name,
                self.current_user.full_name if self.current_user else self.rfid_value,
                (
                    time() - cast(float, self.rfid_present_since)
                    if self.rfid_present_since
                    else 0
                ),
            )
            departed_user: Optional[User] = self.current_user
            self.rfid_value = None
            self.rfid_present_since = None
            self.current_user = None
            # State remains always-on (relay/display/LED not changed)
            self._notify_status_webhook("logout", user=departed_user)
        else:
            # RFID inserted
            self.rfid_present_since = time()
            self.rfid_value = rfid_value
            user: Optional[User] = users.users_by_fob.get(rfid_value)
            if user:
                self.current_user = user
                logging.getLogger("AUTH").info(
                    "RFID inserted on always-enabled machine %s by %s (%s)",
                    self.machine.display_name,
                    user.full_name,
                    rfid_value,
                )
                self._notify_status_webhook("login", user=user)
            else:
                logging.getLogger("AUTH").warning(
                    "RFID inserted on always-enabled machine %s by unknown fob %s",
                    self.machine.display_name,
                    rfid_value,
                )
                self._notify_status_webhook("unknown_fob")
            # State remains always-on (relay/display/LED not changed)

    def _user_is_second_authorized(self, user: User) -> bool:
        """Return whether user holds any of the second-relay authorizations."""
        if self.machine.second_relay is None:
            return False
        for auth in self.machine.second_relay.authorizations_or:
            if auth in user.authorizations:
                return True
        return False

    def _resolve_second_relay(self, emit_log: bool = True) -> None:
        """Compute desired second-relay state and authorization decision.

        Called after every primary-state mutation. Sets
        ``second_relay_desired_state`` and ``second_relay_authorization``
        per the decision tree in data-model.md. Fails closed on unexpected
        errors (False / "denied"). Emits a structured AUTH log line for
        each decision unless ``emit_log`` is False (used to avoid double
        logging when callers will log later).
        """
        try:
            if self.machine.second_relay is None:
                self.second_relay_desired_state = False
                self.second_relay_authorization = None
                return
            if not self.relay_desired_state:
                self.second_relay_desired_state = False
                self.second_relay_authorization = None
                return
            sr = self.machine.second_relay
            if sr.always_enabled:
                self.second_relay_desired_state = True
                self.second_relay_authorization = "always_enabled"
            else:
                user: Optional[User] = self.current_user
                if user is None:
                    # No identified operator (e.g., root always_enabled with
                    # no RFID present). warn-only does not apply because
                    # there is no operator to warn about — fail closed.
                    self.second_relay_desired_state = False
                    self.second_relay_authorization = None
                elif self._user_is_second_authorized(user):
                    self.second_relay_desired_state = True
                    self.second_relay_authorization = "granted"
                elif sr.unauthorized_warn_only:
                    self.second_relay_desired_state = True
                    self.second_relay_authorization = "warn"
                else:
                    self.second_relay_desired_state = False
                    self.second_relay_authorization = "denied"
        except Exception as ex:
            logger.error(
                "Error resolving second relay for %s: %s",
                self.machine.name,
                ex,
                exc_info=True,
            )
            self.second_relay_desired_state = False
            self.second_relay_authorization = "denied"
        if emit_log:
            self._log_second_relay_decision()

    def _log_second_relay_decision(self) -> None:
        """Emit a structured AUTH log line for the current second-relay decision."""
        if self.machine.second_relay is None or self.second_relay_authorization is None:
            return
        sr = self.machine.second_relay
        accessory: str = sr.alias if sr.alias else "second relay"
        machine_label: str = self.machine.display_name
        user_name: str = self.current_user.full_name if self.current_user else "<none>"
        authz = self.second_relay_authorization
        auth_log = logging.getLogger("AUTH")
        if authz == "granted":
            auth_log.info(
                "User %s authorized for accessory %s on machine %s",
                user_name,
                accessory,
                machine_label,
            )
        elif authz == "denied":
            auth_log.info(
                "User %s UNAUTHORIZED for accessory %s on machine %s",
                user_name,
                accessory,
                machine_label,
            )
        elif authz == "warn":
            auth_log.warning(
                "User %s authorized for accessory %s on machine %s "
                "(warn-only override)",
                user_name,
                accessory,
                machine_label,
            )
        elif authz == "always_enabled":
            auth_log.info(
                "Accessory %s on machine %s always-enabled",
                accessory,
                machine_label,
            )

    async def _user_is_authorized(
        self, user: User, slack: Optional["SlackHandler"] = None
    ) -> bool:
        """Return whether user is authorized for this machine."""
        for auth in self.machine.authorizations_or:
            if auth in user.authorizations:
                logging.getLogger("AUTH").info(
                    "User %s (%s) authorized for %s based on %s",
                    user.full_name,
                    user.account_id,
                    self.machine.display_name,
                    auth,
                )
                return True
        if self.machine.unauthorized_warn_only:
            logging.getLogger("AUTH").warning(
                "User %s (%s) authorized for %s based on "
                "unauthorized_warn_only==True",
                user.full_name,
                user.account_id,
                self.machine.display_name,
            )
            if slack:
                await slack.admin_log(
                    f"WARNING - Authorizing user {user.full_name} for "
                    f"{self.machine.display_name} based on unauthorized_warn_only "
                    "setting for machine. User is NOT authorized for this "
                    "machine."
                )
            return True
        return False

    @property
    def machine_response(self) -> Dict[str, str | bool | float | List[float]]:
        """Return the response dict to send to the machine."""
        return {
            "relay": self.relay_desired_state,
            "display": self.display_text,
            "oops_led": self.is_oopsed,
            "status_led_rgb": [x for x in self.status_led_rgb],
            "status_led_brightness": self.status_led_brightness,
            "second_relay": self.second_relay_desired_state,
        }
