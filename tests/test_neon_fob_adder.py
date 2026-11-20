"""Tests for dm_mac.neon_fob_adder module."""

import os
from base64 import b64encode
from pathlib import Path
from typing import List
from typing import Tuple
from unittest.mock import Mock
from unittest.mock import call
from unittest.mock import patch

import pytest
import responses
from responses.registries import OrderedRegistry

from dm_mac.neon_fob_adder import NeonFobUpdater
from dm_mac.neon_fob_adder import main
from dm_mac.neon_fob_adder import parse_args
from dm_mac.neon_fob_adder import process_csv_file

# Module path prefixes for cleaner mocking
pbm = "dm_mac.neon_fob_adder"
pb = f"{pbm}.NeonFobUpdater"

# Test credentials
NOX_CREDS: Tuple[str, str] = ("test", "12345")
NOX_AUTH: str = "Basic " + b64encode(":".join(NOX_CREDS).encode("ascii")).decode(
    "ascii"
)


class TestInit:
    """Test the class init() method."""

    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_happy_path(self) -> None:
        """Happy path test."""
        with patch(f"{pbm}.load_json_config") as m_load:
            m_load.return_value = {"foo": "bar"}
            cls = NeonFobUpdater()

        assert cls._config == {"foo": "bar"}
        assert cls._orgid == "test"
        assert cls._token == "12345"
        assert cls._timeout == 10
        assert cls._fobcsv_field_id is None
        assert cls._update_logger is None
        assert m_load.mock_calls == [call("NEONGETTER_CONFIG", "neon.config.json")]

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_env_vars(self) -> None:
        """Test missing environment variables."""
        with pytest.raises(RuntimeError) as exc:
            NeonFobUpdater()

        assert "NEON_ORG" in str(exc.value) or "NEON_KEY" in str(exc.value)


class TestGetCustomFieldsRaw:
    """Test NeonFobUpdater._get_custom_fields_raw()."""

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_happy_path(self, fixtures_path: str) -> None:
        """Test happy path."""
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_custom_fields.yaml")
        )

        with patch(f"{pbm}.load_json_config") as m_load:
            m_load.return_value = {"foo": "bar"}
            cls = NeonFobUpdater()

        # Get registered responses before making calls
        resp: List[responses.BaseResponse] = [*responses.registered()]

        result = cls._get_custom_fields_raw()

        assert len(result) == 2
        assert result[0]["name"] == "Fob10Digit"
        assert result[1]["name"] == "FobCSV"

        # Verify request
        assert len(resp) == 1
        assert resp[0].calls[0].request.headers["Authorization"] == NOX_AUTH
        assert resp[0].calls[0].request.headers["NEON-API-VERSION"] == "2.11"


class TestGetFobcsvFieldId:
    """Test NeonFobUpdater._get_fobcsv_field_id()."""

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_happy_path(self, fixtures_path: str) -> None:
        """Test finding FobCSV field ID."""
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_custom_fields.yaml")
        )

        with patch(f"{pbm}.load_json_config") as m_load:
            m_load.return_value = {"foo": "bar"}
            cls = NeonFobUpdater()

        # Get registered responses before making calls
        resp: List[responses.BaseResponse] = [*responses.registered()]

        result = cls._get_fobcsv_field_id()

        assert result == 145
        assert cls._fobcsv_field_id == 145

        # Call again to test caching
        result2 = cls._get_fobcsv_field_id()
        assert result2 == 145

        # Should only be one API call due to caching
        assert resp[0].call_count == 1

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_field_not_found(self) -> None:
        """Test when FobCSV field is not found."""
        # Mock empty custom fields response
        responses.add(
            responses.GET,
            "https://api.neoncrm.com/v2/customFields?category=Account",
            json=[],
            status=200,
        )

        with patch(f"{pbm}.load_json_config") as m_load:
            m_load.return_value = {"foo": "bar"}
            cls = NeonFobUpdater()

        with pytest.raises(RuntimeError) as exc:
            cls._get_fobcsv_field_id()

        assert "FobCSV" in str(exc.value)
        assert "not found" in str(exc.value)


