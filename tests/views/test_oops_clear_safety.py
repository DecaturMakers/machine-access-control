"""Safety regression tests: clearing an Oops must never energize a machine.

See issue #201. After an Oops is cleared, the relay may only close on a fresh
authorized RFID insert. A card left in the reader across the Oops, the clear,
a server restart or an MCU reboot must not re-energize the machine.
"""

from pathlib import Path
from typing import Any
from typing import Dict

from freezegun import freeze_time
from quart import Quart
from quart.typing import TestClientProtocol

from dm_mac.models.machine import MachineState

from .quart_test_helpers import app_and_client

#: Strict machine (no warn-only, not always-enabled).
MNAME: str = "metal-mill"
#: Fob of a user authorized for metal-mill; no oops_override.
FOB: str = "8114346998"


async def mcu_update(
    client: TestClientProtocol,
    mname: str = MNAME,
    rfid_value: str = FOB,
    uptime: float = 100.0,
    oops: bool = False,
) -> Dict[str, Any]:
    """POST an MCU update and return the JSON response."""
    response = await client.post(
        "/api/machine/update",
        json={
            "machine_name": mname,
            "oops": oops,
            "rfid_value": rfid_value,
            "uptime": uptime,
            "wifi_signal_db": -54,
            "wifi_signal_percent": 92,
            "internal_temperature_c": 53.89,
        },
    )
    assert response.status_code == 200
    result: Dict[str, Any] = await response.json
    return result


async def oops_and_clear(
    client: TestClientProtocol,
    mname: str = MNAME,
    uptime: float = 101.0,
    rfid_value: str = FOB,
) -> None:
    """Oops via the MCU button with the card present, then clear it via API."""
    resp = await mcu_update(
        client, mname=mname, rfid_value=rfid_value, uptime=uptime, oops=True
    )
    assert resp["relay"] is False
    assert resp["display"] == MachineState.OOPS_DISPLAY_TEXT
    response = await client.delete(f"/api/machine/oops/{mname}")
    assert response.status_code == 200


