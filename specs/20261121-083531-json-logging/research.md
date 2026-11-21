# Research: JSON (Structured) Logging

## R1. Formatter implementation

- **Decision**: Subclass `logging.Formatter` and build a dict, serialized with
  `json.dumps(obj, default=str, ensure_ascii=False)`.
- **Rationale**: This is the pattern in the Python logging cookbook's "structured logging"
  section referenced by the issue. `json.dumps` escapes newlines, so each record is one
  line. `default=str` renders non-serializable `extra` values instead of failing.
- **Alternatives**: `python-json-logger` (new dependency for ~40 lines of code; rejected
  under constitution III). Wrapping the message in a `StructuredMessage` per call site
  (cookbook variant): requires touching every log call; rejected.

## R2. Current handler topology (observed)

Running `mac-server` today shows every record printed **twice**: root has the
`logging.basicConfig()` handler (`handlers[0]`, format set by `set_log_info`) *and*
Quart's `default_handler` (with `RequestFormatter`). Quart's app logger (`dm_mac`, which
also receives the hypercorn access log) has no handler of its own and propagates to root.

- **Decision**: Do not change text mode (spec SC-002). In JSON mode, remove every root
  handler except `default_handler` and give `default_handler` the `JsonFormatter`, so each
  record is emitted exactly once and every line is JSON.
- **Rationale**: Setting the JSON formatter on both handlers would emit duplicate JSON
  lines; leaving the basicConfig handler would mix text lines into the JSON stream
  (violates SC-001).
- **Follow-up (out of scope)**: the text-mode duplication is a pre-existing bug worth a
  separate issue.

## R3. Selection mechanism

- **Decision**: `LOG_FORMAT` env var, case-insensitive, `text` (default) or `json`;
  surrounding whitespace ignored. Anything else: stay on text and log a WARNING naming the
  value.
- **Rationale**: All server options are env vars; Docker deployments set env easily.
  Falling back rather than exiting keeps a typo from taking machines offline.
- **Alternatives**: CLI flag (inconsistent with other config); exit on invalid value
  (rejected: availability over strictness for a safety system).

## R4. Timestamp

- **Decision**: `datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds")`,
  e.g. `2026-11-21T08:37:18.461-05:00`.
- **Rationale**: ISO 8601 with offset is unambiguous for aggregators; millisecond precision
  matches the current text format.

## R5. Extra fields

- **Decision**: Include any `record.__dict__` key not in the set of standard `LogRecord`
  attributes (derived from `logging.LogRecord(...).__dict__` plus `message`, `asctime`,
  `taskName`) and not already one of our output keys (`url`, `remote_addr` are always
  computed by the formatter itself).
- **Rationale**: Deriving the standard set from a real `LogRecord` stays correct across
  Python versions.

## R6. Access log request context

The hypercorn access log is emitted after the request context is gone, so `remote_addr`
and `url` are `null` there (same as `[None]` in today's text output). The client address
and request line are already in its message. No change.