class TestGetAccountInfo:
    """Test NeonFobUpdater.get_account_info()."""

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_happy_path(self, fixtures_path: str) -> None:
        """Test retrieving account info."""
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )

        cls = NeonFobUpdater()
        result = cls.get_account_info("123")

        assert result["account_id"] == "123"
        assert result["full_name"] == "John Doe"
        assert result["preferred_name"] == "Johnny"
        assert result["email"] == "john.doe@example.com"
        assert result["fob_codes"] == ["1234567890"]

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_with_fobcsv(self, fixtures_path: str) -> None:
        """Test account with FobCSV field populated."""
        responses._add_from_file(
            os.path.join(
                fixtures_path, "test_neon_fob_adder", "get_account_with_fobcsv.yaml"
            )
        )

        cls = NeonFobUpdater()
        result = cls.get_account_info("456")

        assert result["account_id"] == "456"
        assert result["full_name"] == "Jane Smith"
        # Should have fobs from both Fob10Digit and FobCSV
        assert set(result["fob_codes"]) == {"9876543210", "1111111111", "2222222222"}

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_http_error(self) -> None:
        """Test HTTP error handling."""
        responses.add(
            responses.GET,
            "https://api.neoncrm.com/v2/accounts/999",
            json={"error": "Not found"},
            status=404,
        )

        with patch(f"{pbm}.load_json_config") as m_load:
            m_load.return_value = {"foo": "bar"}
            cls = NeonFobUpdater()

        with pytest.raises(Exception):
            cls.get_account_info("999")


class TestUpdateAccountFob:
    """Test NeonFobUpdater.update_account_fob()."""

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_happy_path(self, fixtures_path: str) -> None:
        """Test adding fob to account without existing FobCSV."""
        # Load fixtures for getting account and custom fields
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_custom_fields.yaml")
        )
        # Second GET for the account (to retrieve current FobCSV value)
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        # PATCH response
        responses.add(
            responses.PATCH,
            "https://api.neoncrm.com/v2/accounts/123",
            json={"status": "SUCCESS"},
            status=200,
        )

        cls = NeonFobUpdater()
        result = cls.update_account_fob("123", "3333333333")

        # Should return the new FobCSV value (just the new fob since no existing FobCSV)
        assert result == "3333333333"

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_append_to_existing(self, fixtures_path: str) -> None:
        """Test appending to existing FobCSV."""
        # Get account with existing FobCSV
        responses._add_from_file(
            os.path.join(
                fixtures_path, "test_neon_fob_adder", "get_account_with_fobcsv.yaml"
            )
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_custom_fields.yaml")
        )
        # Second GET for FobCSV value
        responses._add_from_file(
            os.path.join(
                fixtures_path, "test_neon_fob_adder", "get_account_with_fobcsv.yaml"
            )
        )
        # PATCH response
        responses.add(
            responses.PATCH,
            "https://api.neoncrm.com/v2/accounts/456",
            json={"status": "SUCCESS"},
            status=200,
        )

        cls = NeonFobUpdater()
        result = cls.update_account_fob("456", "3333333333")

        # Should append to existing
        assert result == "1111111111,2222222222,3333333333"

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_duplicate_fob(self, fixtures_path: str) -> None:
        """Test duplicate fob detection."""
        responses._add_from_file(
            os.path.join(
                fixtures_path, "test_neon_fob_adder", "get_account_with_fobcsv.yaml"
            )
        )

        cls = NeonFobUpdater()

        # Try to add a fob that already exists in FobCSV
        with pytest.raises(ValueError) as exc:
            cls.update_account_fob("456", "1111111111")

        assert "already exists" in str(exc.value)

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_invalid_fob_non_numeric(self) -> None:
        """Test non-numeric fob code."""
        with patch(f"{pbm}.load_json_config") as m_load:
            m_load.return_value = {"foo": "bar"}
            cls = NeonFobUpdater()

        with pytest.raises(ValueError) as exc:
            cls.update_account_fob("123", "abc1234567")

        assert "must be numeric" in str(exc.value)

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_auto_padding(self, fixtures_path: str) -> None:
        """Test automatic padding to 10 digits."""
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_custom_fields.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses.add(
            responses.PATCH,
            "https://api.neoncrm.com/v2/accounts/123",
            json={"status": "SUCCESS"},
            status=200,
        )

        with patch(f"{pbm}.load_json_config") as m_load:
            m_load.return_value = {
                "account_id_field": "Account ID",
                "full_name_field": "Full Name (F)",
                "preferred_name_field": "Preferred Name",
                "email_field": "Email 1",
                "fob_fields": ["Fob10Digit", "FobCSV"],
            }
            cls = NeonFobUpdater()

        # Pass a short number, should be padded
        result = cls.update_account_fob("123", "123")

        # Should be padded with leading zeroes
        assert result == "0000000123"


