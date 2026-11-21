# Feature Specification: JSON (Structured) Logging

**Feature Branch**: `robot-army/issue-52-json-logging`
**Created**: 2026-11-21
**Status**: Draft
**Input**: User description: "GitHub issue #52 "JSON logging": Add JSON (structured) logging. References: https://docs.python.org/3/howto/logging-cookbook.html#implementing-structured-logging and https://stackoverflow.com/questions/50144628/python-logging-into-file-as-a-dictionary-or-json"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Machine-parseable server logs (Priority: P1)

An administrator runs the MAC server under a log aggregation stack (e.g. a container log
shipper feeding a log database). Today every log line is free-form text, so finding
"every authorization decision for machine X" or "every error in the last day" means
writing fragile regular expressions. The administrator turns on JSON logging with one
setting; from then on every line the server writes is a single, self-contained JSON object
with consistently named fields that the aggregator can index directly.

**Why this priority**: This is the entire feature. Without it nothing else matters.

**Independent Test**: Start the server with JSON logging enabled, exercise an MCU update
and an admin API call, and confirm every line written to the log stream parses as a JSON
object with the documented fields.

**Acceptance Scenarios**:

1. **Given** JSON logging is enabled, **When** the server logs any message (application,
   `AUTH` decision, library, or HTTP access log), **Then** the line is exactly one JSON
   object containing at least timestamp, level, logger name, and message.
2. **Given** JSON logging is enabled, **When** a message is logged while handling an HTTP
   request, **Then** the JSON object also contains the client's remote address and the
   request URL.
3. **Given** JSON logging is enabled, **When** an exception is logged with its traceback,
   **Then** the traceback is included as a field of the same JSON object, not as extra
   lines after it.
4. **Given** JSON logging is enabled, **When** a message contains quotes, newlines, or
   non-ASCII characters, **Then** the output is still one valid JSON object on one line.

---

### User Story 2 - Existing deployments are unchanged (Priority: P1)

An administrator who upgrades without changing any configuration sees exactly the same
human-readable text log format as before.

**Why this priority**: Constitution principle IV (backward compatibility); existing log
tooling and humans reading `docker logs` must not break on upgrade.

**Independent Test**: Start the server with no new configuration and confirm the log
output format is identical to the previous release, in both normal and verbose modes.

**Acceptance Scenarios**:

1. **Given** JSON logging is not configured, **When** the server logs, **Then** the
   output matches the existing text format.
2. **Given** JSON logging is configured with an unrecognized value, **When** the server
   starts, **Then** it uses the text format and logs a warning naming the invalid value,
   rather than refusing to start.

---

### User Story 3 - Verbose mode detail in JSON (Priority: P2)

When the server runs in verbose (debug) mode with JSON logging on, each JSON object also
carries the source location (file, line, function) that the verbose text format shows
today, so no debugging information is lost by switching formats.

**Why this priority**: Useful for troubleshooting, but not needed for routine operation.

**Independent Test**: Start in verbose mode with JSON logging and confirm debug-level
records appear and include source-location fields.

**Acceptance Scenarios**:

1. **Given** JSON logging and verbose mode, **When** a debug message is logged, **Then**
   the JSON object includes the source file name, line number, and function name.

---

### Edge Cases

- A log call passes structured context through the logging "extra" mechanism: those
  fields appear as top-level keys in the JSON object, and a value that cannot be
  represented in JSON is rendered as its string form rather than dropping the line.
- A message logged outside any HTTP request (startup, Slack socket handler, background
  tasks): remote address and URL are `null`.
- Logging must never raise into the caller; a formatting failure must not interrupt
  machine-control code paths (constitution principle I).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The MAC server MUST support a JSON log output format, selected by an
  optional configuration setting; the default MUST remain the existing text format.
- **FR-002**: In JSON mode, each log record MUST be written as exactly one JSON object
  on one line.
- **FR-003**: Each JSON object MUST include: timestamp (ISO 8601 with timezone offset),
  level name, logger name, and the fully formatted message.
- **FR-004**: When a record is emitted within an HTTP request, the object MUST include
  the remote address and request URL; otherwise these fields MUST be `null`.
- **FR-005**: When a record carries exception or stack information, it MUST be included
  as string fields of the same object.
- **FR-006**: Custom attributes supplied by the caller (logging "extra") MUST be included
  as top-level keys; non-JSON-serializable values MUST be rendered as strings.
- **FR-007**: In verbose mode, the object MUST additionally include source file name,
  line number, and function name.
- **FR-008**: JSON mode MUST apply to all records the server process emits through its
  log handler, including the `AUTH` logger, library loggers, and the HTTP access log.
- **FR-009**: An unrecognized format value MUST fall back to text and log a warning.
- **FR-010**: The setting MUST be documented with the other environment variables, along
  with the JSON field names.

### Key Entities

- **JSON log record**: one line of output; fields `timestamp`, `level`, `logger`,
  `message`, `remote_addr`, `url`, optional `exc_info`, `stack_info`, `filename`,
  `lineno`, `funcName`, plus any caller-supplied extra fields.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With JSON logging on, 100% of lines the server writes to its log stream
  during a test session parse as JSON objects.
- **SC-002**: With no configuration change, log output is byte-for-byte identical in
  format to the previous release.
- **SC-003**: An administrator can enable JSON logging by setting one environment
  variable, with no code or file changes.
- **SC-004**: An administrator can filter logs to all authorization decisions by a
  single field match (logger name `AUTH`) instead of a text pattern.

## Assumptions

- Scope is the `mac-server` process. The `neongetter` and `neon-fob-adder` command-line
  tools are run interactively by humans and keep their text output; they can be added
  later if needed.
- Logs continue to go to the same stream as today (standard error); no file output or
  log shipping is added.
- The setting is an environment variable, matching how all other server options are
  configured (and how the Docker image is run).
- No new third-party dependency is needed; the standard library's logging facilities are
  sufficient (constitution principle III).
