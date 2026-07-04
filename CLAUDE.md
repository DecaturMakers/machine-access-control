# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is **Decatur Makers Machine Access Control (dm-mac)**: a software and hardware project for using RFID cards/fobs to control access to power tools and equipment in the Decatur Makers makerspace. The system consists of:

1. **Central Control Server**: Python/Quart (async Flask) application that handles authentication/authorization, machine control, and logging
2. **Machine Control Units (MCUs)**: ESP32-based hardware running ESPHome that communicate with the server

The system integrates with NeonOne CRM for user data (optional and pluggable).

## Development Commands

### Environment Setup
```bash
# Install dependencies
poetry install

# Activate virtualenv (if needed)
poetry shell

# Install pre-commit hooks
nox -s pre-commit -- install
```

### Testing
```bash
# Run all tests with coverage
nox -s tests

# Run a single test file
nox -s tests -- tests/test_utils.py

# Run a specific test
nox -s tests -- tests/test_utils.py::test_specific_function

# Run tests with typeguard runtime type checking
nox -s typeguard
```

### Code Quality
```bash
# Run all linting/formatting checks
nox -s pre-commit

# Run type checking
nox -s mypy

# Run security checks
nox -s safety

# Check coverage report
nox -s coverage -- report
nox -s coverage -- html  # generates htmlcov/index.html
```

### Documentation
```bash
# Build docs
nox -s docs

# Build docs with auto-rebuild and browser
DOCS_REBUILD=true nox -s docs
```

### Running the Server
```bash
# Run the MAC server (default port 5000)
poetry run mac-server

# Run with debug mode
poetry run mac-server --debug

# Run with verbose logging
poetry run mac-server --verbose

# Run on custom port
poetry run mac-server --port 8080
```

### NeonGetter Tool
```bash
# Update users.json from NeonOne CRM
poetry run neongetter

# Interactively add RFID fobs to Neon accounts
poetry run neon-fob-adder 123 456 789
poetry run neon-fob-adder --csv members.csv --field account_id
```

Both tools use the same environment variables: ``NEON_ORG``, ``NEON_KEY``, and ``NEONGETTER_CONFIG``.

### Releasing
Releases are automated and driven by the version in `pyproject.toml` — do **not** create or push git tags manually.

```bash
# Bump the version (minor shown; use major/patch as appropriate), then commit and merge to main
poetry version minor
```

On every push to `main`, `.github/workflows/release.yml` compares the `pyproject.toml` version against the latest GitHub release. If it is higher, the workflow automatically creates the git tag (bare version, e.g. `0.14.0` — no `v` prefix), builds and pushes the Docker image to GHCR, publishes to PyPI, and creates a GitHub release with generated notes. If the version is unchanged, the workflow no-ops.

## Architecture

### Core Components

**Application Factory Pattern**: The Quart app is created via `create_app()` in `src/dm_mac/__init__.py`. The app configuration includes:
- `MACHINES`: MachinesConfig instance managing all machine configurations
- `USERS`: UsersConfig instance managing all user data
- `SLACK_HANDLER`: Optional SlackHandler for Slack integration
- `WEBHOOK_NOTIFIER`: Optional WebhookNotifier (see Status-Change Webhook below); `None` unless `STATUS_WEBHOOK_URL` is set
- `START_TIME`: Server start timestamp for uptime tracking

**Configuration System**:
- Machines: `machines.json` (schema in `models/machine.py::CONFIG_SCHEMA`)
  - `authorizations_or`: List of authorizations, any one sufficient to operate
  - `unauthorized_warn_only`: (optional) Allow operation but log warning for unauthorized users
  - `always_enabled`: (optional) Machine always enabled without RFID authentication, displays "Always On"
  - `alias`: (optional) Human-friendly name used in Slack messages and logs instead of machine name
  - `second_relay`: (optional) Object configuring an additional output relay (V1 hardware GPIO14 / connector pin 6) gated on a separate authorization. The second relay only energizes when the primary relay is energized AND the operator additionally satisfies these settings:
    - `authorizations_or`: (required) List of authorizations, any one of which is sufficient to energize the second relay
    - `unauthorized_warn_only`: (optional) Energize the second relay even for primary-authorized operators lacking secondary auth, with a warning logged + Slacked
    - `always_enabled`: (optional) Second relay tracks the primary relay's state regardless of secondary auth
    - `alias`: (optional) Human-readable name for the accessory (used in Slack/log lines that refer specifically to the second relay)
