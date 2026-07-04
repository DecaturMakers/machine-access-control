# MCU Heartbeat Resilience

## Feature Description

On 2026-05-05, four ESP32 MAC units (Bronte, Grizzly Metal Lathe, Metal
Mill, Resaw) all stopped checking in within 31 seconds of one another
after a server-side disk hang made one POST to `/api/machine/update`
take 30.6 seconds to return HTTP 200. The units stayed WiFi-associated
but did no application work for ~22h57m, until each was power-cycled.

The full root-cause analysis is in
[`docs/2026-05-05-mcu-lockup-analysis.md`](../2026-05-05-mcu-lockup-analysis.md).

This feature implements every recommendation from that analysis, in a
sequence that progressively raises the firmware's resilience to
slow/wedged servers without ever interrupting an in-progress
operation (e.g. a laser cut) except as a last-resort hardware
fallback.

## Goals

1. **Eliminate the trigger at the source.** The MAC server must never
   serve a slow-but-200 response: bound disk writes on
   `/api/machine/update` and return HTTP 503 if a write exceeds a
   small budget.
2. **Bound any single POST on the MCU to a few seconds**, so the main
   loop can never be blocked for >~8 seconds by a single request.
3. **Detect heartbeat liveness on the MCU** and reboot if heartbeats
   stop succeeding — but only when the relay is OFF, so an active cut
   is never interrupted.
4. **Provide a hardware-level last-resort fallback** (esp-idf task
   WDT with panic) for catastrophic hangs that no software watchdog
   can untangle.
5. **Improve maintainability** of the firmware by deduplicating the
   five copy-pasted `http_request.post` blocks in
   `esphome-configs/2025.11.2/no-current-input.yaml`.

## Non-Goals

- Changing the MCU↔server protocol or response format.
- Tightening `wifi.reboot_timeout` (the incident had healthy WiFi
  throughout).
- Re-enabling `api.reboot_timeout` (no Home Assistant in this
  deployment).
- Making the MCU recover *without* a reboot once wedged — once the
  http_request component is in the wedge state described in ESPHome
  issues #6677 / #2501, a reboot is the only known cure.

## Implementation Plan

### Overview

Five layers of defense, applied in priority order so each milestone
reduces risk monotonically:

| Layer | Where | Reboot risk to active cut |
|---|---|---|
| §7 disk-write timeout → 503 | server | none |
| §2 HTTP per-request timeout / watchdog_timeout | firmware | none |
| §4 `on_error` failure tracking (no reboot) | firmware | none |
| §5 dedupe POST blocks into a script | firmware | none |
| §1 liveness watchdog **gated on relay OFF** | firmware | none under normal operation |
| §3 esp-idf task WDT panic at 60 s | firmware | very rare; only on catastrophic hang |

Files to modify:

- `src/dm_mac/models/machine.py` (server-side: bound disk write time)
- `src/dm_mac/views/machine.py` (server-side: catch timeout, return 503)
- `esphome-configs/2025.11.2/no-current-input.yaml` (all firmware changes)
- `tests/models/test_machine.py` and `tests/views/test_machine.py` (server-side tests)
- Documentation: `CLAUDE.md`, `README.md`, `docs/source/` as needed

The firmware file is *not* part of the Python test suite. Validation
is by `esphome config no-current-input.yaml` (compile-check) and by
on-device live test (described in Milestone 6).

### Milestone 1: Server-Side Write Timeout (§7)

**Commit prefix:** `mcu-heartbeat - 1.1` through `mcu-heartbeat - 1.4`

The MAC server's `MachineState._save_cache()` writes a pickle file
inside a `filelock`. If the underlying disk hangs (filesystem-level
stall, full disk, bad SD card, etc.), the write can take tens of
seconds and the request to `/api/machine/update` returns 200 only
after the disk recovers. The MCU sees this as a successful but
extremely slow response, which is the worst-case shape for the
firmware (see analysis doc §3).

