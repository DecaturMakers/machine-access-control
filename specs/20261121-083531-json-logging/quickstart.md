# Quickstart: JSON logging

```bash
LOG_FORMAT=json poetry run mac-server            # JSON, INFO and above
LOG_FORMAT=json poetry run mac-server --verbose  # JSON, DEBUG, with file/line/function
poetry run mac-server                            # unchanged text output
```

Docker: add `-e LOG_FORMAT=json` (or `environment: LOG_FORMAT: json` in compose).

Verify every line is JSON:

```bash
LOG_FORMAT=json poetry run mac-server 2>&1 >/dev/null | head -5 | python -m json.tool --json-lines
```

Filter authorization decisions with `jq`: `jq 'select(.logger == "AUTH")'`.
