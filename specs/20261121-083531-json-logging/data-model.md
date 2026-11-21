# Data Model: JSON Log Record

One JSON object per line on standard error.

| Field | Type | Presence | Source |
|-------|------|----------|--------|
| `timestamp` | string, ISO 8601 with offset, ms precision | always | `record.created` |
| `level` | string (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) | always | `record.levelname` |
| `logger` | string | always | `record.name` |
| `message` | string | always | `record.getMessage()` |
| `remote_addr` | string or null | always | Quart `request.remote_addr` if in request context |
| `url` | string or null | always | Quart `request.url` if in request context |
| `exc_info` | string (formatted traceback) | when record has exception info | `formatException()` |
| `stack_info` | string | when `stack_info=True` | `formatStack()` |
| `filename`, `lineno`, `funcName` | string, int, string | verbose mode only | record attributes |
| *extra keys* | any JSON value; non-serializable values as `str()` | when supplied via `extra=` | `record.__dict__` |

Validation rules: the line must parse with `json.loads` to a dict; no literal newlines.
Extra keys never override the fixed fields above.
