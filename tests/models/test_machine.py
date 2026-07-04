"""Tests for models.machine."""

import json
import os
import shutil
from pathlib import Path
from typing import Any
from typing import Dict
from unittest.mock import Mock
from unittest.mock import call
from unittest.mock import patch

import pytest
from freezegun import freeze_time
from jsonschema.exceptions import ValidationError

from dm_mac.models.machine import Machine
from dm_mac.models.machine import MachinesConfig

pbm: str = "dm_mac.models.machine"


class TestMachinesConfig:
    """Tests for models.machine.MachinesConfig."""

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    def test_default_config(self, fixtures_path: str, tmp_path: Path) -> None:
        """Test using default config file path."""
        conf_path: str = os.path.join(fixtures_path, "machines.json")
        shutil.copy(conf_path, os.path.join(tmp_path, "machines.json"))
        os.chdir(tmp_path)
        with patch(f"{pbm}.MachineState", autospec=True):
            cls: MachinesConfig = MachinesConfig()
        assert len(cls.machines) == 6
        assert len(cls.machines_by_name) == 6
        assert cls.load_time == 1689477248.0

    @freeze_time("2023-07-16 03:14:08", tz_offset=0)
    def test_config_path(self, fixtures_path: str, tmp_path: Path) -> None:
        """Test using default config file path."""
        conf: Dict[str, Dict[str, Any]] = {
            "metal-mill": {"authorizations_or": ["Metal Mill"]},
            "hammer": {
                "authorizations_or": [
                    "Woodshop Orientation",
                    "Woodshop 201",
                    "Woodshop 101",
                ],
                "unauthorized_warn_only": True,
            },
        }
        cpath: str = str(os.path.join(tmp_path, "foobar.json"))
        with open(cpath, "w") as fh:
            json.dump(conf, fh, sort_keys=True, indent=4)
        with patch.dict(os.environ, {"MACHINES_CONFIG": cpath}):
            with patch(f"{pbm}.MachineState", autospec=True):
                cls: MachinesConfig = MachinesConfig()
        assert len(cls.machines) == 2
        assert len(cls.machines_by_name) == 2
        assert isinstance(cls.machines_by_name["hammer"], Machine)
        assert cls.machines_by_name["hammer"].name == "hammer"
        assert (
            cls.machines_by_name["hammer"].authorizations_or
            == conf["hammer"]["authorizations_or"]
        )
        assert cls.machines_by_name["hammer"].unauthorized_warn_only is True
        for x in range(0, len(conf)):
            assert isinstance(cls.machines[x], Machine)
        assert cls.machines_by_name["metal-mill"].as_dict == {
            "name": "metal-mill",
            "authorizations_or": ["Metal Mill"],
            "unauthorized_warn_only": False,
            "always_enabled": False,
            "alias": None,
        }
        assert cls.load_time == 1689477248.0

    def test_invalid_config(self, fixtures_path: str, tmp_path: Path) -> None:
        """Test using default config file path."""
        conf: Dict[str, Dict[str, Any]] = {
            "metal-mill": {"authorizations_or": ["Metal Mill"]},
            "hammer": {
                "authorizations_or": [
                    "Woodshop Orientation",
                    "Woodshop 201",
                    "Woodshop 101",
                ],
                "unauthorized_warn_only": True,
            },
            "invalid": {
                "bad_key": 4,
            },
        }
        cpath: str = str(os.path.join(tmp_path, "machines.json"))
        with open(cpath, "w") as fh:
            json.dump(conf, fh, sort_keys=True, indent=4)
        os.chdir(tmp_path)
        with pytest.raises(ValidationError):
            with patch(f"{pbm}.MachineState", autospec=True):
                MachinesConfig()


