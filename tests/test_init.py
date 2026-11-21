import io
import json
import logging
import os
from datetime import datetime
from types import TracebackType
from typing import Any
from typing import Dict
from typing import Generator
from typing import List
from typing import Optional
from typing import Tuple
from unittest.mock import DEFAULT
from unittest.mock import MagicMock
from unittest.mock import call
from unittest.mock import patch

import pytest
from quart import Quart
from quart.logging import default_handler

from dm_mac import JsonFormatter
from dm_mac import asyncio_exception_handler
from dm_mac import configure_log_format
from dm_mac import main


def test_exception_handler():
    with patch("dm_mac.logger") as m_logger:
        asyncio_exception_handler(None, {"exception": "exc", "message": "msg"})
        assert m_logger.mock_calls == [
            call.error("Task failed, msg=msg, exception=exc")
        ]


class TestMain:

    @patch("sys.argv", ["mac-server"])
    @patch.dict("os.environ", {"SLACK_APP_TOKEN": "app-token"})
    def test_with_slack(self):
        mocks: List[MagicMock]
        with patch.multiple(
            "dm_mac",
            set_log_debug=DEFAULT,
            set_log_info=DEFAULT,
            configure_log_format=DEFAULT,
            get_event_loop=DEFAULT,
            SlackHandler=DEFAULT,
            AsyncSocketModeHandler=DEFAULT,
            logger=DEFAULT,
            create_app=DEFAULT,
            new_callable=MagicMock,
        ) as mocks:
            slack_app = MagicMock()
            type(mocks["SlackHandler"].return_value).app = slack_app
            loop = MagicMock()
            app = MagicMock()
            handler = MagicMock()
            mocks["get_event_loop"].return_value = loop
            mocks["create_app"].return_value = app
            mocks["AsyncSocketModeHandler"].return_value = handler
            main()
        assert mocks["set_log_debug"].mock_calls == []
        assert mocks["set_log_info"].mock_calls == [call(mocks["logger"])]
        assert mocks["configure_log_format"].mock_calls == [
            call(mocks["logger"], False)
        ]
        assert mocks["create_app"].mock_calls == [
            call(),
            call().config.update({"SLACK_HANDLER": mocks["SlackHandler"].return_value}),
            call().run(loop=loop, debug=False, host="0.0.0.0", port=5000),
        ]
        assert app.mock_calls == [
            call.config.update({"SLACK_HANDLER": mocks["SlackHandler"].return_value}),
            call.run(loop=loop, debug=False, host="0.0.0.0", port=5000),
        ]
        assert mocks["SlackHandler"].mock_calls == [call(app)]
        assert mocks["AsyncSocketModeHandler"].mock_calls == [
            call(slack_app, "app-token", loop=loop),
            call().start_async(),
        ]
        assert loop.mock_calls == [
            call.set_exception_handler(asyncio_exception_handler),
            call.create_task(handler.start_async()),
        ]

    @patch("sys.argv", ["mac-server", "-v", "--port=123"])
    @patch.dict("os.environ", {"SLACK_APP_TOKEN": ""})
    def test_without_slack(self):
        mocks: List[MagicMock]
        with patch.multiple(
            "dm_mac",
            set_log_debug=DEFAULT,
            set_log_info=DEFAULT,
            configure_log_format=DEFAULT,
            get_event_loop=DEFAULT,
            SlackHandler=DEFAULT,
            AsyncSocketModeHandler=DEFAULT,
            logger=DEFAULT,
            create_app=DEFAULT,
            new_callable=MagicMock,
        ) as mocks:
            slack_app = MagicMock()
            type(mocks["SlackHandler"].return_value).app = slack_app
            loop = MagicMock()
            app = MagicMock()
            handler = MagicMock()
            mocks["get_event_loop"].return_value = loop
            mocks["create_app"].return_value = app
            mocks["AsyncSocketModeHandler"].return_value = handler
            main()
        assert mocks["set_log_debug"].mock_calls == [call(mocks["logger"])]
        assert mocks["set_log_info"].mock_calls == []
        assert mocks["configure_log_format"].mock_calls == [call(mocks["logger"], True)]
        assert mocks["create_app"].mock_calls == [
            call(),
            call().run(loop=loop, debug=False, host="0.0.0.0", port=123),
        ]
        assert app.mock_calls == [
            call.run(loop=loop, debug=False, host="0.0.0.0", port=123)
        ]
        assert mocks["SlackHandler"].mock_calls == []
        assert mocks["AsyncSocketModeHandler"].mock_calls == []
        assert loop.mock_calls == [
            call.set_exception_handler(asyncio_exception_handler),
        ]


ExcInfo = Tuple[type[BaseException], BaseException, Optional[TracebackType]]


def _record(
    msg: str = "hello %s",
    args: Tuple[Any, ...] = ("world",),
    level: int = logging.INFO,
    exc_info: Optional[ExcInfo] = None,
    **extra: Any,
) -> logging.LogRecord:
    rec = logging.LogRecord(
        "some.logger", level, "/path/to/mod.py", 42, msg, args, exc_info, "myfunc"
    )
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


