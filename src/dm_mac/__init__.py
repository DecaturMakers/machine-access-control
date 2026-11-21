"""Decatur Makers Machine Access Control."""

import argparse
import json
import logging
import os
import sys
from asyncio import AbstractEventLoop
from asyncio import get_event_loop
from datetime import datetime
from time import time
from typing import Any
from typing import Dict

from quart import Quart
from quart import has_request_context
from quart import request
from quart.logging import default_handler
from quart_schema import QuartSchema
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from dm_mac.models.machine import FleetTimeoutTracker
from dm_mac.models.machine import MachinesConfig
from dm_mac.models.users import UsersConfig
from dm_mac.slack_handler import SlackHandler
from dm_mac.utils import set_log_debug
from dm_mac.utils import set_log_info
from dm_mac.views.api import api
from dm_mac.views.machine import machineapi
from dm_mac.views.prometheus import prometheus_route
from dm_mac.webhook import WebhookNotifier

logger: logging.Logger = logging.getLogger()
logging.basicConfig(
    level=logging.WARNING, format="[%(asctime)s %(levelname)s] %(message)s"
)

# BEGIN adding request information to logs


class RequestFormatter(logging.Formatter):
    """Custom log formatter to add request information."""

    def format(self, record: logging.LogRecord) -> str:
        """Custom log formatter to add request information."""
        if has_request_context():
            record.url = request.url
            record.remote_addr = request.remote_addr
        else:
            record.url = None
            record.remote_addr = None

        return super().format(record)


#: Attribute names present on every LogRecord (plus those set by
#: ``Formatter.format()``); anything else on a record came from ``extra=``.
_STANDARD_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
) | {"message", "asctime", "taskName", "url", "remote_addr"}


class JsonFormatter(logging.Formatter):
    """Format each log record as a single-line JSON object.

    See ``docs/source/configuration.rst`` (JSON Logging) for the field list.
    """

    def __init__(self, include_location: bool = False) -> None:
        """Optionally include source file, line, and function fields."""
        super().__init__()
        self.include_location: bool = include_location

    def format(self, record: logging.LogRecord) -> str:
        """Render ``record`` as one line of JSON."""
        data: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created)
            .astimezone()
            .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "remote_addr": None,
            "url": None,
        }
        if has_request_context():
            data["remote_addr"] = request.remote_addr
            data["url"] = request.url
        if self.include_location:
            data["filename"] = record.filename
            data["lineno"] = record.lineno
            data["funcName"] = record.funcName
        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            data["stack_info"] = self.formatStack(record.stack_info)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and key not in data:
                data[key] = value
        return json.dumps(data, default=str, ensure_ascii=False)


formatter = RequestFormatter(
    "%(asctime)s %(levelname)s:[%(remote_addr)s]:%(name)s:%(message)s"
)
default_handler.setFormatter(formatter)

# END adding request information to logs

# enable logging from libraries (i.e. everything but the views)
logging.getLogger().addHandler(default_handler)

logging.getLogger("AUTH").setLevel(logging.INFO)
logging.getLogger().setLevel(logging.INFO)

# see: https://github.com/pallets/flask/issues/4786#issuecomment-1416354177
api.register_blueprint(machineapi)

app: Quart


def configure_log_format(lgr: logging.Logger, verbose: bool) -> None:
    """Switch ``lgr`` to JSON output if the ``LOG_FORMAT`` env var says so.

    ``LOG_FORMAT`` is ``text`` (default) or ``json``, case-insensitive. Text
    mode leaves logging exactly as it is. JSON mode leaves Quart's
    ``default_handler`` as the only handler on ``lgr`` (so each record is
    written once) and gives it a :py:class:`JsonFormatter`. Any other value
    keeps text output and logs a warning.
    """
    raw: str = os.environ.get("LOG_FORMAT", "")
    value: str = raw.strip().lower()
    if value in ("", "text"):
        return
    if value != "json":
        lgr.warning("Unknown LOG_FORMAT %r; using text", raw)
        return
    for handler in list(lgr.handlers):
        if handler is not default_handler:
            lgr.removeHandler(handler)
    if default_handler not in lgr.handlers:
        lgr.addHandler(default_handler)
    default_handler.setFormatter(JsonFormatter(include_location=verbose))


def asyncio_exception_handler(_, context):
    # get details of the exception
    exception = context["exception"]
    message = context["message"]
    # log exception
    logger.error(f"Task failed, msg={message}, exception={exception}")


def create_app() -> Quart:
    """Factory to create the app."""
    app: Quart = Quart("dm_mac")
    QuartSchema(
        app,
        info={
            "title": "Decatur Makers Machine Access Control API",
            "version": "0.9.1",
            "description": (
                "HTTP API for the Decatur Makers Machine Access Control system. "
                "Used by ESP32-based Machine Control Units (MCUs) to report state "
                "and receive commands, and by administrators for machine management."
            ),
        },
        tags=[
            {"name": "Machine", "description": "Machine state and control endpoints"},
            {"name": "Admin", "description": "Administrative endpoints"},
            {"name": "Monitoring", "description": "Monitoring and metrics endpoints"},
        ],
    )
    app.config.update({"MACHINES": MachinesConfig()})
    app.config.update({"USERS": UsersConfig()})
    app.config.update({"START_TIME": time()})
    app.config.update({"SLACK_HANDLER": None})
    app.config.update({"WEBHOOK_NOTIFIER": WebhookNotifier.from_env()})
    app.config.update({"FLEET_TIMEOUT_TRACKER": FleetTimeoutTracker()})
    app.register_blueprint(api)
    app.add_url_rule("/metrics", view_func=prometheus_route)
    return app


def main() -> None:
    global app
    p = argparse.ArgumentParser(description="Run Machine Access Control (MAC) server")
    p.add_argument(
        "-d",
        "--debug",
        dest="debug",
        action="store_true",
        default=False,
        help="Debug mode",
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
        "-P",
        "--port",
        dest="port",
        action="store",
        type=int,
        default=5000,
        help="Port number to listen on (default 5000)",
    )
    args = p.parse_args(sys.argv[1:])
    if args.verbose:
        set_log_debug(logger)
    else:
        set_log_info(logger)
    configure_log_format(logger, args.verbose)
    loop: AbstractEventLoop = get_event_loop()
    loop.set_exception_handler(asyncio_exception_handler)
    app = create_app()
    token: str = os.environ.get("SLACK_APP_TOKEN", "").strip()
    if token:
        slack: SlackHandler = SlackHandler(app)
        app.config.update({"SLACK_HANDLER": slack})
        handler = AsyncSocketModeHandler(
            slack.app, os.environ["SLACK_APP_TOKEN"], loop=loop
        )
        loop.create_task(handler.start_async())
    app.run(loop=loop, debug=args.debug, host="0.0.0.0", port=args.port)


if __name__ == "__main__":  # pragma: no cover
    main()