class TestMachine:
    """Tests for models.machine.Machine."""

    def test_happy_path(self) -> None:
        """Test for happy path."""
        with patch(f"{pbm}.MachineState", autospec=True) as m_state:
            cls: Machine = Machine(
                name="mName",
                authorizations_or=["Foo", "Bar"],
            )
        assert cls.name == "mName"
        assert cls.authorizations_or == ["Foo", "Bar"]
        assert cls.unauthorized_warn_only is False
        assert m_state.mock_calls == [call(cls)]
        assert cls.state == m_state.return_value
        assert cls.as_dict == {
            "name": "mName",
            "authorizations_or": ["Foo", "Bar"],
            "unauthorized_warn_only": False,
            "always_enabled": False,
            "alias": None,
        }

    def test_unauth_warn(self) -> None:
        """Test for happy path."""
        with patch(f"{pbm}.MachineState", autospec=True) as m_state:
            cls: Machine = Machine(
                name="mName",
                authorizations_or=["Foo", "Bar"],
                unauthorized_warn_only=True,
            )
        assert cls.name == "mName"
        assert cls.authorizations_or == ["Foo", "Bar"]
        assert cls.unauthorized_warn_only is True
        assert m_state.mock_calls == [call(cls)]
        assert cls.state == m_state.return_value
        assert cls.as_dict == {
            "name": "mName",
            "authorizations_or": ["Foo", "Bar"],
            "unauthorized_warn_only": True,
            "always_enabled": False,
            "alias": None,
        }

    def test_with_alias(self) -> None:
        """Test machine with alias."""
        with patch(f"{pbm}.MachineState", autospec=True) as m_state:
            cls: Machine = Machine(
                name="mName",
                authorizations_or=["Foo", "Bar"],
                alias="My Machine",
            )
        assert cls.name == "mName"
        assert cls.alias == "My Machine"
        assert cls.display_name == "My Machine"
        assert cls.authorizations_or == ["Foo", "Bar"]
        assert m_state.mock_calls == [call(cls)]
        assert cls.state == m_state.return_value
        assert cls.as_dict == {
            "name": "mName",
            "authorizations_or": ["Foo", "Bar"],
            "unauthorized_warn_only": False,
            "always_enabled": False,
            "alias": "My Machine",
        }

    def test_display_name_without_alias(self) -> None:
        """Test display_name property when no alias is set."""
        with patch(f"{pbm}.MachineState", autospec=True):
            cls: Machine = Machine(
                name="mName",
                authorizations_or=["Foo", "Bar"],
            )
        assert cls.display_name == "mName"

    def test_display_name_with_alias(self) -> None:
        """Test display_name property when alias is set."""
        with patch(f"{pbm}.MachineState", autospec=True):
            cls: Machine = Machine(
                name="mName",
                authorizations_or=["Foo", "Bar"],
                alias="My Machine",
            )
        assert cls.display_name == "My Machine"


class TestMachineStatus:
    """Tests for Machine.status and Machine.status_dict."""

    def _machine(self, **state_attrs: Any) -> Machine:
        """Build a Machine with a mocked state and the given state attributes."""
        with patch(f"{pbm}.MachineState", autospec=True):
            mach: Machine = Machine(
                name="mName",
                authorizations_or=["Foo"],
                alias="My Machine",
            )
        # Sensible defaults; overridden by state_attrs.
        defaults: Dict[str, Any] = {
            "is_locked_out": False,
            "is_oopsed": False,
            "relay_desired_state": False,
            "last_checkin": 123.0,
            "last_update": 456.0,
            "current_user": None,
        }
        defaults.update(state_attrs)
        for k, v in defaults.items():
            setattr(mach.state, k, v)
        return mach

    def test_status_locked_out(self) -> None:
        """locked_out takes precedence over everything else."""
        mach = self._machine(
            is_locked_out=True, is_oopsed=True, relay_desired_state=True
        )
        assert mach.status == "locked_out"

    def test_status_oops(self) -> None:
        """oops takes precedence over in_use/idle."""
        mach = self._machine(is_oopsed=True, relay_desired_state=True)
        assert mach.status == "oops"

    def test_status_in_use(self) -> None:
        """relay energized with no oops/lockout is in_use."""
        mach = self._machine(relay_desired_state=True)
        assert mach.status == "in_use"

    def test_status_idle(self) -> None:
        """checked-in machine with relay off is idle."""
        mach = self._machine(relay_desired_state=False, last_checkin=123.0)
        assert mach.status == "idle"

    def test_status_unknown(self) -> None:
        """never-checked-in machine is unknown."""
        mach = self._machine(relay_desired_state=False, last_checkin=None)
        assert mach.status == "unknown"

    def test_status_dict_no_user(self) -> None:
        """status_dict with no logged-in user."""
        mach = self._machine(
            relay_desired_state=False,
            last_checkin=123.0,
            last_update=456.0,
            current_user=None,
        )
        assert mach.status_dict == {
            "name": "mName",
            "display_name": "My Machine",
            "status": "idle",
            "relay": False,
            "oops": False,
            "locked_out": False,
            "current_user": None,
            "last_checkin": 123.0,
            "last_update": 456.0,
        }

    def test_status_dict_with_user(self) -> None:
        """status_dict serializes the logged-in user."""
        user = Mock(account_id="42", full_name="Jane Doe")
        mach = self._machine(
            relay_desired_state=True,
            last_checkin=123.0,
            last_update=456.0,
            current_user=user,
        )
        assert mach.status_dict == {
            "name": "mName",
            "display_name": "My Machine",
            "status": "in_use",
            "relay": True,
            "oops": False,
            "locked_out": False,
            "current_user": {"account_id": "42", "full_name": "Jane Doe"},
            "last_checkin": 123.0,
            "last_update": 456.0,
        }


