# Feature Template

You must read, understand, and follow all instructions in `./README.md` when planning and implementing this feature.

## Overview

Goal: implement the required minimal changes in this application to support https://github.com/DecaturMakers/equipment-status-board/issues/10.

At a high level, this means:

1. If we don't already have one, a simple API for retrieving a list of all machines and their current status.
2. Ability to fire a webhook (non-blocking/async or from a background worker) when a machine's status is changed (user login/logout, unauthorized RFID fob, oops/lockout/clear), using a webhook destination configured via environment variable. The webhook should include information on the currently-logged-in user if there is one. This should only fire on meaningful status changes, not on every update from the MCU.
3. If we don't already have them, API endpoints to oops a machine, put it in maintenance lockout, or clear oops/lockout.

Our approach is to minimize change in this application, and let ESB do the heavy lifting; we just need to send events to it via webhook and give it the appropriate API endpoints to call.

## Implementation Plan

Commit-message prefix for this feature: ``ESB Support - {Milestone}.{Task}``.

### Findings / Scope

Mapping the three high-level requirements onto the current codebase:

1. **Machine list/status API** — *does not exist as JSON.* Today status is only
   available via the Prometheus ``/metrics`` endpoint and the Slack ``status``
   command. We will add a small read-only JSON endpoint.
2. **Status-change webhook** — *does not exist.* The meaningful status changes
   already have well-defined chokepoints in ``models/machine.py`` where Slack
   notifications fire (login, logout, unauthorized/unknown fob, override login,
   oops, un-oops, lockout, unlock, reboot). We will fire the webhook from those
   same sites so it only fires on meaningful changes, never on ordinary MCU
   heartbeats.
3. **Oops / lockout / clear API endpoints** — *already exist* in
   ``views/machine.py``: ``POST``/``DELETE /api/machine/oops/<name>`` and
   ``POST``/``DELETE /api/machine/locked_out/<name>``. ESB "clear" = ``DELETE``
   on whichever of the two is set. No new control endpoints are required; we
   only verify and document them.

The ESB issue also mentions storing 100–500 recent activity events per machine.
Per the "let ESB do the heavy lifting" directive, **ESB stores that history from
the webhook events**; MAC does not add history storage.

### Design Decisions (confirmed with maintainer)

* **Webhook destination:** ``STATUS_WEBHOOK_URL`` environment variable. When
  unset, webhook firing is disabled entirely (mirrors how Slack is disabled
  without its tokens).
* **Authentication:** none. The POST is sent with no auth header.
* **Delivery:** fire-and-forget (``asyncio.create_task``, like Slack) so the MCU
  response is never blocked, with a bounded **retry-with-backoff** in the
  background task and a per-attempt timeout. Failures are logged after retries
  are exhausted; ESB can reconcile via the status API.

### Shared status representation

A single ``status_dict`` (and derived ``status`` string) will be used by **both**
the list API and the webhook payload so they never drift:

```json
{
  "name": "planer",
  "display_name": "Planer",
  "status": "in_use",          // one of: idle | in_use | oops | locked_out | unknown
  "relay": true,
  "oops": false,
  "locked_out": false,
  "current_user": { "account_id": "123", "full_name": "Jane Doe" },  // or null
  "last_checkin": 1720000000.0,  // epoch seconds, or null if never
  "last_update": 1720000000.0    // epoch seconds, or null if never
}
```

The webhook payload is this dict plus an ``event`` field and a firing
``timestamp``. Event values: ``login``, ``logout``, ``unauthorized``,
``unknown_fob``, ``override_login``, ``oops``, ``unoops``, ``lockout``,
``unlock``, ``reboot``.

### Milestone 1 — ESB-facing status & control API — ✅ COMPLETE

Added ``Machine.status`` and ``Machine.status_dict`` (shared representation),
the ``GET /api/machines`` endpoint with ``MachineStatus`` / ``MachinesListResponse``
schemas, and unit tests for both the model properties and the endpoint. Verified
the existing oops/lockout endpoints already satisfy requirement #3 and are
well-covered (no code change needed). All ``nox -s tests`` pass at 97% coverage.

* **1.1** Add a ``status`` property (derived string) and a ``status_dict``
  property on ``Machine`` (reading ``self.state``), producing the shared
  representation above. ``current_user`` serializes to ``{account_id, full_name}``
  or ``null``.
* **1.2** Add ``GET /api/machines`` returning ``{"machines": [status_dict, ...]}``
  for all configured machines, sorted by name. Add ``pydantic`` response schemas
  in ``models/api_schemas.py`` and document the route with ``quart_schema``
  (tagged ``Admin``). Read-only and unauthenticated, consistent with the existing
  API surface.
* **1.3** Confirm the existing oops/lockout endpoints satisfy ESB's control
  needs; add any missing test coverage. No behavior change expected.
* **1.4** Unit tests for ``status``/``status_dict`` and the new endpoint
  (idle/in-use/oops/locked-out, with and without a current user).

