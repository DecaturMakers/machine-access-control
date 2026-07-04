"""Tests for /machine API endpoints."""

from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import call
from unittest.mock import patch

from freezegun import freeze_time
from quart import Quart
from quart import Response
from quart.typing import TestClientProtocol

from dm_mac.models.machine import Machine
from dm_mac.models.machine import MachineState
from dm_mac.slack_handler import SlackHandler

from .quart_test_helpers import app_and_client


class TestRouteSpecialCases:
    """Tests for /machine/update API endpoint special cases."""

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_unknown_machine(self, tmp_path: Path) -> None:
        """Test unknown machine."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # send request
        mname: str = "unknown-machine-name"
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
        assert response.status_code == 404
        assert await response.json == {
            "error": "No such machine: unknown-machine-name",
        }

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_execption(self, tmp_path: Path) -> None:
        """Test exception during machine update."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # send request
        mname: str = "metal-mill"
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
                "foo": "bar",
            },
        )
        # check response
        assert response.status_code == 500
        assert await response.json == {
            "error": "MachineState.update() got an unexpected keyword "
            "argument 'foo'",
        }

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    async def test_state_save_timeout_returns_503(self, tmp_path: Path) -> None:
        """Verify state-save timeout surfaces as HTTP 503 to firmware."""
        from dm_mac.models.machine import StateSaveTimeoutError

        app, client = app_and_client(tmp_path)
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]

        async def boom() -> None:
            m.state.state_save_timeouts += 1
            raise StateSaveTimeoutError("simulated")

        with patch.object(m.state, "save_cache", side_effect=boom):
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
        assert response.status_code == 503
        assert await response.json == {"error": "state save timeout"}


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestUpdateNewMachine:
    """Tests for /machine/update API endpoint for a brand new machine."""

    async def test_initial_update(self, tmp_path: Path) -> None:
        """Test first update for a new machine."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # send request
        mname: str = "metal-mill"
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
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0, 0, 0],
            "status_led_brightness": 0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 12.3
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.relay_desired_state is False
        assert ms.last_update is None
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0

    async def test_initial_update_with_amps(self, tmp_path: Path) -> None:
        """Test first update for a new machine."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # send request
        mname: str = "metal-mill"
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
                "amps": 0.0,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0, 0, 0],
            "status_led_brightness": 0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 12.3
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.relay_desired_state is False
        assert ms.last_update is None
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0

    async def test_empty_update(self, tmp_path: Path) -> None:
        """Test first incorrectly empty update for a new machine."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # send request
        mname: str = "metal-mill"
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0, 0, 0],
            "status_led_brightness": 0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 0.0
        assert ms.wifi_signal_db is None
        assert ms.wifi_signal_percent is None
        assert ms.internal_temperature_c is None
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.relay_desired_state is False
        assert ms.last_update is None
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestOops:
    """Tests for oops button being pressed."""

    async def test_oops_without_user(self, tmp_path: Path) -> None:
        """Test oops button pressed with no user logged in."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": True,
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
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0, 0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 12.3
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is True
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_oops_without_user_slack(self, tmp_path: Path) -> None:
        """Test oops button pressed with no user logged in."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": True,
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
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0, 0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 12.3
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is True
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert slack.mock_calls == [
            call.log_oops(m, "Oops button without RFID present", user_name=None)
        ]

    async def test_oops_released_without_user(self, tmp_path: Path) -> None:
        """Test nothing different happens when oops button is released."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.is_oopsed = True
        m.state.relay_desired_state = False
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.last_checkin = 1689477200.0
        m.state.last_update = 1689477200.0
        m.state.uptime = 12.3
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0, 0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is True
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477200.0
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_oops_with_user(self, tmp_path: Path) -> None:
        """Test oops button pressed with a user logged in (and relay on)."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = True
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.status_led_rgb = (0.0, 1.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Welcome,\nPKenneth"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": True,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is True
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477200.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_oops_with_user_slack(self, tmp_path: Path) -> None:
        """Test oops button pressed with a user logged in (and relay on)."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = True
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.status_led_rgb = (0.0, 1.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Welcome,\nPKenneth"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": True,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is True
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477200.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert slack.mock_calls == [
            call.log_oops(
                m, "Oops button with RFID present", user_name="Kenneth Hunter"
            )
        ]

    async def test_oops_released_with_user(self, tmp_path: Path) -> None:
        """Test nothing different happens when oops button is released."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = None
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.is_oopsed = True
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is True
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477200.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477200.0
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_oops_unknown_user(self, tmp_path: Path) -> None:
        """Test oops button pressed with an unknown user logged in."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0123456789"
        m.state.current_user = None
        m.state.status_led_rgb = (0.0, 0.0, 0.0)
        m.state.status_led_brightness = 0.0
        m.state.display_text = MachineState.DEFAULT_DISPLAY_TEXT
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": True,
                "rfid_value": "0123456789",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is True
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0123456789"
        assert ms.rfid_present_since == 1689477200.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestLockOut:
    """Tests for locking-out and unlocking a machine."""

    async def test_lockout_no_user(self, tmp_path: Path) -> None:
        """Test locking out a machine with no user logged in."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.last_update = 1689477248.0
        m.state.last_checkin = 1689477248.0
        with patch("dm_mac.models.machine.current_app", app):
            await m.lockout()
        # send request
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
            "relay": False,
            "display": MachineState.LOCKOUT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [1.0, 0.5, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.LOCKOUT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 12.3
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is True
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.5, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_lockout_with_user(self, tmp_path: Path) -> None:
        """Test locking out a machine with a user logged in."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = True
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.status_led_rgb = (0.0, 1.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Welcome,\nPKenneth"
        with patch("dm_mac.models.machine.current_app", app):
            await m.lockout()
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.LOCKOUT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [1.0, 0.5, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.LOCKOUT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is True
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477200.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        # lockout() bumps last_update (meaningful state change) to "now"
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.5, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_unlock(self, tmp_path: Path) -> None:
        """Test unlocking a machine."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.last_update = 1689477248.0
        m.state.last_checkin = 1689477248.0
        m.state.is_locked_out = True
        m.state.relay_desired_state = False
        m.state.current_user = None
        m.state.display_text = MachineState.LOCKOUT_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.5, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        with patch("dm_mac.models.machine.current_app", app):
            await m.unlock()
        # send request
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
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 12.3
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestReboot:
    """Test when the machine reboots."""

    async def test_reboot_without_slack(self, tmp_path: Path) -> None:
        """Test reboot with a user logged in (and relay on)."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 12345.6
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = True
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.status_led_rgb = (0.0, 1.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Welcome,\nPKenneth"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477200.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        # _handle_reboot() bumps last_update (machine reset) to "now"
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0

    async def test_reboot_with_slack(self, tmp_path: Path) -> None:
        """Test reboot with a user logged in (and relay on)."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 12345.6
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = True
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.status_led_rgb = (0.0, 1.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Welcome,\nPKenneth"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477200.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        # _handle_reboot() bumps last_update (machine reset) to "now"
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0
        assert slack.mock_calls == [call.admin_log("Machine hammer has rebooted.")]


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestRfidChanged:
    """Tests for RFID value changed in a normal state.

    i.e. not oopsed, locked out, or set to unauthorized_warn_only.
    """

    async def test_rfid_authorized_inserted(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "8114346998",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": True,
            "display": "Welcome,\nPAshley",
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == "Welcome,\nPAshley"
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "8114346998"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user == app.config["USERS"].users_by_fob["8114346998"]
        assert ms.relay_desired_state is True
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 1.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_rfid_authorized_inserted_slack(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "8114346998",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": True,
            "display": "Welcome,\nPAshley",
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == "Welcome,\nPAshley"
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "8114346998"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user == app.config["USERS"].users_by_fob["8114346998"]
        assert ms.relay_desired_state is True
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 1.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert slack.mock_calls == [
            call.admin_log(
                "RFID login on Metal Mill by authorized user Ashley Williams"
            )
        ]

    async def test_rfid_authorized_inserted_zeropad(self, tmp_path: Path) -> None:
        """Test when an auth RFID card is inserted but < 10 characters."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": True,
            "display": "Welcome,\nPKenneth",
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == "Welcome,\nPKenneth"
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user == app.config["USERS"].users_by_fob["0091703745"]
        assert ms.relay_desired_state is True
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 1.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_rfid_authorized_removed(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = True
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.status_led_rgb = (0.0, 1.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Welcome,\nPKenneth"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0

    async def test_rfid_authorized_removed_slack(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = True
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.status_led_rgb = (0.0, 1.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Welcome,\nPKenneth"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0
        assert slack.mock_calls == [
            call.admin_log(
                "RFID logout on hammer by Kenneth Hunter; session "
                "duration 48 seconds"
            )
        ]

    async def test_rfid_unauthorized_inserted_zeropad(self, tmp_path: Path) -> None:
        """Test when an unauth RFID card is inserted but < 10 characters."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": "Unauthorized",
            "oops_led": False,
            "status_led_rgb": [1.0, 0.5, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == "Unauthorized"
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.5, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_rfid_unauthorized_inserted_zeropad_slack(
        self, tmp_path: Path
    ) -> None:
        """Test when an unauth RFID card is inserted but < 10 characters."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": "Unauthorized",
            "oops_led": False,
            "status_led_rgb": [1.0, 0.5, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == "Unauthorized"
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.5, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert slack.mock_calls == [
            call.admin_log(
                "rejected RFID login on Metal Mill by UNAUTHORIZED user "
                "Kenneth Hunter"
            )
        ]

    async def test_rfid_unauthorized_removed(self, tmp_path: Path) -> None:
        """Test when an unauthorized RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.status_led_rgb = (1.0, 0.5, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Unauthorized"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0

    async def test_rfid_unknown_inserted(self, tmp_path: Path) -> None:
        """Test when an unknown RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0123456789",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": "Unknown RFID",
            "oops_led": False,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == "Unknown RFID"
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0123456789"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_rfid_unknown_inserted_slack(self, tmp_path: Path) -> None:
        """Test when an unknown RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0123456789",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": "Unknown RFID",
            "oops_led": False,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == "Unknown RFID"
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0123456789"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert slack.mock_calls == [
            call.admin_log("RFID login attempt on Metal Mill by unknown fob")
        ]

    async def test_rfid_unknown_removed(self, tmp_path: Path) -> None:
        """Test when an unknown RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0123456789"
        m.state.current_user = None
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Unknown RFID"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0

    async def test_rfid_unknown_removed_slack(self, tmp_path: Path) -> None:
        """Test when an unknown RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0123456789"
        m.state.current_user = None
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Unknown RFID"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0
        assert slack.mock_calls == [
            call.admin_log(
                "RFID logout on hammer by unknown; session " "duration 48 seconds"
            )
        ]


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestRfidUnauthorizedWarnOnly:
    """Tests for RFID value changed on unauthorized_warn_only machine."""

    async def test_rfid_authorized_inserted(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "permissive-lathe"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "8114346998",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": True,
            "display": "Welcome,\nPAshley",
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == "Welcome,\nPAshley"
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "8114346998"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user == app.config["USERS"].users_by_fob["8114346998"]
        assert ms.relay_desired_state is True
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 1.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_rfid_authorized_removed(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "permissive-lathe"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = True
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "8114346998"
        m.state.current_user = app.config["USERS"].users_by_fob["8114346998"]
        m.state.status_led_rgb = (0.0, 1.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Welcome,\nPAshley"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0

    async def test_rfid_unauthorized_inserted_zeropad(self, tmp_path: Path) -> None:
        """Test when an unauth RFID card is inserted but < 10 characters."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "permissive-lathe"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": True,
            "display": "Welcome,\nPKenneth",
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == "Welcome,\nPKenneth"
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user == app.config["USERS"].users_by_fob["0091703745"]
        assert ms.relay_desired_state is True
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 1.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_rfid_unauthorized_inserted_zeropad_slack(
        self, tmp_path: Path
    ) -> None:
        """Test when an unauth RFID card is inserted but < 10 characters."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "permissive-lathe"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": True,
            "display": "Welcome,\nPKenneth",
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == "Welcome,\nPKenneth"
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user == app.config["USERS"].users_by_fob["0091703745"]
        assert ms.relay_desired_state is True
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 1.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert slack.mock_calls == [
            call.admin_log(
                "WARNING - Authorizing user Kenneth Hunter for "
                "permissive-lathe based on unauthorized_warn_only setting "
                "for machine. User is NOT authorized for this machine."
            ),
            call.admin_log(
                "RFID login on permissive-lathe by authorized user " "Kenneth Hunter"
            ),
        ]

    async def test_rfid_unauthorized_removed(self, tmp_path: Path) -> None:
        """Test when an unauthorized RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "permissive-lathe"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = True
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.status_led_rgb = (0.0, 1.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Welcome,\nPKenneth"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0

    async def test_rfid_unknown_inserted(self, tmp_path: Path) -> None:
        """Test when an unknown RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "permissive-lathe"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0123456789",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": "Unknown RFID",
            "oops_led": False,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == "Unknown RFID"
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0123456789"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_rfid_unknown_removed(self, tmp_path: Path) -> None:
        """Test when an unknown RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "permissive-lathe"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0123456789"
        m.state.current_user = None
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.display_text = "Unknown RFID"
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestRfidChangedWhenOopsed:
    """Tests for RFID value changed when oopsed."""

    async def test_rfid_authorized_inserted(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.is_oopsed = True
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "8114346998",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is True
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is False
        assert ms.rfid_value == "8114346998"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_authorized_inserted_slack(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.is_oopsed = True
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "8114346998",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is True
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is False
        assert ms.rfid_value == "8114346998"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert slack.mock_calls == [
            call.admin_log(
                "RFID login attempt on Metal Mill by Ashley Williams " "when oopsed."
            )
        ]

    async def test_rfid_authorized_inserted_zeropad(self, tmp_path: Path) -> None:
        """Test when an auth RFID card is inserted but < 10 characters."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.is_oopsed = True
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is True
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_authorized_removed(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.is_oopsed = True
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is True
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_unauthorized_inserted_zeropad(self, tmp_path: Path) -> None:
        """Test when an unauth RFID card is inserted but < 10 characters."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.is_oopsed = True
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is True
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_unauthorized_removed(self, tmp_path: Path) -> None:
        """Test when an unauthorized RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.is_oopsed = True
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is True
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_unknown_inserted(self, tmp_path: Path) -> None:
        """Test when an unknown RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.is_oopsed = True
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0123456789",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is True
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0123456789"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_unknown_inserted_slack(self, tmp_path: Path) -> None:
        """Test when an unknown RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.is_oopsed = True
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0123456789",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is True
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is False
        assert ms.rfid_value == "0123456789"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert slack.mock_calls == [
            call.admin_log(
                "RFID login attempt on Metal Mill by unknown fob when oopsed "
                "or locked out."
            )
        ]

    async def test_rfid_unknown_removed(self, tmp_path: Path) -> None:
        """Test when an unknown RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0123456789"
        m.state.current_user = None
        m.state.is_oopsed = True
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is True
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is False
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestRfidChangedWhenLockedOut:
    """Tests for RFID value changed when locked out."""

    async def test_rfid_authorized_inserted(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.is_locked_out = True
        m.state.display_text = MachineState.LOCKOUT_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "8114346998",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.LOCKOUT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is False
        assert ms.display_text == MachineState.LOCKOUT_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is True
        assert ms.rfid_value == "8114346998"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_authorized_inserted_slack(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.is_locked_out = True
        m.state.display_text = MachineState.LOCKOUT_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "8114346998",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.LOCKOUT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is False
        assert ms.display_text == MachineState.LOCKOUT_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is True
        assert ms.rfid_value == "8114346998"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0
        assert slack.mock_calls == [
            call.admin_log(
                "RFID login attempt on Metal Mill by Ashley Williams "
                "when machine locked-out."
            )
        ]

    async def test_rfid_authorized_inserted_zeropad(self, tmp_path: Path) -> None:
        """Test when an auth RFID card is inserted but < 10 characters."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.is_locked_out = True
        m.state.display_text = MachineState.LOCKOUT_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.LOCKOUT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is False
        assert ms.display_text == MachineState.LOCKOUT_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is True
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_authorized_removed(self, tmp_path: Path) -> None:
        """Test when an authorized RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.is_locked_out = True
        m.state.display_text = MachineState.LOCKOUT_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.LOCKOUT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is False
        assert ms.display_text == MachineState.LOCKOUT_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is True
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_unauthorized_inserted_zeropad(self, tmp_path: Path) -> None:
        """Test when an unauth RFID card is inserted but < 10 characters."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.is_locked_out = True
        m.state.display_text = MachineState.LOCKOUT_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "91703745",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.LOCKOUT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is False
        assert ms.display_text == MachineState.LOCKOUT_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is True
        assert ms.rfid_value == "0091703745"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_unauthorized_removed(self, tmp_path: Path) -> None:
        """Test when an unauthorized RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0091703745"
        m.state.current_user = app.config["USERS"].users_by_fob["0091703745"]
        m.state.is_locked_out = True
        m.state.display_text = MachineState.LOCKOUT_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.LOCKOUT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is False
        assert ms.display_text == MachineState.LOCKOUT_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is True
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_unknown_inserted(self, tmp_path: Path) -> None:
        """Test when an unknown RFID card is inserted."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.is_locked_out = True
        m.state.display_text = MachineState.LOCKOUT_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0123456789",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.LOCKOUT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is False
        assert ms.display_text == MachineState.LOCKOUT_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is True
        assert ms.rfid_value == "0123456789"
        assert ms.rfid_present_since == 1689477248.0
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0

    async def test_rfid_unknown_removed(self, tmp_path: Path) -> None:
        """Test when an unknown RFID card is removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "hammer"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.uptime = 10.3
        m.state.last_update = 1689477200.0
        m.state.last_checkin = 1689477200.0
        m.state.relay_desired_state = False
        m.state.rfid_present_since = 1689477200.0
        m.state.rfid_value = "0123456789"
        m.state.current_user = None
        m.state.is_locked_out = True
        m.state.display_text = MachineState.LOCKOUT_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        # send request
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.LOCKOUT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_oopsed is False
        assert ms.display_text == MachineState.LOCKOUT_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.current_amps == 0
        assert ms.uptime == 13.6
        assert ms.wifi_signal_db == -54
        assert ms.wifi_signal_percent == 92
        assert ms.internal_temperature_c == 53.89
        assert ms.last_checkin == 1689477248.0
        assert ms.is_locked_out is True
        assert ms.rfid_value is None
        assert ms.rfid_present_since is None
        assert ms.current_user is None
        assert ms.relay_desired_state is False
        assert ms.last_update == 1689477248.0


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestOopsApi:
    """Tests for oops API."""

    async def test_oops_post(self, tmp_path: Path) -> None:
        """Test oops POST."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        assert m.state.is_oopsed is False
        # send request
        response: Response = await client.post(
            "/api/machine/oops/metal-mill",
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {"success": True}
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        assert ms.is_oopsed is True
        assert ms.relay_desired_state is False
        assert ms.current_user is None
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_oops_delete(self, tmp_path: Path) -> None:
        """Test oops POST."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.is_oopsed = True
        m.state._save_cache()
        # send request
        response: Response = await client.delete(
            "/api/machine/oops/metal-mill",
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {"success": True}
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        assert ms.is_oopsed is False
        assert ms.relay_desired_state is False
        assert ms.current_user is None
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0

    async def test_oops_post_no_machine(self, tmp_path: Path) -> None:
        """Test oops POST with invalid machine name."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # send request
        response: Response = await client.post(
            "/api/machine/oops/invalid-machine-name",
        )
        # check response
        assert response.status_code == 404
        assert await response.json == {"error": "No such machine: invalid-machine-name"}

    async def test_oops_exception(self, tmp_path: Path) -> None:
        """Test oops POST."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        assert m.state.is_oopsed is False
        m.oops = RuntimeError()
        # send request
        response: Response = await client.post(
            "/api/machine/oops/metal-mill",
        )
        # check response
        assert response.status_code == 500

    async def test_oops_state_save_timeout(self, tmp_path: Path) -> None:
        """Test oops POST returns 503 on state-save timeout.

        Body must include ``action_applied: true`` so the API caller
        knows the in-memory state mutation took effect even though
        persistence to disk timed out.
        """
        from dm_mac.models.machine import StateSaveTimeoutError

        app, client = app_and_client(tmp_path)
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]

        async def boom() -> None:
            raise StateSaveTimeoutError("simulated")

        with patch.object(m.state, "save_cache", side_effect=boom):
            response: Response = await client.post(
                "/api/machine/oops/metal-mill",
            )
        assert response.status_code == 503
        assert await response.json == {
            "error": "state save timeout",
            "action_applied": True,
        }


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestLockApi:
    """Tests for lockout API."""

    async def test_lockout_post(self, tmp_path: Path) -> None:
        """Test lockout POST."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        assert m.state.is_oopsed is False
        # send request
        response: Response = await client.post(
            "/api/machine/locked_out/metal-mill",
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {"success": True}
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        assert ms.is_locked_out is True
        assert ms.relay_desired_state is False
        assert ms.current_user is None
        assert ms.display_text == MachineState.LOCKOUT_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.5, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS

    async def test_lockout_delete(self, tmp_path: Path) -> None:
        """Test locked_out POST."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.is_oopsed = True
        m.state._save_cache()
        # send request
        response: Response = await client.delete(
            "/api/machine/locked_out/metal-mill",
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {"success": True}
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        assert ms.is_locked_out is False
        assert ms.relay_desired_state is False
        assert ms.current_user is None
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0

    async def test_lockout_post_no_machine(self, tmp_path: Path) -> None:
        """Test lockout POST with invalid machine name."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # send request
        response: Response = await client.post(
            "/api/machine/locked_out/invalid-machine-name",
        )
        # check response
        assert response.status_code == 404
        assert await response.json == {"error": "No such machine: invalid-machine-name"}

    async def test_lockout_post_exception(self, tmp_path: Path) -> None:
        """Test lockout POST that raises an exception."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        # set up state
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        assert m.state.is_oopsed is False
        m.lockout = RuntimeError()
        # send request
        response: Response = await client.post(
            "/api/machine/locked_out/metal-mill",
        )
        # check response
        assert response.status_code == 500

    async def test_lockout_state_save_timeout(self, tmp_path: Path) -> None:
        """Test locked_out POST returns 503 on state-save timeout.

        Body must include ``action_applied: true`` so the API caller
        knows the in-memory lock/unlock mutation took effect even
        though persistence to disk timed out.
        """
        from dm_mac.models.machine import StateSaveTimeoutError

        app, client = app_and_client(tmp_path)
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]

        async def boom() -> None:
            raise StateSaveTimeoutError("simulated")

        with patch.object(m.state, "save_cache", side_effect=boom):
            response: Response = await client.post(
                "/api/machine/locked_out/metal-mill",
            )
        assert response.status_code == 503
        assert await response.json == {
            "error": "state save timeout",
            "action_applied": True,
        }


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestOverrideLogin:
    """Tests for oops/lockout override login feature (T013-T017)."""

    async def test_override_login_oopsed(self, tmp_path: Path) -> None:
        """T013: Override login on an oopsed machine by user with oops_override."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state - oops the machine first
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        # Oops the machine via update
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": True,
                "rfid_value": "",
                "uptime": 12.3,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        assert (await response.json)["oops_led"] is True
        # reset slack mock to only track override login calls
        slack.reset_mock()
        # Now insert Jason's RFID (oops_override user)
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0014916441",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": True,
            "display": "OVERRIDE BY\njantman",
            "oops_led": True,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_override_login is True
        assert ms.is_oopsed is True
        assert ms.is_locked_out is False
        assert ms.relay_desired_state is True
        assert ms.display_text == "OVERRIDE BY\njantman"
        assert ms.status_led_rgb == (0.0, 1.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.rfid_value == "0014916441"
        assert ms.current_user is not None
        assert ms.current_user.account_id == "4"
        # verify Slack
        assert slack.log_override_login.mock_calls == [call(m, "Jason Antman")]

    async def test_override_login_locked_out(self, tmp_path: Path) -> None:
        """T014: Override login on a locked-out machine by user with oops_override."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state - lock out the machine
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.lockout()
        m.state._save_cache()
        # reset slack mock
        slack.reset_mock()
        # Now insert Jason's RFID (oops_override user)
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0014916441",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response
        assert response.status_code == 200
        assert await response.json == {
            "relay": True,
            "display": "OVERRIDE BY\njantman",
            "oops_led": False,
            "status_led_rgb": [0.0, 1.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state
        assert ms.is_override_login is True
        assert ms.is_locked_out is True
        assert ms.is_oopsed is False
        assert ms.relay_desired_state is True
        assert ms.display_text == "OVERRIDE BY\njantman"
        assert ms.status_led_rgb == (0.0, 1.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.rfid_value == "0014916441"
        assert ms.current_user is not None
        assert ms.current_user.account_id == "4"
        # verify Slack
        assert slack.log_override_login.mock_calls == [call(m, "Jason Antman")]

    async def test_override_login_then_remove(self, tmp_path: Path) -> None:
        """T015: Override login on oopsed machine, then card removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state - oops the machine
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.is_oopsed = True
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.uptime = 10.3
        m.state._save_cache()
        # Insert Jason's RFID (override login)
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0014916441",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        assert (await response.json)["relay"] is True
        assert (await response.json)["display"] == "OVERRIDE BY\njantman"
        # reset slack mock
        slack.reset_mock()
        # Now remove the card
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 14.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response - should return to oopsed state
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state - back to oopsed
        assert ms.is_override_login is False
        assert ms.is_oopsed is True
        assert ms.is_locked_out is False
        assert ms.relay_desired_state is False
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.rfid_value is None
        assert ms.current_user is None

    async def test_admin_clear_during_override(self, tmp_path: Path) -> None:
        """T016: Admin clears oops during override login, then card removed."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state - oops the machine
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.is_oopsed = True
        m.state.display_text = MachineState.OOPS_DISPLAY_TEXT
        m.state.status_led_rgb = (1.0, 0.0, 0.0)
        m.state.status_led_brightness = MachineState.STATUS_LED_BRIGHTNESS
        m.state.uptime = 10.3
        m.state._save_cache()
        # Insert Jason's RFID (override login)
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0014916441",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        assert (await response.json)["relay"] is True
        # Admin clears oops via DELETE
        response = await client.delete(
            "/api/machine/oops/metal-mill",
        )
        assert response.status_code == 200
        assert await response.json == {"success": True}
        # reset slack mock
        slack.reset_mock()
        # Now remove the card
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 15.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response - should return to normal idle state (not oopsed)
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.DEFAULT_DISPLAY_TEXT,
            "oops_led": False,
            "status_led_rgb": [0.0, 0.0, 0.0],
            "status_led_brightness": 0.0,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state - back to normal idle
        assert ms.is_override_login is False
        assert ms.is_oopsed is False
        assert ms.is_locked_out is False
        assert ms.relay_desired_state is False
        assert ms.display_text == MachineState.DEFAULT_DISPLAY_TEXT
        assert ms.status_led_rgb == (0.0, 0.0, 0.0)
        assert ms.status_led_brightness == 0.0
        assert ms.rfid_value is None
        assert ms.current_user is None

    async def test_admin_oops_during_override(self, tmp_path: Path) -> None:
        """T017: Admin oopses machine during override login on locked-out machine."""
        # boilerplate for test
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        slack = AsyncMock(spec_set=SlackHandler)
        app.config.update({"SLACK_HANDLER": slack})
        # set up state - lock out the machine
        mname: str = "metal-mill"
        m: Machine = app.config["MACHINES"].machines_by_name[mname]
        m.state.lockout()
        m.state._save_cache()
        # Insert Jason's RFID (override login)
        response: Response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0014916441",
                "uptime": 13.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        assert (await response.json)["relay"] is True
        # Admin oopses the machine via POST
        response = await client.post(
            "/api/machine/oops/metal-mill",
        )
        assert response.status_code == 200
        assert await response.json == {"success": True}
        # Verify relay is now off (oops takes effect immediately)
        # Next MCU update with card still present should show oopsed state
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "0014916441",
                "uptime": 14.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        assert response.status_code == 200
        resp_json = await response.json
        assert resp_json["relay"] is False
        assert resp_json["oops_led"] is True
        # reset slack mock
        slack.reset_mock()
        # Now remove the card
        response = await client.post(
            "/api/machine/update",
            json={
                "machine_name": mname,
                "oops": False,
                "rfid_value": "",
                "uptime": 15.6,
                "wifi_signal_db": -54,
                "wifi_signal_percent": 92,
                "internal_temperature_c": 53.89,
            },
        )
        # check response - should stay in oopsed state
        assert response.status_code == 200
        assert await response.json == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }
        # boilerplate to read state from disk
        with patch.dict("os.environ", {"MACHINE_STATE_DIR": m.state._state_dir}):
            ms: MachineState = MachineState(m)
        # verify state - oopsed
        assert ms.is_oopsed is True
        assert ms.is_locked_out is True
        assert ms.is_override_login is False
        assert ms.relay_desired_state is False
        assert ms.display_text == MachineState.OOPS_DISPLAY_TEXT
        assert ms.status_led_rgb == (1.0, 0.0, 0.0)
        assert ms.status_led_brightness == MachineState.STATUS_LED_BRIGHTNESS
        assert ms.rfid_value is None
        assert ms.current_user is None