- Users: `users.json` (schema in `models/users.py::CONFIG_SCHEMA`)
- Machine names must match ESPHome configs and can only contain `[a-z0-9_-]`
- Machines can be looked up by either name or alias (case-insensitively) in Slack commands (both at-mentions and the `/oops-clear` slash command)

**State Persistence**:
- Machine state is persisted to disk on every update using pickle
- Default location: `./machine_state/` (configurable via `MACHINE_STATE_DIR` env var)
- File locking via `filelock` ensures thread-safe state updates
- Enables server restarts without affecting running machines
- Each persistence write is bounded by `STATE_SAVE_TIMEOUT_SEC` (2.0 s) via
  `MachineState.save_cache()`. If a write exceeds the budget the request
  handler returns HTTP 503 to the MCU so the firmware sees a clean error
  instead of a slow-but-200 response. `save_cache()` is single-flight per
  machine: only one worker *thread* runs at a time. Concurrent callers
  *join* the in-flight task (each waits up to `STATE_SAVE_TIMEOUT_SEC`
  for it to complete) instead of spawning a second thread that would
  also block on the same disk, so a stuck disk cannot exhaust the
  thread pool. Brief overlap between requests succeeds without
  counting; only callers whose own wait actually exceeds the budget
  count as timeouts. Lifetime per-machine timeouts are exposed as the
  `mac_state_save_timeouts_total` Prometheus counter. Two independent
  Slack notifications cover different failure shapes (both post to
  `SLACK_CONTROL_CHANNEL_ID`):

  1. **Per-machine** ("this machine is repeatedly slow"): fires
     exactly once on the transition to 2 lifetime timeouts for one
     machine. Suppresses single transient stalls.
  2. **Fleet-wide** ("the disk is hung"): fires when at least
     `FLEET_TIMEOUT_THRESHOLD` (default 2) *distinct* machines record
     timeouts within `FLEET_TIMEOUT_WINDOW_SEC` (default 60 s), with
     `FLEET_TIMEOUT_COOLDOWN_SEC` (default 300 s) between consecutive
     fires. This catches the 2026-05-11 pattern in which every
     machine's per-machine counter goes 0→1 simultaneously and the
     per-machine rule above never trips. Implemented by
     `FleetTimeoutTracker` (one instance per app, in
     `current_app.config["FLEET_TIMEOUT_TRACKER"]`).

### Request Flow

1. **MCU Update Request**: ESP32 POSTs to `/machine/update` with current state (RFID value, oops button, uptime, WiFi signal, temperature, optional amperage)
2. **Authentication**: Server looks up user by RFID fob code (zero-padded to 10 chars)
3. **Authorization**: Checks if user has any of the required authorizations from `machines.json::authorizations_or` list
4. **State Update**: Updates machine state, persists to disk, optionally logs to Slack
5. **Response**: Returns JSON with desired MCU outputs (relay state, LCD text, LED colors)

### Key Models

**Machine** (`models/machine.py`):
- `name`: Unique machine identifier
- `authorizations_or`: List of authorizations, any one sufficient to operate
- `unauthorized_warn_only`: If true, log warning but allow operation for unauthorized users
- `state`: MachineState instance tracking current operator, session timing, lockout status

**User** (`models/users.py`):
- `fob_codes`: List of RFID fob codes (10-digit strings)
- `account_id`: Unique account identifier
- `authorizations`: List of training/authorization field names
- `expiration_ymd`: Membership expiration in YYYY-MM-DD format

### API Endpoints

**Machine APIs** (mounted under the `/api` blueprint, so externally served
as `/api/machine/*`):
- `POST /api/machine/update`: Main endpoint for MCU state updates. Returns
  503 with `{"error": "state save timeout"}` if persisting the resulting
  state exceeds `STATE_SAVE_TIMEOUT_SEC`.
- `POST /api/machine/oops/<machine_name>`: Set the machine into Oops
  (maintenance-needed) state. `DELETE` on the same path clears it.
- `POST /api/machine/locked_out/<machine_name>`: Lock out a machine.
  `DELETE` on the same path unlocks it.

**Admin APIs** (`/api/*`):
- `POST /api/reload-users`: Hot-reload users.json without restart
- `GET /api/machines`: List all machines and their current status as JSON
  (sorted by name). Read-only; intended for external consumers such as the
  Equipment Status Board. Each entry is `Machine.status_dict` (name,
  display_name, derived `status`, relay, oops, locked_out, current_user,
  last_checkin, last_update).
