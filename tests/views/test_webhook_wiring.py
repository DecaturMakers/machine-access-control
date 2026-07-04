"""Integration tests that the status webhook fires from the update path."""

from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from unittest.mock import AsyncMock
from unittest.mock import Mock

from quart import Quart
from quart.typing import TestClientProtocol

from .quart_test_helpers import app_and_client


def _heartbeat(machine_name: str, **overrides: Any) -> Dict[str, Any]:
    """Return a minimal /api/machine/update payload."""
    body: Dict[str, Any] = {
        "machine_name": machine_name,
        "oops": False,
        "rfid_value": "",
        "uptime": 100.0,
        "wifi_signal_db": -50,
        "wifi_signal_percent": 90,
        "internal_temperature_c": 50.0,
    }
    body.update(overrides)
    return body


def _events(notify: Mock) -> List[str]:
    """Return the ordered list of event names passed to notifier.notify."""
    return [call.args[1] for call in notify.call_args_list]


class TestWebhookWiring:
    """Verify meaningful updates fire the webhook and heartbeats do not."""

    def _app_with_notifier(self, tmp_path: Path) -> Any:
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        notifier = Mock()
        notifier.notify = Mock()
        app.config["WEBHOOK_NOTIFIER"] = notifier
        return app, client, notifier

    async def test_heartbeat_does_not_fire(self, tmp_path: Path) -> None:
        """An empty-RFID heartbeat is not a meaningful change; no webhook."""
        app, client, notifier = self._app_with_notifier(tmp_path)
        await client.post("/api/machine/update", json=_heartbeat("metal-mill"))
        await client.post("/api/machine/update", json=_heartbeat("metal-mill"))
        notifier.notify.assert_not_called()

    async def test_login_then_logout_fire(self, tmp_path: Path) -> None:
        """An authorized login and the following logout each fire once."""
        app, client, notifier = self._app_with_notifier(tmp_path)
        # Ashley Williams (fob 8114346998) is authorized for Metal Mill.
        await client.post(
            "/api/machine/update",
            json=_heartbeat("metal-mill", rfid_value="8114346998"),
        )
        await client.post("/api/machine/update", json=_heartbeat("metal-mill"))
        assert _events(notifier.notify) == ["login", "logout"]
        # login carries the acting user
        login_call = notifier.notify.call_args_list[0]
        assert login_call.kwargs["user"].full_name == "Ashley Williams"
        # logout carries the departed user
        logout_call = notifier.notify.call_args_list[1]
        assert logout_call.kwargs["user"].full_name == "Ashley Williams"

    async def test_unauthorized_fires(self, tmp_path: Path) -> None:
        """An unauthorized fob on a restrictive machine fires 'unauthorized'."""
        app, client, notifier = self._app_with_notifier(tmp_path)
        # Kenneth Hunter (0091703745) lacks Metal Lathe on restrictive-lathe.
        await client.post(
            "/api/machine/update",
            json=_heartbeat("restrictive-lathe", rfid_value="0091703745"),
        )
        assert _events(notifier.notify) == ["unauthorized"]

    async def test_unknown_fob_fires(self, tmp_path: Path) -> None:
        """An unknown fob fires 'unknown_fob' with no user."""
        app, client, notifier = self._app_with_notifier(tmp_path)
        await client.post(
            "/api/machine/update",
            json=_heartbeat("metal-mill", rfid_value="9999999999"),
        )
        assert _events(notifier.notify) == ["unknown_fob"]
        assert notifier.notify.call_args_list[0].kwargs["user"] is None

    async def test_oops_button_fires(self, tmp_path: Path) -> None:
        """Pressing the oops button fires 'oops'."""
        app, client, notifier = self._app_with_notifier(tmp_path)
        await client.post(
            "/api/machine/update", json=_heartbeat("metal-mill", oops=True)
        )
        assert _events(notifier.notify) == ["oops"]

    async def test_api_oops_and_clear_fire(self, tmp_path: Path) -> None:
        """POST/DELETE oops control endpoints fire 'oops'/'unoops'."""
        app, client, notifier = self._app_with_notifier(tmp_path)
        await client.post("/api/machine/oops/metal-mill")
        await client.delete("/api/machine/oops/metal-mill")
        assert _events(notifier.notify) == ["oops", "unoops"]

    async def test_api_lockout_and_unlock_fire(self, tmp_path: Path) -> None:
        """POST/DELETE lockout control endpoints fire 'lockout'/'unlock'."""
        app, client, notifier = self._app_with_notifier(tmp_path)
        await client.post("/api/machine/locked_out/metal-mill")
        await client.delete("/api/machine/locked_out/metal-mill")
        assert _events(notifier.notify) == ["lockout", "unlock"]

    async def test_always_enabled_login_logout(self, tmp_path: Path) -> None:
        """Always-on machines still fire login/logout for the tracked user."""
        app, client, notifier = self._app_with_notifier(tmp_path)
        # known user login on the always-on machine, then removal
        await client.post(
            "/api/machine/update",
            json=_heartbeat("always-on-machine", rfid_value="8114346998"),
        )
        await client.post("/api/machine/update", json=_heartbeat("always-on-machine"))
        assert _events(notifier.notify) == ["login", "logout"]

    async def test_always_enabled_unknown_fob(self, tmp_path: Path) -> None:
        """An unknown fob on an always-on machine fires 'unknown_fob'."""
        app, client, notifier = self._app_with_notifier(tmp_path)
        await client.post(
            "/api/machine/update",
            json=_heartbeat("always-on-machine", rfid_value="9999999999"),
        )
        assert _events(notifier.notify) == ["unknown_fob"]

    async def test_slack_path_fires_via_handler_app(self, tmp_path: Path) -> None:
        """A Slack-initiated oops (no request context) fires via slack.quart."""
        app, client = app_and_client(tmp_path)
        notifier = Mock()
        notifier.notify = Mock()
        app.config["WEBHOOK_NOTIFIER"] = notifier
        # Fake Slack handler holding the app, as the real SlackHandler does.
        fake_slack = Mock()
        fake_slack.quart = app
        fake_slack.log_oops = AsyncMock()
        mach = app.config["MACHINES"].machines_by_name["metal-mill"]
        # Called outside any request context, exactly like the Slack callback.
        await mach.oops(slack=fake_slack)
        assert _events(notifier.notify) == ["oops"]
        fake_slack.log_oops.assert_awaited_once()

    async def test_disabled_notifier_is_noop(self, tmp_path: Path) -> None:
        """With no notifier configured, meaningful updates still succeed."""
        app, client = app_and_client(tmp_path)
        assert app.config["WEBHOOK_NOTIFIER"] is None
        resp = await client.post(
            "/api/machine/update",
            json=_heartbeat("metal-mill", rfid_value="8114346998"),
        )
        assert resp.status_code == 200