class TestAddFobToAccount:
    """Test NeonFobUpdater.add_fob_to_account()."""

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    @patch(f"{pbm}.input")
    @patch("builtins.print")
    def test_successful_add(
        self, m_print: Mock, m_input: Mock, fixtures_path: str, tmp_path: Path
    ) -> None:
        """Test successful fob addition."""
        # Mock user inputs: fob code, then confirmation
        m_input.side_effect = ["3333333333", "y"]

        # Load fixtures
        # add_fob_to_account makes these API calls in order:
        # 1. GET account (to display info)
        # 2. GET account (in update_account_fob to check for duplicates)
        # 3. GET customFields (to get FobCSV field ID)
        # 4. GET account (in update_account_fob to get current FobCSV value)
        # 5. PATCH account
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_custom_fields.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses.add(
            responses.PATCH,
            "https://api.neoncrm.com/v2/accounts/123",
            json={"status": "SUCCESS"},
            status=200,
        )

        cls = NeonFobUpdater()
        cls.add_fob_to_account("123")

        # Verify print was called with account info
        print_calls = [str(call) for call in m_print.mock_calls]
        assert any("Account ID: 123" in call for call in print_calls)
        assert any("John Doe" in call for call in print_calls)
        assert any("Success" in call for call in print_calls)

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    @patch(f"{pbm}.input")
    @patch("builtins.print")
    def test_user_skips(self, m_print: Mock, m_input: Mock, fixtures_path: str) -> None:
        """Test user choosing to skip."""
        m_input.return_value = "s"

        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )

        cls = NeonFobUpdater()
        cls.add_fob_to_account("123")

        # Should print "Skipped"
        print_calls = [str(call) for call in m_print.mock_calls]
        assert any("Skipped" in call for call in print_calls)

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    @patch(f"{pbm}.input")
    @patch("builtins.print")
    def test_user_declines_confirmation(
        self, m_print: Mock, m_input: Mock, fixtures_path: str
    ) -> None:
        """Test user declining at confirmation prompt."""
        m_input.side_effect = ["3333333333", "n"]

        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )

        cls = NeonFobUpdater()
        cls.add_fob_to_account("123")

        # Should print "Cancelled"
        print_calls = [str(call) for call in m_print.mock_calls]
        assert any("Cancelled" in call for call in print_calls)

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    @patch(f"{pbm}.input")
    @patch("builtins.print")
    def test_invalid_fob_input_then_skip(
        self, m_print: Mock, m_input: Mock, fixtures_path: str
    ) -> None:
        """Test invalid fob code input followed by skip."""
        # First input is invalid, second is skip
        m_input.side_effect = ["not-a-number", "s"]

        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )

        cls = NeonFobUpdater()
        cls.add_fob_to_account("123")

        # Should print error and then skip
        print_calls = [str(call) for call in m_print.mock_calls]
        assert any("Error" in call and "numeric" in call for call in print_calls)
        assert any("Skipped" in call for call in print_calls)

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    @patch(f"{pbm}.input")
    @patch("builtins.print")
    def test_invalid_fob_input_then_valid(
        self, m_print: Mock, m_input: Mock, fixtures_path: str
    ) -> None:
        """Test invalid fob code input followed by valid input."""
        # First input is invalid, second is valid, third is confirmation
        m_input.side_effect = ["not-a-number", "3333333333", "y"]

        # Load fixtures for successful addition
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_custom_fields.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses.add(
            responses.PATCH,
            "https://api.neoncrm.com/v2/accounts/123",
            json={"status": "SUCCESS"},
            status=200,
        )

        cls = NeonFobUpdater()
        cls.add_fob_to_account("123")

        # Should print error, then success
        print_calls = [str(call) for call in m_print.mock_calls]
        assert any("Error" in call and "numeric" in call for call in print_calls)
        assert any("Success" in call for call in print_calls)

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    @patch(f"{pbm}.input")
    @patch("builtins.print")
    def test_multiple_invalid_inputs_then_valid(
        self, m_print: Mock, m_input: Mock, fixtures_path: str
    ) -> None:
        """Test multiple invalid inputs before valid input."""
        # Multiple invalid inputs, then valid, then confirmation
        m_input.side_effect = [
            "abc123",  # non-numeric
            "12345678901",  # too long (11 digits)
            "3333333333",  # valid
            "y",  # confirmation
        ]

        # Load fixtures for successful addition
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_custom_fields.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses.add(
            responses.PATCH,
            "https://api.neoncrm.com/v2/accounts/123",
            json={"status": "SUCCESS"},
            status=200,
        )

        cls = NeonFobUpdater()
        cls.add_fob_to_account("123")

        # Should print multiple errors, then success
        print_calls = [str(call) for call in m_print.mock_calls]
        assert any("Error" in call and "numeric" in call for call in print_calls)
        assert any("Error" in call and "10 digits" in call for call in print_calls)
        assert any("Success" in call for call in print_calls)

    @responses.activate(registry=OrderedRegistry)
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    @patch(f"{pbm}.input")
    @patch("builtins.print")
    def test_duplicate_fob_input_then_valid(
        self, m_print: Mock, m_input: Mock, fixtures_path: str
    ) -> None:
        """Test duplicate fob code input followed by valid input."""
        # First input is duplicate, second is valid, third is confirmation
        m_input.side_effect = ["1234567890", "3333333333", "y"]

        # Load fixtures for successful addition
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_custom_fields.yaml")
        )
        responses._add_from_file(
            os.path.join(fixtures_path, "test_neon_fob_adder", "get_account.yaml")
        )
        responses.add(
            responses.PATCH,
            "https://api.neoncrm.com/v2/accounts/123",
            json={"status": "SUCCESS"},
            status=200,
        )

        cls = NeonFobUpdater()
        cls.add_fob_to_account("123")

        # Should print error about duplicate, then success
        print_calls = [str(call) for call in m_print.mock_calls]
        assert any("Error" in call and "already exists" in call for call in print_calls)
        assert any("Success" in call for call in print_calls)