async def login(client: TestClientProtocol) -> None:
    """Establish a baseline with no card, then log in (relay on)."""
    resp = await mcu_update(client, rfid_value="", uptime=99.0)
    assert resp["relay"] is False
    resp = await mcu_update(client, uptime=100.0)
    assert resp["relay"] is True


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestOopsClearWithCardPresent:
    """Card stays in the reader through Oops and clear."""

    async def test_same_card_after_clear(self, tmp_path: Path) -> None:
        """Relay stays off on heartbeats after clear; fresh insert turns it on."""
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        await login(client)
        await oops_and_clear(client)
        for uptime in (102.0, 103.0, 104.0):
            resp = await mcu_update(client, uptime=uptime)
            assert resp["relay"] is False
            assert resp["display"] == MachineState.DEFAULT_DISPLAY_TEXT
        state = app.config["MACHINES"].machines_by_name[MNAME].state
        assert state.relay_desired_state is False
        assert state.current_user is None
        # positive control: remove and re-insert the card -> login
        resp = await mcu_update(client, rfid_value="", uptime=105.0)
        assert resp["relay"] is False
        resp = await mcu_update(client, uptime=106.0)
        assert resp["relay"] is True

    async def test_same_card_after_clear_and_server_restart(
        self, tmp_path: Path
    ) -> None:
        """Relay stays off after clear across a server restart (cache reload)."""
        client: TestClientProtocol
        _, client = app_and_client(tmp_path)
        await login(client)
        await oops_and_clear(client)
        # new app instance loads state from the same on-disk cache
        app2: Quart
        client2: TestClientProtocol
        app2, client2 = app_and_client(tmp_path)
        state = app2.config["MACHINES"].machines_by_name[MNAME].state
        assert state.is_oopsed is False
        assert state.relay_desired_state is False
        for uptime in (102.0, 103.0):
            resp = await mcu_update(client2, uptime=uptime)
            assert resp["relay"] is False

    async def test_server_restart_while_oopsed_then_clear(self, tmp_path: Path) -> None:
        """Restart while Oopsed, clear on the new instance, card still present."""
        client: TestClientProtocol
        _, client = app_and_client(tmp_path)
        await login(client)
        resp = await mcu_update(client, uptime=101.0, oops=True)
        assert resp["relay"] is False
        client2: TestClientProtocol
        _, client2 = app_and_client(tmp_path)
        resp = await mcu_update(client2, uptime=102.0)
        assert resp["relay"] is False
        assert resp["display"] == MachineState.OOPS_DISPLAY_TEXT
        response = await client2.delete(f"/api/machine/oops/{MNAME}")
        assert response.status_code == 200
        resp = await mcu_update(client2, uptime=103.0)
        assert resp["relay"] is False

    async def test_same_card_after_clear_and_mcu_reboot(self, tmp_path: Path) -> None:
        """Relay stays off when the MCU reboots after clear with card present."""
        client: TestClientProtocol
        _, client = app_and_client(tmp_path)
        await login(client)
        await oops_and_clear(client)
        # lower uptime = MCU reboot
        resp = await mcu_update(client, uptime=2.0)
        assert resp["relay"] is False
        resp = await mcu_update(client, uptime=7.0)
        assert resp["relay"] is False

    async def test_mcu_reboot_while_oopsed_then_clear(self, tmp_path: Path) -> None:
        """MCU reboots while Oopsed with card present; clear; relay stays off."""
        client: TestClientProtocol
        _, client = app_and_client(tmp_path)
        await login(client)
        resp = await mcu_update(client, uptime=101.0, oops=True)
        assert resp["relay"] is False
        resp = await mcu_update(client, uptime=2.0)
        assert resp["relay"] is False
        response = await client.delete(f"/api/machine/oops/{MNAME}")
        assert response.status_code == 200
        resp = await mcu_update(client, uptime=7.0)
        assert resp["relay"] is False


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestRebootKeepsOopsAndLockout:
    """An MCU reboot must not drop the Oops / lock-out display or state."""

    @staticmethod
    async def _reboot(
        client: TestClientProtocol, mname: str, rfid_value: str = ""
    ) -> Dict[str, Any]:
        await mcu_update(client, mname=mname, rfid_value=rfid_value, uptime=100.0)
        return await mcu_update(client, mname=mname, rfid_value=rfid_value, uptime=1.0)

    async def test_reboot_while_oopsed(self, tmp_path: Path) -> None:
        """Reboot of an Oopsed machine keeps the Oops display."""
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        app.config["MACHINES"].machines_by_name[MNAME].state.oops()
        resp = await self._reboot(client, MNAME)
        assert resp == {
            "relay": False,
            "display": MachineState.OOPS_DISPLAY_TEXT,
            "oops_led": True,
            "status_led_rgb": [1.0, 0.0, 0.0],
            "status_led_brightness": MachineState.STATUS_LED_BRIGHTNESS,
            "second_relay": False,
        }

    async def test_reboot_while_locked_out(self, tmp_path: Path) -> None:
        """Reboot of a locked-out machine keeps the lock-out display."""
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        app.config["MACHINES"].machines_by_name[MNAME].state.lockout()
        resp = await self._reboot(client, MNAME)
        assert resp["relay"] is False
        assert resp["display"] == MachineState.LOCKOUT_DISPLAY_TEXT
        assert resp["status_led_rgb"] == [1.0, 0.5, 0.0]

    async def test_always_enabled_reboot_while_oopsed(self, tmp_path: Path) -> None:
        """Always-enabled machine must not energize on reboot while Oopsed."""
        mname: str = "always-on-machine"
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        resp = await mcu_update(client, mname=mname, rfid_value="", uptime=100.0)
        assert resp["relay"] is True
        resp = await mcu_update(
            client, mname=mname, rfid_value="", uptime=101.0, oops=True
        )
        assert resp["relay"] is False
        resp = await mcu_update(client, mname=mname, rfid_value="", uptime=1.0)
        assert resp["relay"] is False
        assert resp["display"] == MachineState.OOPS_DISPLAY_TEXT
        resp = await mcu_update(client, mname=mname, rfid_value="", uptime=6.0)
        assert resp["relay"] is False
        state = app.config["MACHINES"].machines_by_name[mname].state
        assert state.relay_desired_state is False

    async def test_always_enabled_reboot_while_locked_out(self, tmp_path: Path) -> None:
        """Always-enabled machine must not energize on reboot while locked out."""
        mname: str = "always-on-machine"
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        app.config["MACHINES"].machines_by_name[mname].state.lockout()
        resp = await self._reboot(client, mname)
        assert resp["relay"] is False
        assert resp["display"] == MachineState.LOCKOUT_DISPLAY_TEXT
