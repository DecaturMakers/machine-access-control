"""Tool to update users.json from NeonOne API."""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from datetime import timedelta
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple
from typing import Union
from typing import cast

import requests
from jsonschema import validate
from requests import Response
from requests import Session
from requests.adapters import HTTPAdapter

from dm_mac.cli_utils import env_var_or_die
from dm_mac.cli_utils import set_log_debug
from dm_mac.cli_utils import set_log_info
from dm_mac.models.users import UsersConfig
from dm_mac.utils import load_json_config

logging.basicConfig(
    level=logging.WARNING, format="[%(asctime)s %(levelname)s] %(message)s"
)
logger: logging.Logger = logging.getLogger()

# suppress noisy urllib3 logging
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("urllib3").propagate = True

CONFIG_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "full_name_field": {
            "type": "string",
            "description": "Neon field name containing member full name.",
        },
        "first_name_field": {
            "type": "string",
            "description": "Neon field name containing member first name.",
        },
        "last_name_field": {
            "type": "string",
            "description": "Neon field name containing member last name.",
        },
        "preferred_name_field": {
            "type": "string",
            "description": "Neon field name containing member preferred name.",
        },
        "email_field": {
            "type": "string",
            "description": "Neon field name containing member email " "address.",
        },
        "expiration_field": {
            "type": "string",
            "description": "Neon field name containing membership " "expiration date.",
        },
        "account_id_field": {
            "type": "string",
            "description": "Neon field name containing account ID.",
        },
        "fob_fields": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "List of Neon field names containing RFID "
            "fob codes. The value of these fields can be either "
            "a single string fob code, or a CSV list of multiple"
            " fob codes.",
        },
        "authorized_field_value": {
            "type": "string",
            "description": "Value for name of option indicating that "
            "member is authorized / training complete.",
        },
        "oops_override_field": {
            "type": "string",
            "description": "Neon custom field name for the oops override "
            "authorization checkbox. Defaults to 'OOPS_OVERRIDE'.",
        },
        "static_fobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fob_codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "List of RFID fob codes for this user.",
                    },
                    "account_id": {
                        "type": "string",
                        "description": "Account ID for this user.",
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address for this user.",
                    },
                    "full_name": {
                        "type": "string",
                        "description": "Full name of this user.",
                    },
                    "first_name": {
                        "type": "string",
                        "description": "First name of this user.",
                    },
                    "last_name": {
                        "type": "string",
                        "description": "Last name of this user.",
                    },
                    "preferred_name": {
                        "type": "string",
                        "description": "Preferred name of this user.",
                    },
                    "expiration_ymd": {
                        "type": "string",
                        "description": "Membership expiration date in YYYY-MM-DD format.",
                    },
                    "authorizations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of authorizations for this user.",
                    },
                    "oops_override": {
                        "type": "boolean",
                        "description": "Whether this user can perform "
                        "override logins on oopsed/locked-out machines.",
                    },
                },
                "required": [
                    "fob_codes",
                    "account_id",
                    "email",
                    "full_name",
                    "first_name",
                    "last_name",
                    "preferred_name",
                    "expiration_ymd",
                    "authorizations",
                ],
                "additionalProperties": False,
            },
            "description": "Optional list of static user entries to be added "
            "directly to users.json without querying NeonOne API.",
        },
    },
    "required": [
        "full_name_field",
        "first_name_field",
        "last_name_field",
        "preferred_name_field",
        "email_field",
        "expiration_field",
        "account_id_field",
        "fob_fields",
        "authorized_field_value",
    ],
    "additionalProperties": False,
}