class TestParseArgs:
    """Test parse_args() function."""

    def test_account_ids_mode(self) -> None:
        """Test parsing account IDs."""
        args = parse_args(["123", "456", "789"])

        assert args.account_ids == ["123", "456", "789"]
        assert args.csv_path is None
        assert args.field_name is None
        assert args.verbose is False

    def test_csv_mode(self) -> None:
        """Test CSV mode arguments."""
        args = parse_args(["--csv", "test.csv", "--field", "account_id"])

        assert args.account_ids == []
        assert args.csv_path == "test.csv"
        assert args.field_name == "account_id"

    def test_verbose_flag(self) -> None:
        """Test verbose flag."""
        args = parse_args(["-v", "123"])

        assert args.verbose is True

    def test_conflicting_modes(self) -> None:
        """Test error when both modes are used."""
        with pytest.raises(SystemExit):
            parse_args(["123", "--csv", "test.csv", "--field", "account_id"])

    def test_csv_without_field(self) -> None:
        """Test error when CSV specified without field."""
        with pytest.raises(SystemExit):
            parse_args(["--csv", "test.csv"])

    def test_field_without_csv(self) -> None:
        """Test error when field specified without CSV."""
        with pytest.raises(SystemExit):
            parse_args(["--field", "account_id"])

    def test_no_arguments(self) -> None:
        """Test error when no mode specified."""
        with pytest.raises(SystemExit):
            parse_args([])


