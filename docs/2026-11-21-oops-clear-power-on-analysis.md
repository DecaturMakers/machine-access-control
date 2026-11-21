# Machines powering on after an Oops is cleared: analysis (issue #201)

## Report

On 2026-10-08 staff told members that "once an Oops is cleared, any machine
that wasn't properly shut down will turn back on by itself", after a couple of
close calls. The intended behavior is that clearing an Oops never energizes a
machine; the relay closes only on an authorized RFID insert after the clear.

## Findings

**Server: no path closes the relay on an Oops clear for a normal machine.**
`MachineState.unoops()` sets `relay_desired_state = False` unless the machine is
`always_enabled`. A card left in the reader across the Oops and the clear does
not log in again, because `update()` only runs the login path when
`rfid_value` changes. This holds across a server restart (state reloaded from
the pickle cache) and across an MCU reboot. Regression tests now pin all of
these: `tests/views/test_oops_clear_safety.py`.

**Server: two `_handle_reboot()` defects, both fixed.**

1. An `always_enabled` machine that was Oopsed or locked out had its relay
   turned back **on** by an MCU reboot, because `_handle_reboot()` restored the
   always-on state without checking `is_oopsed` / `is_locked_out`. No machine
   in the production `machines.json` sets `always_enabled`, so this could not
   explain the reports, but it was a real energize-while-Oopsed path.
2. A reboot of an Oopsed or locked-out machine reset the display and status
   LED to the idle defaults, so the reader stopped showing the Oops / lock-out
   message (seen on Resaw on 2026-11-18). The relay stayed off.

`_handle_reboot()` now keeps the relay off and the Oops / lock-out display for
an Oopsed or locked-out machine, and restores always-on only otherwise.

**Firmware: relay follows the server only.** In
`esphome-configs/2025.11.2/no-current-input.yaml` the relay switch has no
`restore_mode`, so it uses the ESPHome default (`ALWAYS_OFF`) at boot, and
`relay_output.turn_on()` is called only when a 2xx response from
`/api/machine/update` carries `"relay": true`. A failed or non-2xx POST leaves
the relay as it was and never turns it on.

**Override sessions.** An `oops_override` user who badges in on an Oopsed
machine gets the relay, by design. If the Oops is cleared during that session,
the session continues until the card is removed; it does not start a new one.

## Most likely cause

The machine's own switch. MAC cuts power with its relay but cannot move the
machine's ON/OFF switch. If a machine is Oopsed (or the card is pulled) with
its switch left ON, the next authorized login closes the relay and the motor
starts at once. To the person badging in, it "turned on by itself" after the
clear. That is a hardware gap, not a server bug.

## Open items (need staff / hardware work)

- Ask staff which machines had the close calls, when, and whether a card was
  in the reader at the moment the machine started.
- Correlate with the `OOPS` and `AUTH` logs in Loki: an `un-Oopsed` line
  followed by a relay-on with **no** `RFID login` / `session start` between
  them would contradict the analysis above. Older logs may have aged out.
- List the machines that lack no-volt-release (magnetic) switches and decide
  on NVR switches, a switch-position interlock, or a documented procedure.