The server should bound the time spent writing state and surface
overruns to the MCU as HTTP 503 so the firmware sees a clean error
and recovers via the next 10 s heartbeat.

#### Task 1.1: Add `STATE_SAVE_TIMEOUT_SEC` constant and timeout-bounded save

- In `src/dm_mac/models/machine.py`, add module-level constant
  `STATE_SAVE_TIMEOUT_SEC = 2.0`.
- Refactor `_save_cache()` to run the pickle dump under
  `asyncio.wait_for(...)` (or run the synchronous body in a thread
  with `asyncio.to_thread()` and `asyncio.wait_for`). The current
  method is synchronous, so `MachineState.update()` (the async caller)
  will need to invoke it via `await asyncio.to_thread(...)` wrapped in
  `asyncio.wait_for`.
- On `asyncio.TimeoutError`, log at ERROR level with the machine name
  and re-raise a new exception class `StateSaveTimeoutError` so the
  view layer can distinguish.

#### Task 1.2: Plumb timeout into the view

- In `src/dm_mac/views/machine.py`, the `/machine/update` handler
  should catch `StateSaveTimeoutError` and return HTTP 503 with a JSON
  body like `{"error": "state save timeout"}`. No state mutations
  should be returned to the MCU on this path (i.e. don't claim the
  relay is on if we couldn't persist that fact).
- Add a Prometheus counter `mac_state_save_timeouts_total` (labeled by
  machine) so we can alert on this from monitoring.
- On the second and subsequent timeouts for a given machine (i.e.
  when the per-machine counter transitions from 1 → 2 or higher),
  send a Slack notification to `SLACK_CONTROL_CHANNEL_ID`. A single
  one-off timeout is logged + counted but does not page; repeated
  timeouts indicate a real disk problem.

#### Task 1.3: Unit tests for timeout path

- New tests in `tests/models/test_machine.py`:
  - `test_save_cache_timeout`: monkeypatch `pickle.dump` (or the
    `open()` call) to sleep longer than `STATE_SAVE_TIMEOUT_SEC`,
    assert `StateSaveTimeoutError` is raised.
  - `test_save_cache_succeeds_within_budget`: normal path completes
    well under the budget.
- New tests in `tests/views/test_machine.py`:
  - `test_update_returns_503_on_save_timeout`: simulate a save timeout
    and assert the response is HTTP 503 with the expected JSON body.
  - `test_update_returns_200_on_normal_save`: regression check that
    the happy path is unaffected.
- Ensure the Prometheus counter increments by exactly 1 per timeout.

#### Task 1.4: Documentation

- Update `CLAUDE.md` "State Persistence" section to mention the
  2 s save budget and 503 behavior on overrun.
- Add a brief note in `docs/source/` (or wherever the API behavior is
  documented) describing the new 503 response code.

**Milestone completion criteria:**

- All new tests pass.
- All previously-passing tests still pass.
- `nox -s tests`, `nox -s mypy`, `nox -s pre-commit` all pass.

### Milestone 2: Firmware HTTP Timeouts and Failure Tracking (§2 + §4 + §5)

**Commit prefix:** `mcu-heartbeat - 2.1` through `mcu-heartbeat - 2.4`

These three changes are bundled because they share data (the new
globals) and because §5 (deduplication) makes §2 and §4 trivially
applied in one place rather than five.

#### Task 2.1: Add globals for liveness state

In `esphome-configs/2025.11.2/no-current-input.yaml`, add to
`globals:`:

```yaml
- id: last_ok_post_uptime
  type: uint32_t
  restore_value: false
  initial_value: '0'
- id: consecutive_post_failures
  type: uint32_t
  restore_value: false
  initial_value: '0'
```

#### Task 2.2: Bound HTTP requests with timeout + watchdog_timeout

Update the `http_request:` block:

```yaml
http_request:
  timeout: 5s
  watchdog_timeout: 8s
```

`timeout` is the per-recv socket timeout (best-effort upper bound);
`watchdog_timeout` (esp-idf only) is what feeds the task WDT during
transfer and gives a true ceiling when paired with the WDT panic
config in Milestone 4.

#### Task 2.3: Deduplicate POST into a `script: mode: restart`

The same ~50-line POST/parse block is currently copy-pasted 5 times
(`interval`, `wifi.on_connect`, `card_present.on_release`,
`oops_button.on_press`, `wiegand.on_tag`).

- Add a `script:` named `post_to_mac` with `mode: restart` (so a fresh
  trigger preempts a stuck one rather than queuing).
- The script body contains the `http_request.post` with the JSON
  builder, `on_response` (parse JSON, drive relay/display/LEDs/second
  relay, **set `id(last_ok_post_uptime) = uptime` and reset
  `consecutive_post_failures = 0`**), and an `on_error` handler that
  increments `consecutive_post_failures` and logs at WARN.
- Replace each of the 5 inline `http_request.post` blocks with
  `- script.execute: post_to_mac`.
- The `on_error` handler must NOT call `App.safe_reboot()` directly —
  reboot logic lives in Milestone 3 and is gated on relay state.

#### Task 2.4: Compile-check the firmware

- Run `esphome config esphome-configs/2025.11.2/no-current-input.yaml`
  (locally, against ESPHome 2025.11.2) to confirm the YAML still
  compiles. Any secrets needed for compile-check should be stubbed in
  a `secrets.yaml` example included only locally — do **not** commit
  real secrets.
- If `esphome` is not installed locally, document the manual
  validation step for the human reviewer.

**Milestone completion criteria:**

- YAML compiles cleanly with `esphome config`.
- All five trigger sites use `script.execute: post_to_mac`.
- The script body has both `on_response` (success path) and
  `on_error` (failure path).
- All previously-passing Python tests still pass (these changes are
  firmware-only, so no regression expected).

### Milestone 3: Firmware Liveness Watchdog (Relay-State Gated) (§1)

**Commit prefix:** `mcu-heartbeat - 3.1`

#### Task 3.1: Add the watchdog interval

Add a new entry to `interval:` (alongside the existing 10 s heartbeat):

```yaml
- interval: 30s
  startup_delay: 120s
  then:
    - lambda: |-
        uint32_t now = (uint32_t) id(uptime_sensor).state;
        uint32_t last = id(last_ok_post_uptime);
        uint32_t stale = (last == 0) ? now : (now - last);
        bool relay_on = id(relay_output).state || id(relay2_output).state;
        if (stale > 90 && !relay_on) {
          ESP_LOGE("WDOG", "No successful POST in %us; relay off; rebooting", stale);
          App.safe_reboot();
        } else if (stale > 90 && relay_on) {
          ESP_LOGW("WDOG", "No successful POST in %us; relay ON; deferring reboot", stale);
          id(display_content) = "WARN: server\nlink stale";
          id(my_display).print(id(display_content));
        }
```

Notes:

- 90 s threshold = ~9 missed 10 s heartbeats. Tune in live testing.
- 120 s `startup_delay` keeps the watchdog from firing during boot
  before the first successful POST has had a chance to land.
- The check inspects **both** primary and second relay state — if
  either is energized, the machine is in an active operation and
  reboots are deferred.
- `App.safe_reboot()` (not `App.reboot()`) lets ESPHome teardown run
  cleanly first.

**Milestone completion criteria:**

- YAML compiles.
- Manual review confirms the relay-state gate is correct.
- All previously-passing Python tests still pass.

### Milestone 4: esp-idf Task Watchdog Panic (§3)

**Commit prefix:** `mcu-heartbeat - 4.1`

#### Task 4.1: Add sdkconfig overrides

In the `esp32:` block of
`esphome-configs/2025.11.2/no-current-input.yaml`:

```yaml
esp32:
  board: esp32dev
  framework:
    type: esp-idf
    sdkconfig_options:
      CONFIG_ESP_TASK_WDT_TIMEOUT_S: "60"
      CONFIG_ESP_TASK_WDT_EN: y
      CONFIG_ESP_TASK_WDT_INIT: y
      CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPU0: y
      CONFIG_ESP_TASK_WDT_CHECK_IDLE_TASK_CPU1: y
      CONFIG_ESP_TASK_WDT_PANIC: y
```

A 60 s timeout (vs. the 15 s in the original analysis) is deliberate:
the task WDT cannot inspect relay state, so any panic-reboot will
interrupt whatever the machine is doing. 60 s ensures this only
triggers on truly catastrophic hangs that the gated watchdog in
Milestone 3 cannot recover from.

**Milestone completion criteria:**

- YAML compiles.
- All previously-passing Python tests still pass.

### Milestone 5: Acceptance Criteria

**Commit prefix:** `mcu-heartbeat - 5.1` through `mcu-heartbeat - 5.4`

#### Task 5.1: Documentation

- Update `CLAUDE.md`:
  - Mention the new HTTP 503 response on `/api/machine/update` when
    state save exceeds the budget.
  - Note the new firmware liveness watchdog (90 s threshold, gated on
    relay state) in any section that describes MCU behavior.
- Update `README.md` if it documents the MCU/server protocol.
- Update `docs/source/` if relevant API or operational pages exist.

#### Task 5.2: Verify unit test coverage

- `nox -s coverage -- report` must show coverage for the new
  server-side timeout paths.
- Add tests if any new branches are uncovered.

#### Task 5.3: All nox sessions pass

- `nox -s tests` — 100% passing.
- `nox -s mypy` — clean.
- `nox -s pre-commit` — clean.
- `nox -s safety` — clean.

#### Task 5.4: Move feature file to `completed/`

- Move `docs/features/mcu-heartbeat-resilience.md` to
  `docs/features/completed/mcu-heartbeat-resilience.md`.
- Commit with `mcu-heartbeat - 5.4: feature complete`.

### Milestone 6: Live Rollout & Validation

**Commit prefix:** `mcu-heartbeat - 6.x` (only if hot-fixes needed)

This milestone is performed by the human operator after Milestones 1–5
land. No new code is expected; record outcomes in this document.

Order of operations:

1. **Deploy server-side fix (Milestone 1) to production first.**
   Verify the MAC server still serves normal requests. Confirm the
   `mac_state_save_timeouts_total` metric stays at zero under normal
   load (any non-zero count indicates a real disk problem worth
   investigating independently).
2. **Flash one MCU first (suggested: Bronte)** with the firmware
   changes from Milestones 2–4. Soak for at least 24 hours. Observe:
   - Heartbeats arrive every ~10 s with no gaps.
   - `last_ok_post_uptime` (visible in ESPHome logs at DEBUG) updates
     on every successful POST.
   - The watchdog interval logs no `WDOG` messages during normal
     operation.
3. **Induced-failure test on Bronte:**
   - With no card inserted (relay off), stop `mac-server`.
   - Confirm that within ~90–120 s the firmware logs a `WDOG` ERROR
     and reboots cleanly.
   - With a card inserted (relay on), stop `mac-server`.
   - Confirm that the firmware logs a `WDOG` WARN, displays
     `WARN: server\nlink stale` on the LCD, and does **not** reboot.
   - Restart `mac-server`. Confirm normal heartbeats resume without a
     reboot.
4. **Flash the remaining three units** (Grizzly Metal Lathe, Metal
   Mill, Resaw) once Bronte has 24+ hours of stable operation.
5. **Record outcomes** in this feature document under
   "Implementation Status" before moving the file to `completed/`.

**Milestone completion criteria:**

- All four units running the new firmware with stable heartbeats for
  >7 days.
- At least one induced-failure test (server stop) confirms the gated
  watchdog reboots when relay is off and defers when relay is on.
- No unexplained `WDOG` events in production.

## Resolved Decisions

1. **`STATE_SAVE_TIMEOUT_SEC = 2.0`** — confirmed; tunable later if
   needed.
2. **90 s firmware liveness threshold** — confirmed.
3. **Slack alert** — fire when
   `mac_state_save_timeouts_total > 1` for a given machine, so a
   single transient timeout does not page anyone. Use the existing
   `SLACK_CONTROL_CHANNEL_ID` (private admin channel) since this is
   an operational issue, not a member-visible one.
4. **Rollout shape** — single PR covering all milestones (overrides
   the per-milestone approval gates in `docs/features/README.md`),
   per explicit operator direction. Milestone commit prefixes are
   still used for traceability inside the PR.
5. **ESPHome compile-check** — install `esphome` locally and run
   `esphome config` against the modified YAML before opening the PR.
   If installation fails, flag for human handling.

## Implementation Status

**Status:** 🚧 IN PROGRESS — server changes (Milestone 1) and firmware
changes (Milestones 2–4) implemented; documentation, full-suite
verification, and live rollout pending.

- **Milestone 1 — Server-Side Write Timeout:** ✅ COMPLETE
  - `STATE_SAVE_TIMEOUT_SEC = 2.0` in `src/dm_mac/models/machine.py`
  - `StateSaveTimeoutError` raised by new async
    `MachineState.save_cache()` wrapper around the existing sync
    `_save_cache()`
  - All three view handlers (`/machine/update`, `/machine/oops`,
    `/machine/locked_out`) catch the exception and return HTTP 503
    with `{"error": "state save timeout"}`
  - Per-machine `state_save_timeouts` counter persisted with the rest
    of the pickle state
  - `mac_state_save_timeouts_total` Prometheus counter exposed via a
    new `LabeledCounterMetricFamily` helper
  - Slack notification fired on every timeout where the per-machine
    count crosses ≥ 2 (single transient stalls do not page)
  - Tests: `TestAsyncSaveCache` (5 tests), 503 surfacing tests for
    each of the three endpoints, prometheus output regenerated
  - All `nox` sessions (`tests`, `mypy`, `pre-commit`) passing; total
    coverage 97 %
- **Milestones 2–4 — Firmware Changes:** ✅ COMPLETE
  - `esphome-configs/2025.11.2/no-current-input.yaml` validates with
    `esphome config` (ESPHome 2025.6.3 locally available)
  - **M2** — `http_request: timeout: 5s` and `watchdog_timeout: 8s`;
    five duplicated `http_request.post` blocks replaced with
    `script.execute: post_to_mac`; new `script: mode: restart` is the
    single source of truth for the POST and now has both
    `on_response` (status-code-aware) and `on_error` handlers; new
    `last_ok_post_uptime` and `consecutive_post_failures` globals
  - **M3** — second `interval:` entry implements the liveness
    watchdog (90 s threshold, 120 s startup_delay, gated on relay
    state — reboots only when both relays are off, otherwise displays
    `WARN: server\nlink stale` on the LCD)
  - **M4** — `esp32.framework.sdkconfig_options` configures the
    esp-idf task WDT with a 60 s timeout and `..._PANIC: y` for the
    catastrophic-hang fallback
- **Milestone 5 — Acceptance:** ✅ COMPLETE (in this PR)
  - `CLAUDE.md` updated with the State Persistence timeout behavior
    and the 503 response on `/machine/update`.
  - `docs/source/http-api.rst` gained a "State Save Timeout
    (HTTP 503)" section and a paragraph in the Prometheus Metrics
    section about `mac_state_save_timeouts_total`.
  - All `nox` sessions pass: `tests` (97 % coverage), `mypy`,
    `pre-commit`, `safety`, `docs`.
  - The feature file is intentionally **not** moved to
    `docs/features/completed/` in this PR because Milestone 6 (live
    rollout) cannot complete until after merge; a follow-up commit
    will move the file once live validation is signed off.
- **Milestone 6 — Live Rollout:** ⏳ PENDING (post-merge — see
  procedure above)