### Milestone 2 — Status-change webhook — ✅ COMPLETE

Added ``src/dm_mac/webhook.py`` (``WebhookNotifier``: fire-and-forget delivery
via ``aiohttp`` with bounded exponential-backoff retry, enabled by
``STATUS_WEBHOOK_URL``), wired it into ``create_app`` as ``WEBHOOK_NOTIFIER``,
and fired ``notify(...)`` from the meaningful status-change sites in
``models/machine.py`` (login / logout / unauthorized / unknown_fob /
override_login / oops / unoops / lockout / unlock / reboot), including the
always-enabled RFID-tracking path. The notifier is resolved via
``current_app`` in the request-context (MCU/API) paths and via the passed
Slack handler's app (``slack.quart``) in the Slack-command path, which runs
without a request context. Payloads reuse ``Machine.status_dict`` plus
``event``, ``timestamp``, and a distinct ``user`` (event actor) field. Unit
tests cover the notifier (payload/retry/backoff/disabled) and the wiring
(each event fires; heartbeats do not; Slack path; disabled no-op). All
``nox -s tests`` and ``nox -s mypy`` pass; ``webhook.py`` at 100% coverage.

* **2.1** New module ``src/dm_mac/webhook.py`` with a ``WebhookNotifier`` class:
  * Constructed from ``STATUS_WEBHOOK_URL``.
  * ``notify(machine, event, user=None)`` builds the payload from
    ``machine.status_dict`` + ``event`` + ``timestamp`` and spawns a
    fire-and-forget ``asyncio.create_task`` delivery coroutine.
  * Delivery coroutine POSTs JSON via ``aiohttp`` (already a dependency) with a
    per-attempt timeout and retry-with-backoff (a small, bounded number of
    attempts with exponential backoff); logs a single error after exhaustion.
* **2.2** In ``create_app``/``main`` (``__init__.py``), instantiate the notifier
  when ``STATUS_WEBHOOK_URL`` is set and store it as
  ``app.config["WEBHOOK_NOTIFIER"]`` (default ``None``), exactly like
  ``SLACK_HANDLER``.
* **2.3** Fire ``notify(...)`` from the same async sites that emit Slack
  messages, so webhooks track meaningful changes only:
  * ``MachineState._handle_rfid_insert`` → ``login`` / ``unauthorized`` /
    ``unknown_fob`` / ``override_login``
  * ``MachineState._handle_rfid_remove`` → ``logout``
  * ``MachineState._handle_reboot`` → ``reboot`` (and logout of any prior user)
  * ``Machine.oops`` / ``MachineState._handle_oops`` → ``oops``
  * ``Machine.unoops`` → ``unoops``; ``Machine.lockout`` → ``lockout``;
    ``Machine.unlock`` → ``unlock``
  Each site fetches the notifier via ``current_app.config.get("WEBHOOK_NOTIFIER")``
  and no-ops when ``None``.
* **2.4** Unit tests: payload shape per event, disabled-when-unset, retry/backoff
  on failure (mock ``aiohttp``), and non-firing on ordinary heartbeat updates.

### Milestone 3 — Acceptance Criteria — ✅ COMPLETE

Updated documentation (`docs/source/configuration.rst` env-var table;
`docs/source/http-api.rst` with the Machine Status API and Status-Change
Webhook sections; `CLAUDE.md` app-config, API endpoints, env vars, and a new
Status-Change Webhook subsection). `README.rst` is a pointer to the full docs
and needed no change. `GET /api/machines` is picked up automatically by the
generated OpenAPI spec, and `dm_mac.webhook` by `sphinx-apidoc`. New code has
unit-test coverage (`webhook.py` at 100%). All `nox` sessions pass: `tests`,
`mypy`, `pre-commit`, `typeguard`, `docs`, and `safety`.

Note: `nox -s safety` was failing on `main` due to a pre-existing transitive
`msgpack==1.2.0` advisory (GHSA-6v7p-g79w-8964), unrelated to this feature. To
satisfy the "all nox sessions passing" criterion, `msgpack ^1.2.1` was pinned
in `pyproject.toml`'s existing "secure versions of transitive dependencies"
block (same mechanism already used for urllib3/werkzeug/marshmallow).

* **3.1** Update documentation: ``README.md`` (env var + endpoints if listed),
  ``docs/source/configuration.rst`` (add ``STATUS_WEBHOOK_URL`` to the env-var
  table), ``docs/source/http-api.rst`` (document ``GET /api/machines`` and the
  webhook payload/events), and ``CLAUDE.md`` (env vars + architecture notes).
  Match the existing style and verbosity.
* **3.2** Ensure all new code has appropriate unit-test coverage.
* **3.3** All ``nox`` sessions pass (``tests``, ``mypy``, ``pre-commit``,
  ``safety``, ``typeguard``, ``docs``).
* **3.4** Move this file from ``docs/features/`` to ``docs/features/completed/``.