class TestMachinesConfigGetMachine:
    """Tests for MachinesConfig.get_machine method."""

    def test_get_machine_by_name(self, fixtures_path: str, tmp_path: Path) -> None:
        """Test getting a machine by name."""
        conf: Dict[str, Dict[str, Any]] = {
            "metal-mill": {"authorizations_or": ["Metal Mill"], "alias": "Metal Mill"},
            "hammer": {"authorizations_or": ["Woodshop Orientation"]},
        }
        cpath: str = str(os.path.join(tmp_path, "machines.json"))
        with open(cpath, "w") as fh:
            json.dump(conf, fh, sort_keys=True, indent=4)
        with patch.dict(os.environ, {"MACHINES_CONFIG": cpath}):
            with patch(f"{pbm}.MachineState", autospec=True):
                cls: MachinesConfig = MachinesConfig()
        machine = cls.get_machine("metal-mill")
        assert machine is not None
        assert machine.name == "metal-mill"
        assert machine.alias == "Metal Mill"

    def test_get_machine_by_alias(self, fixtures_path: str, tmp_path: Path) -> None:
        """Test getting a machine by alias."""
        conf: Dict[str, Dict[str, Any]] = {
            "metal-mill": {"authorizations_or": ["Metal Mill"], "alias": "Metal Mill"},
            "hammer": {"authorizations_or": ["Woodshop Orientation"]},
        }
        cpath: str = str(os.path.join(tmp_path, "machines.json"))
        with open(cpath, "w") as fh:
            json.dump(conf, fh, sort_keys=True, indent=4)
        with patch.dict(os.environ, {"MACHINES_CONFIG": cpath}):
            with patch(f"{pbm}.MachineState", autospec=True):
                cls: MachinesConfig = MachinesConfig()
        machine = cls.get_machine("Metal Mill")
        assert machine is not None
        assert machine.name == "metal-mill"
        assert machine.alias == "Metal Mill"

    def test_get_machine_not_found(self, fixtures_path: str, tmp_path: Path) -> None:
        """Test getting a machine that doesn't exist."""
        conf: Dict[str, Dict[str, Any]] = {
            "metal-mill": {"authorizations_or": ["Metal Mill"], "alias": "Metal Mill"},
        }
        cpath: str = str(os.path.join(tmp_path, "machines.json"))
        with open(cpath, "w") as fh:
            json.dump(conf, fh, sort_keys=True, indent=4)
        with patch.dict(os.environ, {"MACHINES_CONFIG": cpath}):
            with patch(f"{pbm}.MachineState", autospec=True):
                cls: MachinesConfig = MachinesConfig()
        machine = cls.get_machine("nonexistent")
        assert machine is None

    def test_get_machine_case_insensitive_name(
        self, fixtures_path: str, tmp_path: Path
    ) -> None:
        """Test getting a machine by name regardless of case."""
        conf: Dict[str, Dict[str, Any]] = {
            "metal-mill": {"authorizations_or": ["Metal Mill"], "alias": "Metal Mill"},
            "hammer": {"authorizations_or": ["Woodshop Orientation"]},
        }
        cpath: str = str(os.path.join(tmp_path, "machines.json"))
        with open(cpath, "w") as fh:
            json.dump(conf, fh, sort_keys=True, indent=4)
        with patch.dict(os.environ, {"MACHINES_CONFIG": cpath}):
            with patch(f"{pbm}.MachineState", autospec=True):
                cls: MachinesConfig = MachinesConfig()
        for variant in ["metal-mill", "Metal-Mill", "METAL-MILL", "MeTaL-mIlL"]:
            machine = cls.get_machine(variant)
            assert machine is not None, variant
            assert machine.name == "metal-mill"

    def test_get_machine_case_insensitive_alias(
        self, fixtures_path: str, tmp_path: Path
    ) -> None:
        """Test getting a machine by alias regardless of case."""
        conf: Dict[str, Dict[str, Any]] = {
            "metal-mill": {"authorizations_or": ["Metal Mill"], "alias": "Metal Mill"},
            "hammer": {"authorizations_or": ["Woodshop Orientation"]},
        }
        cpath: str = str(os.path.join(tmp_path, "machines.json"))
        with open(cpath, "w") as fh:
            json.dump(conf, fh, sort_keys=True, indent=4)
        with patch.dict(os.environ, {"MACHINES_CONFIG": cpath}):
            with patch(f"{pbm}.MachineState", autospec=True):
                cls: MachinesConfig = MachinesConfig()
        for variant in ["Metal Mill", "metal mill", "METAL MILL", "mEtAl MiLl"]:
            machine = cls.get_machine(variant)
            assert machine is not None, variant
            assert machine.name == "metal-mill"
            assert machine.alias == "Metal Mill"

    def test_aliases_colliding_case_insensitively_raise(
        self, fixtures_path: str, tmp_path: Path
    ) -> None:
        """Two aliases differing only by case must be rejected at load."""
        conf: Dict[str, Dict[str, Any]] = {
            "metal-mill": {"authorizations_or": ["a"], "alias": "Big Machine"},
            "hammer": {"authorizations_or": ["b"], "alias": "big machine"},
        }
        cpath: str = str(os.path.join(tmp_path, "machines.json"))
        with open(cpath, "w") as fh:
            json.dump(conf, fh, sort_keys=True, indent=4)
        with patch.dict(os.environ, {"MACHINES_CONFIG": cpath}):
            with patch(f"{pbm}.MachineState", autospec=True):
                with pytest.raises(ValueError, match="collides case-insensitively"):
                    MachinesConfig()

    def test_alias_colliding_with_other_machine_name_raises(
        self, fixtures_path: str, tmp_path: Path
    ) -> None:
        """An alias that matches another machine's name (case-insensitively) raises."""
        conf: Dict[str, Dict[str, Any]] = {
            "metal-mill": {"authorizations_or": ["a"]},
            "hammer": {"authorizations_or": ["b"], "alias": "Metal-Mill"},
        }
        cpath: str = str(os.path.join(tmp_path, "machines.json"))
        with open(cpath, "w") as fh:
            json.dump(conf, fh, sort_keys=True, indent=4)
        with patch.dict(os.environ, {"MACHINES_CONFIG": cpath}):
            with patch(f"{pbm}.MachineState", autospec=True):
                with pytest.raises(ValueError, match="collides case-insensitively"):
                    MachinesConfig()

    def test_alias_equal_to_own_name_is_allowed(
        self, fixtures_path: str, tmp_path: Path
    ) -> None:
        """An alias equal to the machine's own name is harmless, not a collision."""
        conf: Dict[str, Dict[str, Any]] = {
            "hammer": {"authorizations_or": ["b"], "alias": "Hammer"},
        }
        cpath: str = str(os.path.join(tmp_path, "machines.json"))
        with open(cpath, "w") as fh:
            json.dump(conf, fh, sort_keys=True, indent=4)
        with patch.dict(os.environ, {"MACHINES_CONFIG": cpath}):
            with patch(f"{pbm}.MachineState", autospec=True):
                cls: MachinesConfig = MachinesConfig()
        machine = cls.get_machine("HAMMER")
        assert machine is not None
        assert machine.name == "hammer"
