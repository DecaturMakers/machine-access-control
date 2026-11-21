# Tasks: JSON (Structured) Logging

**Input**: Design documents from `specs/20261121-083531-json-logging/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/log-record.md

**Tests**: Included; constitution principle II requires tests for all new server logic.

## Phase 1: Setup

No setup needed: no new dependencies or files beyond those below.

## Phase 2: Foundational

- [X] T001 Add `JsonFormatter(logging.Formatter)` to `src/dm_mac/__init__.py` next to `RequestFormatter`: `__init__(self, include_location: bool = False)`; `format()` builds a dict with `timestamp` (local ISO 8601, ms, with offset), `level`, `logger`, `message` (`record.getMessage()`), `remote_addr` and `url` (from Quart request context, else `None`); adds `exc_info` via `formatException` when `record.exc_info`, `stack_info` via `formatStack` when set; adds `filename`/`lineno`/`funcName` when `include_location`; adds extra keys from `record.__dict__` not in the standard-attribute set (derived from a real `LogRecord` plus `message`, `asctime`, `taskName`) and not already in the dict; returns `json.dumps(d, default=str, ensure_ascii=False)`

## Phase 3: User Story 1 - Machine-parseable server logs (P1) 🎯 MVP

**Goal**: `LOG_FORMAT=json` makes every server log line a single JSON object.
**Independent Test**: tests below, plus running the server with `LOG_FORMAT=json` and parsing every stderr line with `json.loads`.

- [X] T002 [US1] Add `configure_log_format(lgr: logging.Logger, verbose: bool) -> None` to `src/dm_mac/__init__.py`: reads `LOG_FORMAT` (strip, lowercase; empty/`text` → return unchanged); `json` → remove every handler on `lgr` except `default_handler` and set `JsonFormatter(include_location=verbose)` on `default_handler`; other values → `lgr.warning("Unknown LOG_FORMAT %r; using text", raw)`
- [X] T003 [US1] Call `configure_log_format(logger, args.verbose)` in `main()` in `src/dm_mac/__init__.py` after `set_log_debug`/`set_log_info`
- [X] T004 [P] [US1] Tests for `JsonFormatter` in `tests/test_init.py`: required fields and types, ISO timestamp with offset, `%`-args interpolated, null request fields outside a request, populated `remote_addr`/`url` inside `app.test_request_context()`, `exc_info` traceback string, `stack_info`, extra fields including a non-serializable object rendered via `str`, extras cannot override fixed fields, newline/quote/non-ASCII message stays one line and round-trips
- [X] T005 [US1] Tests for `configure_log_format` in `tests/test_init.py` using a throwaway logger with a plain `StreamHandler` plus `default_handler` (restore `default_handler`'s formatter afterwards): `json` leaves only `default_handler` with a `JsonFormatter`; case-insensitive and whitespace-tolerant
- [X] T006 [US1] Update existing `TestMain` tests in `tests/test_init.py` to patch `configure_log_format` and assert it is called with `(logger, verbose)`

## Phase 4: User Story 2 - Existing deployments unchanged (P1)

**Goal**: no output change unless `LOG_FORMAT=json`; bad values warn and keep text.
**Independent Test**: tests below.

- [X] T007 [US2] Tests in `tests/test_init.py`: unset, empty and `text` leave handlers and formatters untouched (same objects); an invalid value leaves them untouched and logs one WARNING naming the value

## Phase 5: User Story 3 - Verbose detail in JSON (P2)

**Goal**: verbose + JSON includes source location.
**Independent Test**: test below.

- [X] T008 [US3] Test in `tests/test_init.py`: `JsonFormatter(include_location=True)` output includes `filename`, `lineno`, `funcName`; default excludes them; `configure_log_format(lgr, verbose=True)` installs a location-including formatter

## Phase 6: Polish

- [X] T009 [P] Document `LOG_FORMAT` in the env var table and add a "JSON Logging" section with the field list and an example in `docs/source/configuration.rst`
- [X] T010 [P] Add `LOG_FORMAT` to "Optional for MAC server" env vars and a short "JSON logging" note in the Logging section of `CLAUDE.md`
- [X] T011 Run `nox -s tests`, `nox -s mypy`, `nox -s pre-commit`; fix failures
- [X] T012 Run `mac-server` with `LOG_FORMAT=json` against fixture configs, issue a request, verify every stderr line parses as JSON and no duplicates; run without it and confirm text output unchanged

## Dependencies

T001 → T002 → T003. Tests T004 needs T001; T005–T008 need T002. US2 and US3 depend only on Foundational + T002. Polish after all stories.

## Parallel Examples

- T004 can be written alongside T002/T003.
- T009 and T010 are independent docs files.

## Implementation Strategy

MVP is US1 (T001–T006). US2 is guarded by tests only, since text mode is untouched by design. US3 is a flag on the same formatter.