class NeonUserUpdater:
    """Class to update users.json from Neon One API."""

    BASE_URL: str = "https://api.neoncrm.com/v2/"

    MAX_PAGE_SIZE: int = 200
    #: Total attempts for the account search POST (transient failures only).
    SEARCH_ATTEMPTS: int = 3
    #: Seconds to sleep before retry N (1-based) is ``N * SEARCH_BACKOFF_SEC``.
    SEARCH_BACKOFF_SEC: int = 10

    def __init__(self, dump_fields: bool = False):
        """Initialize NeonUserUpdater."""
        self._orgid: str = env_var_or_die("NEON_ORG", "your Neon organization ID")
        self._token: str = env_var_or_die("NEON_KEY", "your Neon API key")
        self._sess: Session = Session()
        self._sess.mount("https://", HTTPAdapter(max_retries=3))
        self._sess.auth = (self._orgid, self._token)
        self._sess.headers.update({"NEON-API-VERSION": "2.11"})
        logger.debug(
            "Will authenticate to Neon API using Username (organization ID) "
            "%s and password (token) of length %d: %s...",
            self._orgid,
            len(self._token),
            self._token[:3],
        )
        self._timeout: int = 30
        if dump_fields:
            logger.debug("dump_fields passed; dumping fields and then exiting")
            self._dump_fields()
            return
        self._config: Dict[str, Union[str, List[str]]] = (
            self._load_and_validate_config()
        )

    def _load_and_validate_config(self) -> Dict[str, Union[str, List[str]]]:
        """Load and validate the config file."""
        config: Dict[str, Union[str, List[str]]] = cast(
            Dict[str, Union[str, List[str]]],
            load_json_config("NEONGETTER_CONFIG", "neon.config.json"),
        )
        NeonUserUpdater.validate_config(config)
        return config

    def _get_custom_fields_raw(self) -> List[Dict[str, Any]]:
        """Return the raw API response for custom fields."""
        url: str = self.BASE_URL + "customFields?category=Account"
        logger.debug("GET %s", url)
        r: Response = self._sess.get(url, timeout=self._timeout)
        logger.debug(
            "Neon returned HTTP %d with %d byte content", r.status_code, len(r.content)
        )
        try:
            r.raise_for_status()
        except Exception:
            logger.error(
                "HTTP GET of %s returned HTTP %d headers=%s body=%s",
                url,
                r.status_code,
                r.headers,
                r.text,
            )
            raise
        return cast(List[Dict[str, Any]], r.json())

    def _dump_fields(self) -> None:
        print("Account fields:")
        url: str = self.BASE_URL + "accounts/search/outputFields?searchKey=1"
        logger.debug("GET %s", url)
        r: Response = self._sess.get(url, timeout=self._timeout)
        logger.debug(
            "Neon returned HTTP %d with %d byte content", r.status_code, len(r.content)
        )
        r.raise_for_status()
        print(json.dumps(r.json(), sort_keys=True, indent=4))
        print("Custom fields:")
        print(json.dumps(self._get_custom_fields_raw(), sort_keys=True, indent=4))

    @staticmethod
    def validate_config(config: Dict[str, Any]) -> None:
        """Validate configuration via jsonschema."""
        logger.debug("Validating NeonUserUpdater config")
        validate(config, CONFIG_SCHEMA)
        logger.debug("NeonUserConfig is valid")

    @staticmethod
    def example_config() -> Dict[str, Any]:
        """Return an example configuration."""
        return {
            "full_name_field": "Full Name (F)",
            "first_name_field": "First Name",
            "last_name_field": "Last Name",
            "preferred_name_field": "Preferred Name",
            "email_field": "Email 1",
            "expiration_field": "Membership Expiration Date",
            "account_id_field": "Account ID",
            "fob_fields": ["Fob10Digit"],
            "authorized_field_value": "Training Complete",
            "static_fobs": [
                {
                    "fob_codes": ["9999999999"],
                    "account_id": "static-1",
                    "email": "static@example.com",
                    "full_name": "Static User",
                    "first_name": "Static",
                    "last_name": "User",
                    "preferred_name": "Static",
                    "expiration_ymd": "2099-12-31",
                    "authorizations": ["Woodshop 101", "CNC Router"],
                }
            ],
        }

    def fields_to_get(self) -> List[Union[str, int, List[str]]]:
        """Return a list of custom field names to retrieve from Neon."""
        field_names: List[Union[str, int, List[str]]] = [
            self._config["full_name_field"],
            self._config["email_field"],
            self._config["expiration_field"],
            self._config["account_id_field"],
            self._config["first_name_field"],
            self._config["last_name_field"],
            self._config["preferred_name_field"],
        ]
        override_field: str = cast(
            str, self._config.get("oops_override_field", "OOPS_OVERRIDE")
        )
        customs: List[Dict[str, Any]] = self._get_custom_fields_raw()
        logger.debug("Neon API returned %d custom fields", len(customs))
        for cust in customs:
            if cust["name"] in self._config["fob_fields"]:
                field_names.append(int(cust["id"]))
                continue
            if cust.get("displayType") != "Checkbox":
                continue
            have_value: bool = False
            for opt in cust.get("optionValues", []):
                if opt.get("name") == self._config["authorized_field_value"]:
                    have_value = True
                    break
            if have_value:
                field_names.append(int(cust["id"]))
            elif cust["name"] == override_field:
                field_names.append(int(cust["id"]))
        logger.info("Fields to get from Neon API: %s", field_names)
        return field_names

    def _post_search(self, url: str, data: Dict[str, Any]) -> requests.Response:
        """
        POST the (read-only, so idempotent) account search, with retries.

        Connection errors, timeouts and HTTP 429/5xx are retried, up to
        ``SEARCH_ATTEMPTS`` total attempts with linear backoff. Other 4xx
        responses are returned immediately. After the final attempt, the last
        exception is raised, or the last response returned (so the caller's
        ``raise_for_status()`` fails as it always has).
        """
        for attempt in range(1, self.SEARCH_ATTEMPTS + 1):
            last: bool = attempt == self.SEARCH_ATTEMPTS
            try:
                r: requests.Response = self._sess.post(
                    url, timeout=self._timeout, json=data
                )
            except (requests.ConnectionError, requests.Timeout) as ex:
                if last:
                    raise
                reason: str = f"{type(ex).__name__}: {ex}"
            else:
                if r.status_code != 429 and r.status_code < 500:
                    return r
                if last:
                    return r
                reason = f"HTTP {r.status_code}"
            delay: int = attempt * self.SEARCH_BACKOFF_SEC
            logger.warning(
                "Neon account search attempt %d of %d failed (%s); "
                "retrying in %d seconds",
                attempt,
                self.SEARCH_ATTEMPTS,
                reason,
                delay,
            )
            time.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def _get_users_page(
        self, page: int, fields: List[Union[str, int, List[str]]], cutoff: str
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """Get a specified page of the account search endpoint."""
        url: str = f"{self.BASE_URL}accounts/search"
        data: Dict[str, Any] = {
            "outputFields": fields,
            "pagination": {
                "currentPage": page,
                "pageSize": self.MAX_PAGE_SIZE,
            },
            "searchFields": [
                {
                    "field": "Account Type",
                    "operator": "EQUAL",
                    "value": "Individual",
                },
                {
                    "field": "Membership Expiration Date",
                    "operator": "GREATER_AND_EQUAL",
                    "value": cutoff,
                },
            ],
        }
        logger.debug(
            "POST %s with data: %s", url, json.dumps(data, sort_keys=True, indent=4)
        )
        r: requests.Response = self._post_search(url, data)
        try:
            r.raise_for_status()
        except Exception:
            logger.error(
                "HTTP GET of %s returned HTTP %d headers=%s body=%s",
                url,
                r.status_code,
                r.headers,
                r.text,
            )
            raise
        search_dict = r.json()
        last_page: int = search_dict["pagination"]["totalPages"] - 1
        results: List[Dict[str, Any]] = search_dict["searchResults"]
        logger.debug(
            "Users search returned %d accounts; last_page=%d", len(results), last_page
        )
        return last_page, results

    def get_users(
        self, fields: List[Union[str, int, List[str]]]
    ) -> List[Dict[str, Any]]:
        """Pull users from NeonCRM."""
        current_page: int = 0
        last_page: int = 0
        cutoff: str = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        results: List[Dict[str, Any]]
        users: List[Dict[str, Any]] = []
        while current_page <= last_page:
            last_page, results = self._get_users_page(current_page, fields, cutoff)
            users.extend(results)
            current_page += 1
        logger.info(
            "Retrieved %d total users (active or expired in the last week) "
            "from Neon API",
            len(users),
        )
        return users

    def _mac_users_reload(self) -> None:
        """If env var set, trigger users config reload."""
        if "MAC_USER_RELOAD_URL" not in os.environ:
            logger.info("MAC_USER_RELOAD_URL env var not set; not reloading config")
            return
        url: str = os.environ["MAC_USER_RELOAD_URL"]
        logger.debug("POST to %s", url)
        r = requests.post(url, timeout=20)
        logger.debug("POST returned HTTP %d: %s", r.status_code, r.text)
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError:
            logger.exception(
                "POST to %s returned HTTP %d: %s", url, r.status_code, r.text
            )
            raise
        logger.info("Reloaded users config in MAC: %s", r.json())

    def run(self, output_path: str) -> None:
        """Run the update."""
        field_names: List[Union[str, int, List[str]]] = self.fields_to_get()
        rawdata: List[Dict[str, Any]] = self.get_users(field_names)
        users: List[Dict[str, Any]] = []
        logger.info("Generating users config")
        fobs: Dict[str, Dict[str, Any]] = {}
        dupes: List[str] = []
        override_field: str = cast(
            str, self._config.get("oops_override_field", "OOPS_OVERRIDE")
        )
        for user in rawdata:
            # Handle last_name - if not in response, extract from full_name
            last_name = user.get(self._config["last_name_field"])  # type: ignore
            if not last_name:
                # Fallback: extract from full_name (take last word)
                full_name_parts = user[self._config["full_name_field"]].split()  # type: ignore
                last_name = full_name_parts[-1] if full_name_parts else ""
            tmp: Dict[str, Any] = {
                "fob_codes": [],
                "account_id": user[self._config["account_id_field"]],  # type: ignore
                "email": user[self._config["email_field"]],  # type: ignore
                "full_name": user[self._config["full_name_field"]],  # type: ignore
                "first_name": user[self._config["first_name_field"]],  # type: ignore
                "last_name": last_name,
                "preferred_name": user[self._config["preferred_name_field"]],  # type: ignore
                "expiration_ymd": user[self._config["expiration_field"]],  # type: ignore
                "authorizations": [
                    x
                    for x in user.keys()
                    if user[x] == self._config["authorized_field_value"]
                    and x != override_field
                ],
                "oops_override": user.get(override_field)
                == self._config["authorized_field_value"],
            }
            for x in self._config["fob_fields"]:
                if tmpfobs := user.get(x):
                    tmp["fob_codes"].extend(tmpfobs.split(","))
            if not tmp["expiration_ymd"]:
                logger.info(
                    "Found user with no expiration date; account_id=%s name=%s",
                    tmp["account_id"],
                    tmp["full_name"],
                )
                tmp["expiration_ymd"] = "2345-01-01"
            user_fobs: List[str] = []
            for fobfield in self._config["fob_fields"]:
                if fobfield not in user:  # pragma: no cover
                    logger.debug("User does not have field %s: %s", user, fobfield)
                    continue
                if not user[fobfield]:  # pragma: no cover
                    logger.warning("User has null field %s: %s", user, fobfield)
                    continue
                # check for duplicate fob number
                ff: str = user[fobfield]
                if ff in fobs:
                    dupes.append(
                        f"fob {ff} is present in user {fobs[ff]['full_name']} "
                        f"({fobs[ff]['account_id']}) as well as "
                        f"{tmp['full_name']} ({tmp['account_id']})"
                    )
                    continue
                fobs[ff] = tmp
                user_fobs.append(ff)
            users.append(tmp)
        if dupes:
            raise RuntimeError(
                "ERROR: Duplicate fob fields: " + "; ".join(sorted(dupes))
            )
        # Add static fobs if present in config
        if "static_fobs" in self._config:
            static_users: List[Dict[str, Any]] = cast(
                List[Dict[str, Any]], self._config["static_fobs"]
            )
            logger.info("Processing %d static user entries", len(static_users))
            for static_user in static_users:
                # Check for duplicate fob codes and track if user has valid fobs
                valid_fob_count = 0
                for fob_code in static_user["fob_codes"]:
                    if fob_code in fobs:
                        dupes.append(
                            f"fob {fob_code} is present in user "
                            f"{fobs[fob_code]['full_name']} "
                            f"({fobs[fob_code]['account_id']}) as well as "
                            f"static user {static_user['full_name']} "
                            f"({static_user['account_id']})"
                        )
                        continue
                    fobs[fob_code] = static_user
                    valid_fob_count += 1
                # Only add the static user if they have at least one valid fob
                if valid_fob_count > 0:
                    # Set oops_override default for static users
                    if "oops_override" not in static_user:
                        static_user["oops_override"] = False
                    users.append(static_user)
            if dupes:
                raise RuntimeError(
                    "ERROR: Duplicate fob fields: " + "; ".join(sorted(dupes))
                )
        UsersConfig.validate_config(users)
        logger.info("Writing users config for %d users to %s", len(users), output_path)
        with open(output_path, "w") as fh:
            json.dump(users, fh, sort_keys=True, indent=4)
        self._mac_users_reload()


def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse command line arguments."""
    p = argparse.ArgumentParser(description="Update users.json from Neon API")
    p.add_argument(
        "--dump-fields",
        dest="dump_fields",
        action="store_true",
        default=False,
        help="Just dump Neon API fields to STDOUT and then exit",
    )
    p.add_argument(
        "--dump-example-config",
        dest="dump_example_config",
        action="store_true",
        default=False,
        help="Just dump example config file to STDOUT and then exit",
    )
    p.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        default=False,
        help="verbose output",
    )
    p.add_argument(
        "-o",
        "--output-path",
        dest="output_path",
        action="store",
        type=str,
        default="users.json",
        help="Output path for users.json file",
    )
    args = p.parse_args(argv)
    return args


def main() -> None:
    """Main entrypoint for CLI script."""
    args = parse_args(sys.argv[1:])
    # set logging level
    if args.verbose:
        set_log_debug(logger)
    else:
        set_log_info(logger)
    if args.dump_fields:
        NeonUserUpdater(dump_fields=True)
    elif args.dump_example_config:
        print(json.dumps(NeonUserUpdater.example_config(), sort_keys=True, indent=4))
    else:
        NeonUserUpdater().run(output_path=args.output_path)
