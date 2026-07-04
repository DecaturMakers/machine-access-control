"""Tests for API Views."""

import os
from pathlib import Path
from shutil import copy
from unittest.mock import patch

from freezegun import freeze_time
from quart import Quart
from quart import Response
from quart.typing import TestClientProtocol

from dm_mac.models.users import UsersConfig

from .quart_test_helpers import app_and_client


class TestIndex:
    """Tests for API Index view."""

    async def test_index_response(self, tmp_path: Path) -> None:
        """Test for API index response."""
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        response: Response = await client.get("/api/")
        assert response.status_code == 200
        assert await response.json == {"message": "Nothing to see here..."}
        assert response.headers["Content-Type"] == "application/json"


class TestMachines:
    """Tests for the GET /api/machines endpoint."""

    async def test_all_machines_listed_sorted(self, tmp_path: Path) -> None:
        """All configured machines are returned, sorted by name."""
        app: Quart
        client: TestClientProtocol
        app, client = app_and_client(tmp_path)
        response: Response = await client.get("/api/machines")
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/json"
        data = await response.json
        names = [m["name"] for m in data["machines"]]
        assert names == sorted(names)
        assert set(names) == set(app.config["MACHINES"].machines_by_name.keys())

    async def test_status_reflects_state(self, tmp_path: Path) -> None:
        """Endpoint reflects live machine state (in_use/oops/locked_out/user)."""
        app, client = app_and_client(tmp_path)
        mconf = app.config["MACHINES"]
        # in_use with a logged-in user
        mm = mconf.machines_by_name["metal-mill"]
        mm.state.relay_desired_state = True
        mm.state.last_checkin = 100.0
        mm.state.current_user = app.config["USERS"].users_by_fob["8114346998"]
        # oopsed
        mconf.machines_by_name["hammer"].state.is_oopsed = True
        # locked out
        mconf.machines_by_name["restrictive-lathe"].state.is_locked_out = True
        response: Response = await client.get("/api/machines")
        by_name = {m["name"]: m for m in (await response.json)["machines"]}
        assert by_name["metal-mill"]["status"] == "in_use"
        assert by_name["metal-mill"]["relay"] is True
        assert by_name["metal-mill"]["current_user"] == {
            "account_id": "1",
            "full_name": "Ashley Williams",
        }
        assert by_name["hammer"]["status"] == "oops"
        assert by_name["hammer"]["oops"] is True
        assert by_name["restrictive-lathe"]["status"] == "locked_out"
        assert by_name["restrictive-lathe"]["locked_out"] is True