- `GET /metrics`: Prometheus metrics endpoint

### Status-Change Webhook

When `STATUS_WEBHOOK_URL` is set, `WebhookNotifier` (`src/dm_mac/webhook.py`)
POSTs a JSON webhook to that URL on every *meaningful* machine status change —
never on ordinary MCU heartbeats. Events: `login`, `logout`, `unauthorized`,
`unknown_fob`, `override_login`, `oops`, `unoops`, `lockout`, `unlock`,
`reboot`. The payload is `Machine.status_dict` plus `event`, `timestamp`, and a
distinct `user` field (the event actor, e.g. who logged out — differs from
`current_user`). Delivery is fire-and-forget (an `asyncio` task, like the Slack
notifications) with a per-attempt timeout and bounded exponential-backoff
retry, so the MCU response is never blocked; failures are logged and dropped.
`notify()` is called only from the meaningful status-change code paths in
`models/machine.py`, so heartbeats never fire it. The notifier is resolved via
`current_app` in request-context (MCU/API) paths and via the passed Slack
handler's app (`slack.quart`) in the Slack-command path, which runs without a
request context.

### Logging

Custom `RequestFormatter` adds request context (`remote_addr`, `url`) to all logs when available. The `AUTH` logger is used specifically for authentication/authorization decisions.

## Environment Variables

Required for NeonGetter:
- `NEON_ORG`: NeonOne organization name
- `NEON_KEY`: NeonOne API key
- `NEONGETTER_CONFIG`: Path to neon config JSON

Optional for MAC server:
- `USERS_CONFIG`: Path to users.json (default: `./users.json`)
- `MACHINES_CONFIG`: Path to machines.json (default: `./machines.json`)
- `MACHINE_STATE_DIR`: State persistence directory (default: `./machine_state`)
- `SLACK_BOT_TOKEN`: Slack Bot User OAuth Token
- `SLACK_APP_TOKEN`: Slack Socket OAuth Token
- `SLACK_SIGNING_SECRET`: Slack Signing Secret
- `SLACK_CONTROL_CHANNEL_ID`: Private admin channel ID
- `SLACK_OOPS_CHANNEL_ID`: Public channel for oops/maintenance notices
- `STATUS_WEBHOOK_URL`: If set, URL to POST status-change webhooks to (see Status-Change Webhook above); disabled when unset

## Testing Notes

- Tests use fixtures in `tests/fixtures/` for config files
- Test environment variables are set in `noxfile.py::TEST_ENV`
- Async tests use `pytest-asyncio` with `--asyncio-mode=auto`
- Network blocking enforced via `pytest-blockage` to prevent accidental external calls
- Coverage threshold: 5% (intentionally low for early-stage project)

## Important Implementation Details

- RFID values from ESPHome have leading zeroes stripped; the server left-pads to 10 characters
- Machine state updates use both in-memory caching and disk persistence
- All machine state operations are protected by file locks to prevent race conditions
- The server uses asyncio event loop with custom exception handler
- Slack integration uses Socket Mode (bidirectional WebSocket)
- Machines can be configured with `unauthorized_warn_only: true` for training/soft-enforcement mode

## Feature Development

We have a special process for developing features. When asked to begin work on a feature, you MUST read and understand all of `docs/features/README.md` which outlines our feature development process. Once you have read and understood that document, ask the user which of the `docs/features/*.md` Features they want to begin work on; once one is chosen, begin work on the feature development process.

## Active Technologies
- Python 3.12 + Quart (async Flask), slack-bolt, prometheus-client, jsonschema, filelock, humanize (001-oops-override)
- JSON config files (users.json, machines.json), pickle state files with file locking (001-oops-override)
- Python 3.12 + Quart (async Flask), slack-bolt, prometheus-client, jsonschema, filelock, humanize, pydantic (existing) (002-second-relay-support)
- JSON config files (`machines.json`, `users.json`); per-machine pickle state under `MACHINE_STATE_DIR` (default `./machine_state/`) protected by `filelock` (002-second-relay-support)

## Recent Changes
- 001-oops-override: Added Python 3.12 + Quart (async Flask), slack-bolt, prometheus-client, jsonschema, filelock, humanize

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
