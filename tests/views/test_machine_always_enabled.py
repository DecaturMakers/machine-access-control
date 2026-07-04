"""Tests for always-enabled machines."""

from pathlib import Path
from unittest.mock import patch

from freezegun import freeze_time
from quart import Quart
from quart import Response
from quart.typing import TestClientProtocol

from dm_mac.models.machine import Machine
from dm_mac.models.machine import MachineState

from .quart_test_helpers import app_and_client


class TestAlwaysEnabledMachine:
    """Tests for always-enabled machine functionality."""

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_always_enabled_basic(self, tmp_path: Path) -> None:
        """Test always-enabled machine shows 'Always On' with relay on."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # send request
        mname: str = "always-on-machine"
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 12.3,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": True,
            "display": MachineState.ALWAYS_ON_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.ALWAYS_ON_DISPLAY_TEXT
        assert ms.relay_desired_state is True
        assert ms.status_led_rgb == (0.0, 1.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_always_enabled_oopsed(self, tmp_path: Path) -> None:
        """Test always-enabled machine exhibits correct Oops behavior."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        mname: str = "always-on-machine"

        # First, machine should be in always-on state
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 12.3,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        json_response = await response.json
        assert json_response["relay"] is True
        assert json_response["display"] == MachineState.ALWAYS_ON_DISPLAY_TEXT

        # Oops the machine
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": True,
                "rfid_value": "",
                "uptime": 13.5,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        json_response = await response.json
        assert json_response == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }

        # Release oops button (oops=false) - machine stays oopsed
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 14.7,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        json_response = await response.json
        # Machine stays oopsed when button is released
        assert json_response == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }

        # Un-oops via API endpoint
        response = await client.delete(f"/api/machine/oops/{mname}")
        assert response.status_code == 200

        # Now machine should return to always-on state
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 15.9,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        json_response = await response.json
        # After un-oops, always-enabled machine returns to always-on state
        assert json_response == {
            "relay": True,
            "display": MachineState.ALWAYS_ON_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_always_enabled_ignores_rfid_insert(self, tmp_path: Path) -> None:
        """Test always-enabled machine tracks RFID but maintains always-on state."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        mname: str = "always-on-machine"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]

        # Insert an RFID card (authorized user)
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "8114346998",  # Ashley Williams from users.json
                "uptime": 12.3,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # Machine should still show "Always On", not a welcome message
        assert response.status_code == 200
        json_response = await response.json
        assert json_response == {
            "relay": True,
            "display": MachineState.ALWAYS_ON_DISPLAY_TEXT,  # NOT "Welcome, <name>"
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # Verify RFID value is tracked for auditing
        assert m.state.rfid_value == "8114346998"
        assert m.state.current_user is not None
        assert m.state.current_user.full_name == "Ashley Williams"
        assert m.state.rfid_present_since == 1689477248.0

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_always_enabled_ignores_rfid_remove(self, tmp_path: Path) -> None:
        """Test always-enabled machine tracks RFID removal but maintains always-on state."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        mname: str = "always-on-machine"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]

        # Insert an RFID card first
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "8114346998",  # Ashley Williams
                "uptime": 12.3,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        json_response = await response.json
        assert json_response["relay"] is True
        # Verify RFID was tracked
        assert m.state.rfid_value == "8114346998"
        assert m.state.current_user is not None

        # Remove the RFID card
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",  # Empty = card removed
                "uptime": 13.5,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # Machine should still be on with "Always On" display
        assert response.status_code == 200
        json_response = await response.json
        assert json_response == {
            "relay": True,  # Still on!
            "display": MachineState.ALWAYS_ON_DISPLAY_TEXT,  # Still "Always On"
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # Verify RFID removal was tracked
        assert m.state.rfid_value is None
        assert m.state.current_user is None
        assert m.state.rfid_present_since is None

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_always_enabled_first_contact(self, tmp_path: Path) -> None:
        """Test always-enabled machine is immediately enabled on first contact."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        mname: str = "always-on-machine"

        # First contact - no RFID, no oops, brand new machine
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 1.0,  # Just started
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # Machine should be immediately enabled
        assert response.status_code == 200
        json_response = await response.json
        assert json_response == {
            "relay": True,  # On immediately!
            "display": MachineState.ALWAYS_ON_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_always_enabled_last_update_only_on_change(
        self, tmp_path: Path
    ) -> None:
        """Always-on machines bump last_update only on a real change (transition
        into always-on or a tracked RFID change), not on steady-state
        heartbeats — so /api/machines and Prometheus don't show a perpetually
        "now" last_update for an idle always-on machine."""
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        mname: str = "always-on-machine"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]

        def heartbeat(rfid: str = "") -> dict:
            return {
                "machine_name": mname,
                "oops": False,
                "rfid_value": rfid,
                "uptime": 10.0,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            }

        # First contact: relay transitions off -> on, so last_update is set.
        await client.post("/api/machine/update", json=heartbeat())
        assert m.state.relay_desired_state is True
        assert m.state.last_update == 1689477248.0

        # Steady-state heartbeat (relay already on, no RFID change): last_update
        # must NOT be bumped. A sentinel detects any unwanted write.
        m.state.last_update = 111.0
        await client.post("/api/machine/update", json=heartbeat())
        assert m.state.last_update == 111.0

        # RFID login (tracked change): last_update is bumped to now.
        m.state.last_update = 111.0
        await client.post("/api/machine/update", json=heartbeat(rfid="8114346998"))
        assert m.state.last_update == 1689477248.0

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_always_enabled_unlock(self, tmp_path: Path) -> None:
        """Test always-enabled machine restores always-on state after unlock."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        mname: str = "always-on-machine"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]

        # Lock out the machine
        await client.post(f"/api/machine/locked_out/{mname}")
        assert m.state.is_locked_out is True

        # Unlock the machine
        response: Response = await client.delete(f"/api/machine/locked_out/{mname}")
        assert response.status_code == 200

        # Machine should return to always-on state
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 12.3,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        json_response = await response.json
        assert json_response == {
            "relay": True,
            "display": MachineState.ALWAYS_ON_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_always_enabled_reboot(self, tmp_path: Path) -> None:
        """Test always-enabled machine restores always-on state after reboot."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        mname: str = "always-on-machine"

        # First update to establish baseline
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 100.0,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200

        # Simulate reboot by sending lower uptime
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 1.0,  # Lower uptime = reboot
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        json_response = await response.json
        # After reboot, always-enabled machine should be back to always-on state
        assert json_response == {
            "relay": True,
            "display": MachineState.ALWAYS_ON_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_always_enabled_config_change_to_disabled(
        self, tmp_path: Path
    ) -> None:
        """Test machine resets to disabled when always_enabled config changes to false.

        This tests the bug fix where a machine configured with always_enabled=true
        that later has that config changed to always_enabled=false should reset
        to disabled state on the next update, even without an RFID card change.
        """
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        mname: str = "always-on-machine"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]

        # Verify machine starts with always_enabled=true
        assert m.always_enabled is True

        # First update to establish the always-enabled state
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 12.3,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        json_response = await response.json
        # Machine should be in always-on state
        assert json_response["relay"] is True
        assert json_response["display"] == MachineState.ALWAYS_ON_DISPLAY_TEXT
        assert json_response["status_led_rgb"] == [0.0, 1.0, 0.0]

        # Verify internal state
        assert m.state.relay_desired_state is True
        assert m.state.display_text == MachineState.ALWAYS_ON_DISPLAY_TEXT
        assert m.state.current_user is None  # No user, just always-enabled

        # Simulate config change: set always_enabled to false
        # This simulates what happens when machines.json is edited and reloaded
        m.always_enabled = False

        # Send another update with NO RFID change (still empty)
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",  # Same as before - no card
                "uptime": 13.5,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        json_response = await response.json

        # Machine should now be in disabled state (the bug fix)
        assert json_response == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }

        # Verify internal state was reset
        assert m.state.relay_desired_state is False
        assert m.state.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert m.state.status_led_rgb == (0.0, 0.0, 0.0)
        assert m.state.status_led_brightness == 0.0