@freeze_time("2023-07-16 03:14:08", tz_offset=0)
class TestReloadUsers:
    """Tests for reloading users."""

    async def test_no_change(self, tmp_path: Path, fixtures_path: str) -> None:
        """Test /reload-users with no change."""
        # set things up
        uconf: str = str(os.path.join(tmp_path, "users.json"))
        copy(os.path.join(fixtures_path, "users.json"), uconf)
        with patch.dict("os.environ", {"USERS_CONFIG": uconf}):
            app: Quart
            client: TestClientProtocol
            app, client = app_and_client(tmp_path)
            users: UsersConfig = app.config["USERS"]
            users.load_time = 123456.0
            before = [x.as_dict for x in users.users]
            response: Response = await client.post("/api/reload-users")
        assert response.status_code == 200
        assert await response.json == {
            "updated": 0,
            "removed": 0,
            "added": 0,
        }
        users = app.config["USERS"]
        assert users.load_time == 1689477248.0
        after = [x.as_dict for x in users.users]
        assert before == after
        assert len(users.users_by_fob) == 4
        assert users.users_by_fob["8114346998"].account_id == "1"
        assert users.users_by_fob["8682768676"].account_id == "2"
        assert users.users_by_fob["0091703745"].account_id == "3"
        assert users.users_by_fob["0014916441"].account_id == "4"

    async def test_exception(self, tmp_path: Path, fixtures_path: str) -> None:
        """Test /reload-users when an exception is raised."""
        # set things up
        uconf: str = str(os.path.join(tmp_path, "users.json"))
        copy(os.path.join(fixtures_path, "users.json"), uconf)
        with patch.dict("os.environ", {"USERS_CONFIG": uconf}):
            app: Quart
            client: TestClientProtocol
            app, client = app_and_client(tmp_path)
            users: UsersConfig = app.config["USERS"]
            users.load_time = 123456.0
            before = [x.as_dict for x in users.users]
            with open(uconf, "w") as fh:
                fh.write("\n")
            response: Response = await client.post("/api/reload-users")
        assert response.status_code == 500
        assert await response.json == {
            "error": "Expecting value: line 2 column 1 (char 1)"
        }
        users = app.config["USERS"]
        assert users.load_time == 123456.0
        after = [x.as_dict for x in users.users]
        assert before == after

    async def test_changed(self, tmp_path: Path, fixtures_path: str) -> None:
        """Test /reload-users with changes."""
        # set things up
        uconf: str = str(os.path.join(tmp_path, "users.json"))
        copy(os.path.join(fixtures_path, "users.json"), uconf)
        with patch.dict("os.environ", {"USERS_CONFIG": uconf}):
            app: Quart
            client: TestClientProtocol
            app, client = app_and_client(tmp_path)
            app.config["USERS"].load_time = 123456.0
            copy(os.path.join(fixtures_path, "users-changed.json"), uconf)
            response: Response = await client.post("/api/reload-users")
        assert response.status_code == 200
        assert await response.json == {
            "updated": 2,
            "removed": 1,
            "added": 1,
        }
        users: UsersConfig = app.config["USERS"]
        assert users.load_time == 1689477248.0
        after = [x.as_dict for x in users.users]
        assert after == [
            {
                "account_id": "1",
                "authorizations": [
                    "Woodshop Orientation",
                    "Woodshop 201",
                    "Woodshop 101",
                    "Metal Mill",
                    "Metal Lathe",
                    "Foobar",
                ],
                "email": "munoz@example.net",
                "expiration_ymd": "2024-08-18",
                "first_name": "Ashley",
                "last_name": "Williams",
                "fob_codes": ["8114346998", "0012348901"],
                "full_name": "Ashley Williams",
                "preferred_name": "PAshley",
                "oops_override": False,
            },
            {
                "account_id": "3",
                "authorizations": ["Woodshop 201", "Woodshop 101"],
                "email": "rossdaniel@example.net",
                "expiration_ymd": "2024-08-19",
                "first_name": "Kenneth",
                "last_name": "Hunter",
                "fob_codes": ["0091703745"],
                "full_name": "Kenneth Hunter",
                "preferred_name": "PKenneth",
                "oops_override": False,
            },
            {
                "account_id": "4",
                "authorizations": [
                    "Woodshop Orientation",
                    "Woodshop 201",
                    "Woodshop 101",
                    "Metal Mill",
                    "Metal Lathe",
                ],
                "email": "jason@jasonantman.com",
                "expiration_ymd": "2099-01-01",
                "first_name": "Jason",
                "last_name": "Antman",
                "fob_codes": ["0014916441"],
                "full_name": "Jason Antman",
                "preferred_name": "jantman",
                "oops_override": True,
            },
            {
                "account_id": "19",
                "authorizations": ["Woodshop Orientation", "Metal Mill"],
                "email": "tony37@example.net",
                "expiration_ymd": "2024-08-18",
                "first_name": "James",
                "last_name": "Smith",
                "fob_codes": ["8682768000"],
                "full_name": "James Smith",
                "preferred_name": "PJames",
                "oops_override": False,
            },
        ]
        assert len(users.users_by_fob) == 5
        assert users.users_by_fob["8114346998"].account_id == "1"
        assert users.users_by_fob["0012348901"].account_id == "1"
        assert "8682768676" not in users.users_by_fob
        assert users.users_by_fob["0091703745"].account_id == "3"
        assert users.users_by_fob["0014916441"].account_id == "4"
        assert users.users_by_fob["8682768000"].account_id == "19"