class TestProcessCsvFile:
    """Test process_csv_file() function."""

    def test_happy_path(self, fixtures_path: str) -> None:
        """Test processing CSV file."""
        csv_path = os.path.join(
            fixtures_path, "test_neon_fob_adder", "test_accounts.csv"
        )

        mock_updater = Mock(spec=NeonFobUpdater)
        process_csv_file(csv_path, "account_id", mock_updater)

        # Should call add_fob_to_account for each row
        assert mock_updater.add_fob_to_account.call_count == 3
        assert mock_updater.add_fob_to_account.mock_calls == [
            call("123"),
            call("456"),
            call("789"),
        ]

    def test_missing_field(self, tmp_path: Path) -> None:
        """Test error when field not in CSV."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("id,name\n1,foo\n2,bar\n")

        mock_updater = Mock(spec=NeonFobUpdater)

        with pytest.raises(ValueError) as exc:
            process_csv_file(str(csv_file), "account_id", mock_updater)

        assert "account_id" in str(exc.value)
        assert "not found" in str(exc.value)


class TestMain:
    """Test main() function."""

    @patch(f"{pbm}.NeonFobUpdater")
    @patch(f"{pbm}.set_log_info")
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_account_ids_mode(self, m_log: Mock, m_updater_class: Mock) -> None:
        """Test main with account IDs."""
        mock_updater = Mock()
        m_updater_class.return_value = mock_updater

        with patch("sys.argv", ["neon-fob-adder", "123", "456"]):
            main()

        # Should create updater and call add_fob_to_account for each ID
        assert m_updater_class.call_count == 1
        assert mock_updater.add_fob_to_account.mock_calls == [call("123"), call("456")]

    @patch(f"{pbm}.process_csv_file")
    @patch(f"{pbm}.NeonFobUpdater")
    @patch(f"{pbm}.set_log_info")
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_csv_mode(
        self, m_log: Mock, m_updater_class: Mock, m_process: Mock
    ) -> None:
        """Test main with CSV mode."""
        mock_updater = Mock()
        m_updater_class.return_value = mock_updater

        with patch(
            "sys.argv",
            ["neon-fob-adder", "--csv", "test.csv", "--field", "account_id"],
        ):
            main()

        # Should call process_csv_file
        assert m_process.call_count == 1
        assert m_process.mock_calls == [call("test.csv", "account_id", mock_updater)]

    @patch(f"{pbm}.NeonFobUpdater")
    @patch(f"{pbm}.set_log_debug")
    @patch.dict(
        "os.environ",
        {
            "NEON_ORG": "test",
            "NEON_KEY": "12345",
            "NEONGETTER_CONFIG": "tests/fixtures/neon.config.json",
        },
    )
    def test_verbose_logging(self, m_log_debug: Mock, m_updater_class: Mock) -> None:
        """Test verbose flag sets debug logging."""
        with patch("sys.argv", ["neon-fob-adder", "-v", "123"]):
            main()

        assert m_log_debug.call_count == 1
