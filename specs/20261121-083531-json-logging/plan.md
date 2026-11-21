# Implementation Plan: JSON (Structured) Logging

**Branch**: `robot-army/issue-52-json-logging` | **Date**: 2026-11-21 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/20261121-083531-json-logging/spec.md`

## Summary

Add an opt-in JSON log format to `mac-server`, selected by a new `LOG_FORMAT`
environment variable (`text` default, `json`). A stdlib-only `JsonFormatter` in
`src/dm_mac/__init__.py` renders each record as one JSON line with timestamp, level,
logger, message, request context, exception/stack text, caller `extra` fields, and (in
verbose mode) source location. A `configure_log_format()` helper called from `main()`
applies it. Text mode is untouched.

## Technical Context

**Language/Version**: Python 3.13 (per `pyproject.toml`)
**Primary Dependencies**: stdlib `logging`, `json`, `datetime`; Quart (`has_request_context`, `request`, `quart.logging.default_handler`)
**Storage**: N/A
**Testing**: pytest + pytest-asyncio via `nox -s tests`
**Target Platform**: Linux server / Docker image
**Project Type**: web service (single project)
**Performance Goals**: no measurable change; one `json.dumps` per record
**Constraints**: must never raise into callers; text output unchanged when unset
**Scale/Scope**: one module changed, one env var, docs

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Assessment |
|-----------|------------|
| I. Safety & Reliability | No machine-control logic changes. Formatting errors are caught by `logging.Handler.emit` → `handleError` and never reach callers; `json.dumps(default=str)` prevents serialization errors. Invalid `LOG_FORMAT` falls back to text instead of failing startup. PASS |
| II. Testing Discipline | Unit tests for every field rule, request context, exceptions, extras, location, env selection and fallback. No network. PASS |
| III. Simplicity & YAGNI | Stdlib only, no new dependency (`python-json-logger` rejected). One formatter class, one function, one env var. CLI tools out of scope. PASS |
| IV. Backward Compatibility | Default is text and the text code path is not modified. No API, config file or pickle changes. PASS |
| V. Documentation | `LOG_FORMAT` and field list added to `docs/source/configuration.rst` and `CLAUDE.md`. PASS |
| Operational: Logging | `AUTH` logger and INFO-level state-change logging unchanged; JSON makes `AUTH` filterable by field. PASS |

Post-design re-check: unchanged, PASS. No complexity tracking entries.

## Project Structure

### Documentation (this feature)

`specs/20261121-083531-json-logging/`: `spec.md`, `plan.md`, `research.md`,
`data-model.md`, `contracts/log-record.md`, `quickstart.md`, `tasks.md`.

### Source Code (repository root)

- `src/dm_mac/__init__.py`: `JsonFormatter`, `configure_log_format()`, call from `main()`
- `tests/test_init.py`: new tests; patch `configure_log_format` in existing `main()` tests
- `docs/source/configuration.rst`, `CLAUDE.md`: env var + field docs

**Structure Decision**: Keep the formatter next to the existing `RequestFormatter` in
`src/dm_mac/__init__.py`, since both depend on Quart's request context and the module's
`default_handler` wiring. No new module.

## Complexity Tracking

None.