class TestJsonFormatter:

    def test_required_fields(self) -> None:
        rec = _record()
        line = JsonFormatter().format(rec)
        assert "\n" not in line
        data = json.loads(line)
        assert data == {
            "timestamp": datetime.fromtimestamp(rec.created)
            .astimezone()
            .isoformat(timespec="milliseconds"),
            "level": "INFO",
            "logger": "some.logger",
            "message": "hello world",
            "remote_addr": None,
            "url": None,
        }
        ts = datetime.fromisoformat(data["timestamp"])
        assert ts.utcoffset() is not None

    async def test_request_context(self) -> None:
        app = Quart(__name__)
        async with app.test_request_context(
            "/api/machines", headers={"Remote-Addr": "10.1.2.3"}
        ):
            data = json.loads(JsonFormatter().format(_record()))
        assert data["remote_addr"] == "10.1.2.3"
        assert data["url"] == "http://localhost/api/machines"

    def test_exception_and_stack(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError as err:
            exc: ExcInfo = (type(err), err, err.__traceback__)
        rec = _record(exc_info=exc)
        rec.stack_info = "Stack (most recent call last):\n  frame"
        line = JsonFormatter().format(rec)
        assert "\n" not in line
        data = json.loads(line)
        assert data["exc_info"].startswith("Traceback (most recent call last):")
        assert "ValueError: boom" in data["exc_info"]
        assert data["stack_info"] == "Stack (most recent call last):\n  frame"

    def test_extra_fields(self) -> None:
        class Thing:
            def __str__(self) -> str:
                return "a-thing"

        rec = _record(machine="metal-mill", count=3, thing=Thing())
        data = json.loads(JsonFormatter().format(rec))
        assert data["machine"] == "metal-mill"
        assert data["count"] == 3
        assert data["thing"] == "a-thing"

    def test_extra_cannot_override_fixed_fields(self) -> None:
        logger = logging.getLogger("test_json_extra_override")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
        try:
            logger.warning("msg", extra={"level": "FAKE", "timestamp": "x"})
        finally:
            logger.removeHandler(handler)
        data = json.loads(stream.getvalue())
        assert data["level"] == "WARNING"
        assert data["timestamp"] != "x"

    def test_record_already_formatted_by_text_handler(self) -> None:
        rec = _record()
        logging.Formatter("%(asctime)s %(message)s").format(rec)
        data = json.loads(JsonFormatter().format(rec))
        assert "asctime" not in data
        assert data["message"] == "hello world"

    def test_special_characters_single_line(self) -> None:
        msg = 'quote " backslash \\ newline\nsecond ünïcødé ✓'
        line = JsonFormatter().format(_record(msg=msg, args=()))
        assert "\n" not in line
        assert json.loads(line)["message"] == msg

    def test_location(self) -> None:
        rec = _record()
        assert "filename" not in json.loads(JsonFormatter().format(rec))
        data = json.loads(JsonFormatter(include_location=True).format(rec))
        assert data["filename"] == "mod.py"
        assert data["lineno"] == 42
        assert data["funcName"] == "myfunc"


class TestConfigureLogFormat:

    @pytest.fixture
    def lgr(self) -> Generator[logging.Logger, None, None]:
        orig_fmt = default_handler.formatter
        lgr = logging.getLogger("test_configure_log_format")
        other = logging.StreamHandler(io.StringIO())
        lgr.addHandler(other)
        lgr.addHandler(default_handler)
        yield lgr
        for h in list(lgr.handlers):
            lgr.removeHandler(h)
        default_handler.setFormatter(orig_fmt)

    @pytest.mark.parametrize("value", ["json", "JSON", " Json \n"])
    def test_json(self, lgr: logging.Logger, value: str) -> None:
        with patch.dict("os.environ", {"LOG_FORMAT": value}):
            configure_log_format(lgr, False)
        assert lgr.handlers == [default_handler]
        assert isinstance(default_handler.formatter, JsonFormatter)
        assert default_handler.formatter.include_location is False

    def test_json_verbose(self, lgr: logging.Logger) -> None:
        with patch.dict("os.environ", {"LOG_FORMAT": "json"}):
            configure_log_format(lgr, True)
        assert isinstance(default_handler.formatter, JsonFormatter)
        assert default_handler.formatter.include_location is True

    def test_json_adds_default_handler_if_missing(self) -> None:
        orig_fmt = default_handler.formatter
        lgr = logging.getLogger("test_configure_log_format_missing")
        lgr.addHandler(logging.StreamHandler(io.StringIO()))
        try:
            with patch.dict("os.environ", {"LOG_FORMAT": "json"}):
                configure_log_format(lgr, False)
            assert lgr.handlers == [default_handler]
        finally:
            for h in list(lgr.handlers):
                lgr.removeHandler(h)
            default_handler.setFormatter(orig_fmt)

    @pytest.mark.parametrize("env", [{}, {"LOG_FORMAT": ""}, {"LOG_FORMAT": "Text"}])
    def test_text_unchanged(self, lgr: logging.Logger, env: Dict[str, str]) -> None:
        handlers = list(lgr.handlers)
        fmt = default_handler.formatter
        with patch.dict("os.environ", env, clear=False):
            if not env:
                os.environ.pop("LOG_FORMAT", None)
            configure_log_format(lgr, False)
        assert lgr.handlers == handlers
        assert default_handler.formatter is fmt

    def test_invalid_value(
        self, lgr: logging.Logger, caplog: pytest.LogCaptureFixture
    ) -> None:
        handlers = list(lgr.handlers)
        fmt = default_handler.formatter
        with patch.dict("os.environ", {"LOG_FORMAT": "yaml"}):
            with caplog.at_level(logging.WARNING, logger=lgr.name):
                configure_log_format(lgr, False)
        assert lgr.handlers == handlers
        assert default_handler.formatter is fmt
        assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
            (logging.WARNING, "Unknown LOG_FORMAT 'yaml'; using text")
        ]
