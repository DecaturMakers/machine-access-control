# Contract: `LOG_FORMAT` and JSON log lines

## Configuration

| `LOG_FORMAT` value | Behaviour |
|--------------------|-----------|
| unset, empty, `text` (any case) | existing text format, unchanged |
| `json` (any case) | one JSON object per line, fields per `data-model.md` |
| anything else | text format, plus one WARNING: `Unknown LOG_FORMAT '<value>'; using text` |

## Example (normal mode)

```json
{"timestamp": "2026-11-21T08:37:21.462-05:00", "level": "INFO", "logger": "AUTH", "message": "...", "remote_addr": "10.0.0.5", "url": "http://mac/api/machine/update"}
```

## Example (verbose mode, with exception)

```json
{"timestamp": "...", "level": "ERROR", "logger": "dm_mac.models.machine", "message": "...", "remote_addr": null, "url": null, "filename": "machine.py", "lineno": 123, "funcName": "save_cache", "exc_info": "Traceback (most recent call last):\n ..."}
```
