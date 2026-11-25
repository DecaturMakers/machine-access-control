# Custom MCU PCB (V2 Hardware)

You must read, understand, and follow all instructions in `./README.md` when planning and implementing this feature.

## Overview

Research and recommend a custom PCB to replace the off-the-shelf (COTS) assembly inside the
[Version 1 MCU box](../source/hardware.rst) (ESP32 dev board on a screw-terminal breakout, level
converter, relay module, and point-to-point wiring to the reader, LCD, LED, button and M12
connector). Tracked in GitHub issue #208.

**This document is research, not a finished design.** It is written in the feature-doc format so
that, once Jason approves the recommendations, the "Implementation Plan" section below becomes the
plan for the actual board. A feature doc is a reasonable container for this: the research is the
planning phase of the feature. If Jason would rather keep research and the build plan separate, the
research sections can move to a dated `docs/YYYY-MM-DD-*.md` analysis doc like the existing
lockup analyses.

**Status:** second revision, after Jason's answers of 2026-11-25 (section 0). **Awaiting Jason's
decisions in section 14 before any design work.** Nothing has been ordered and no firmware or
ESPHome config has been changed.

Conventions used below:

* **[confirmed]**: verified from this repo, a datasheet, distributor page or source file (cited),
  or stated by Jason.
* **[assumed]**: inferred, not confirmed. Each one needs checking by Jason or on a prototype.
* **[snapshot]**: a price or stock figure taken from a search-result summary because the live page
  could not be fetched. Recheck before ordering.
* Other prices were read from live distributor pages on **2026-11-25**; they are not estimates.

## 0. Decisions and answers from Jason (2026-11-25)

* **Connector:** keep the M12 A-coded 8-pin. It is the only widely available locking connector with
  pigtails, cables and extensions; the 2 A limit is accepted. (GX16-8 is hard to find except as
  bare connector bodies.)
* **Architecture:** the ideal is **a single board mounted to the lid** carrying the LCD, reader,
  button and LED, with as few connections as possible, supporting different button and LED styles.
  Housing is a custom 3D-printed housing, or a 3D-printed faceplate on a metal housing with an
  external WiFi antenna. Enclosure constraints from the first revision are all open.
* **GPIOs can be reassigned.**
* **Unit count:** 5 in production, 6 more built and not yet deployed (11 V1 units). About 10 more
  after that; a bulk lot may be bought for stock depending on cost. Quantities used below: 10, 25
  and 50 boards.
* **Loads:** from a VFD's logic-level input up to a 5 HP 240 VAC motor. **Anything switching more
  than 1 A uses an external relay/contactor assembly.**
* **Mains on M12: no.** Every unit that switches more than a control signal has a second enclosure
  with the 5 VDC supply and a 5 VDC-coil relay; M12 pins 3/4 carry only that relay's control
  circuit.
* **Field failures: none.** All V1 units are securely mounted on stationary equipment. (Movable
  tools are new, so vibration is a new consideration for V2.)
* **Fobs:** generic 125 kHz EM4100-compatible cards and keyfobs.
* **Movable tools:** planer, jointer; later perhaps a contractor table saw; welders are at most a
  stretch goal. **IP54 is sufficient**; they are never used outdoors in rain.
* **Main concern: the RFID reader**, as the hardest part to source (section 4).

## 1. Constraints for the enclosure effort

### 1.1 Architecture

**Recommendation: one lid-mounted board. The LCD, RFID reader and status LED are on the board;
the Oops button is a panel part on a short keyed cable; the M12 is a panel-mount socket whose
leads land on a pluggable terminal block.** That is two internal connections (plus a u.FL antenna
cable in a metal housing).

* **Front face (towards the faceplate):** through-hole parts only: the bare 16x2 LCD on a 16-pin
  header and standoffs, the reader (module socket or on-board antenna, see section 4), and a
  through-hole addressable LED (5 mm or 8 mm WS2812-compatible) or a light pipe.
* **Back face:** all SMT parts, so assembly stays single-sided (JLCPCB charges double setup and
  stencil for double-sided), plus the relay, the terminal block and the button header.
* **Button:** a 4-pin JST-XH header. The faceplate holds whichever panel button is chosen (16 mm,
  19 mm, 22 mm mushroom); the board cannot hold it directly because panel buttons have a deep body
  and threaded bushing. The button LED is driven through a MOSFET from 5 V with a resistor
  footprint, so 3 V, 5 V and (dimly) 12 V LED buttons all work, which widens button choice compared
  with V1's "LED must be 3.3 V-drivable" rule.
* **LED styles:** footprints for a through-hole 5 mm/8 mm addressable LED on the front, plus a
  3-pin header for an external pixel such as V1's 12 mm LED. Only one is fitted.

What this costs: the board is larger (about 150 x 85 mm, see 1.2), above JLCPCB's 100 x 100 mm
price tier, and the faceplate layout is fixed by the board. The housing becomes "a box that fits
this board" rather than "a box that holds loose parts".

### 1.2 Board outline and mounting

| Item | Target | Notes |
|---|---|---|
| Outline | about 150 x 85 mm, 1.6 mm FR-4, 2 layers | [assumed] until first layout; driven by LCD (80 x 36 mm) + reader zone + button/LED row |
| Mounting | 6 x M3 (3.2 mm plated): 4 at the corners, 2 near the LCD and reader | the faceplate is the reference surface; board on standoffs behind it |
| Front-face height | LCD: about 10 mm (bare LCD, no I2C backpack) above the board; reader module: about 10 mm [assumed] | the faceplate sits on the LCD bezel; window over LCD, plain plastic over reader |
| Back-face height | 20 mm max | relay and terminal plug with wires |
| Reader zone | no copper pour under or around the reader antenna; at least 20 mm from the LCD's metal bezel and the ESP32 module [assumed] | 125 kHz fields detune near metal and ground planes |
| ESP32 antenna (WROOM-32E) | at a board edge, 15 mm clear of metal | not needed for WROOM-32UE (external antenna) |

### 1.3 Connectors

* **M12 A-coded 8-pin, V1 pinout, panel-mount female socket** in the housing wall (Pg9 or
  M16 x 1.5 threaded hole), leads to an 8-position 3.81 mm pluggable terminal on the board. Rated
  **30 V and 2 A per contact, IP67 mated** (Phoenix Contact 1436343 datasheet) [confirmed]. Fine for
  every load path Jason described: ≤1 A SELV pilot circuits only [confirmed by Jason].
* **Oops button:** 4-pin JST-XH (switch, switch return, LED+, LED-).
* **External antenna (metal housing only):** ESP32-WROOM-32UE's u.FL socket to a bulkhead RP-SMA
  pigtail. WROOM-32E and WROOM-32UE share one footprint, so one board design serves both housings;
  the module is chosen at order time [assumed: same footprint per Espressif's combined datasheet,
  verify against the land pattern].

### 1.4 Housing and environment

* **IP54** for all units, indoor and movable [confirmed by Jason]: gasketed lid/faceplate seam,
  sealed LCD window, and an M12 cap on a lanyard for unplugged movable units. The external card
  pocket is fine at IP54.
* **Temperature:** 0 to +40 °C ambient, up to +50 °C for occasional dry outdoor use in sun
  [assumed]. The standard HD44780 LCD (typically 0 to +50 °C [assumed; not stated on the
  distributor page checked]) is the limiting part; everything else on the board is rated -40 to
  +85 °C.
* **Metal housing:** the faceplate over the LCD and reader must be non-metallic, and the reader
  antenna should be at least 25 mm from the metal housing edge [assumed rule of thumb; verify read
  range on a prototype]. WiFi needs the WROOM-32UE and an external antenna.
* **Vibration (planer, jointer, table saw):** soldered module rather than a socketed dev board
  (section 3), latching JST-XH for the button, the terminal block plug screwed down, LCD on
  standoffs as well as its header, and the reader module (if used) retained by the faceplate or a
  clip, not only by its socket.

## 2. Known problems and how the board addresses them

| # | Problem | Hardware or firmware/server? | Board's answer |
|---|---|---|---|
| 1 | Machine starts on the next login after an Oops clear because the machine's own switch was left ON (`docs/2026-11-21-oops-clear-power-on-analysis.md`) | **Hardware gap at the machine**, not the MCU | The board cannot see the machine switch while its relay is open. Real fix: NVR or magnetic switches on the machines. The board adds a current-transformer input so future firmware can detect current flowing the instant the relay closes and open it again (section 8). |
| 2 | MCUs wedged for 22 h and 40 min while WiFi-associated (`docs/2026-05-05-*`, `docs/2026-05-11-*`) | **Firmware/server**, already fixed in firmware | Reset supervisor on EN; external watchdog footprint, not fitted by default because using it needs a firmware change (section 7). |
| 3 | Relay state at boot / brown-out | Hardware | MOSFET relay driver with a gate pull-down: the relay is open whenever the GPIO is not driven. Tamper input moved off strapping pin GPIO12. Second-relay output gated in hardware by the primary relay drive (section 5). |
| 4 | Hand-wired COTS stack | Hardware | One board, two internal connections. No V1 field failures from wiring [confirmed by Jason], so the gain is build time and repeatability, plus robustness for the new movable units. |
| 5 | No current sensing or tamper; second relay optional | Hardware + future firmware | Tamper input, CT input and the second-relay output on the existing M12 pins; firmware for tamper and current is proposed only (section 10). |

## 3. MCU: module on the board vs a dev board on headers

**Recommendation: ESP32-WROOM-32E-N4 (or -32UE-N4 for an external antenna) soldered to the
board.**

| | Module soldered on the board | Dev board (ESP32-DevKitC-32E/-32UE) plugged into headers |
|---|---|---|
| Part cost | module $3.31 at 10 (LCSC C701341) [confirmed]; -32UE $2.65 to $4.16 [snapshot]; plus USB-UART, USB-C, LDO, supervisor, buttons: about $1.90 more (section 11) | Espressif DevKitC-32E $14.69, -32UE $14.40 at Mouser [snapshot; currency unverified] |
| Assembly | JLCPCB places it; about five extra Extended-part fees per order ($3.07 each) | fewer SMT parts; two 19-pin header sockets to solder |
| Field swap | replace the whole board (it is the spare part) | pull the dev board, which is quicker if the ESP32 itself fails |
| Vibration | nothing to work loose | header sockets can fret or back out on a planer or jointer; needs a retaining strap |
| Height | module is 3 mm | dev board on sockets adds about 20 mm on the back face [assumed] |
| Reset, power quality | our own supervisor and LDO | whatever the dev board has: the genuine DevKitC is fine, clones vary (AMS1117, RC on EN) |
| Pinout risk | none | the board must match one dev board pinout; 38-pin and 30-pin clones differ in width and order |
| Antenna | 32E or 32UE on the same footprint | buy the matching dev board |

What the module option gives up: you cannot swap only the ESP32. Since the board is the swap unit
and costs less than one genuine dev board in parts, that is the right trade for movable tools.

Module notes:

* WROOM-32D (V1) is marked "Not Recommended for New Designs" on its datasheet v2.8; WROOM-32E is
  its current replacement [confirmed]. Espressif's longevity commitment covers the ESP32 (classic)
  chip for at least 15 years from 2016-01-01 [confirmed].
* Same chip, so `board: esp32dev` and every ESPHome component in the current config carry over.
  4 MB flash, the same as V1, is enough for OTA.
* ESP32-S3 / C3 / C6 were considered and rejected: different board targets and pin capabilities for
  no gain this application needs.

## 4. RFID reader (the main sourcing problem)

### 4.1 What any reader must do

* **Deliver the full 32-bit EM4100 ID.** The fob numbers in Neon are 10-digit decimals (the
  `Fob10Digit` field in `docs/source/neon.rst`), which is the 32-bit EM4100 ID printed on the card.
  ESPHome's `wiegand` component gives the full 32 bits only for 34-bit frames: for 26-bit frames
  it emits the lower 24 bits, at most 8 digits (`wiegand.cpp`, lines 72 to 93) [confirmed]. So the
  V1 reader must be sending Wiegand-34 [assumed: inferred from the codes matching Neon; Jason,
  please confirm from a V1 log line], and a **Wiegand-26-only reader would break every existing
  fob**.
* **Report card presence**, because pulling the card logs the user out. V1 uses the reader's `CST`
  line on GPIO18.

### 4.2 Options

| | A. V1 AliExpress Wiegand reader on a header | B. ID Innovations ID-12LA module on the board | C. On-board EM4095 front end + PCB antenna |
|---|---|---|---|
| Sourcing | single AliExpress listing; the core problem | SparkFun SEN-11827 in stock, $32.50 (1), $30.88 (25+), $29.25 (100+) [confirmed, sparkfun.com]; Mouser 474-SEN-11827, 28 in stock [snapshot]. ID Innovations' own site did not resolve and the datasheet dates from 2015 [confirmed], so it is a long-lived part from one small maker | EM Microelectronic EM4095 (SOIC-16): LCSC out of stock, about $2.85 at 100+ [snapshot]; TME EUR 4.30 at 1, 898 in stock [snapshot]; DigiKey listed [snapshot]. No EOL notice found |
| Full 32-bit ID | yes (Wiegand-34) [assumed, 4.1] | yes, via its ASCII serial output (STX, 10 hex chars, checksum, CR LF ETX). Its Wiegand output is 26-bit only, so it must not be used [confirmed, datasheet v1.2] | yes, firmware decodes the raw EM4100 frame |
| Card present | `CST` pin | Tag-in-Range pin (pin 6, high while a tag is in range, all formats) [confirmed in datasheet text; one table row marks it "(Future)", so bench-test it] | in firmware: card present while frames keep arriving (EM4100 tags repeat their frame continuously) |
| Supply | 3.3 to 5 V | 2.8 to 5 V, needs a clean linear-regulated supply (under 3 mV p-p) [confirmed] | 4.1 to 5.5 V (5 V rail) [confirmed] |
| Read range | short [assumed] | 12 cm with an ISO card [confirmed]; the ID-20LA (SEN-11828, $37.50) reads 18 cm | about 11 cm on EM's demo board PCB antenna (120 µH) [confirmed, AN404] |
| ESPHome | `wiegand` (unchanged) | built-in `rdm6300` component parses this exact frame (it skips CR/LF "for ID-20LA compatibility") and emits the 32-bit ID [confirmed, `rdm6300.cpp`] | **no ESPHome component exists** [confirmed by search]; closest code is the MIT-licensed `Nickjgniklu/em4095` ESP32 library, which would have to become an ESPHome external component in this repo |
| Firmware change | none | small: `uart:` + `rdm6300:` instead of `wiegand:`, plus a duplicate filter (section 10) | large: new component, Manchester decode, card-present logic, and it must not disturb the main loop |
| Board design risk | none | low: module footprint, clean 3.3 V supply, keep-out | high: antenna design and tuning, layout near the LCD bezel and ground, EMC of a 125 kHz carrier |
| Per-unit reader cost | $6.26 (V1 price, Nov 2025, not re-checked) | about $31 | about $3 to $5 IC plus passives; antenna is PCB copper [snapshot prices] |

Other modules checked: Seeed Grove 125 kHz (5 V only, UART or Wiegand-26, no card-present pin),
RF125e (Wiegand-26 only, non-commercial licence), RDM6300 (cheap and everywhere, UART frame
parsed by ESPHome, but no card-present pin, and whether it keeps sending frames while a card is
held is not confirmed). None of them both deliver 32 bits and report presence [confirmed for
Grove and RF125e from their docs; RDM6300 behaviour unconfirmed].

### 4.3 Recommendation

**Rev A: ID-12LA (option B) as the fitted reader, with a 5-pin header for a V1-style Wiegand
reader (option A) on the same GPIOs as a fallback.** It is the only distributor-stocked part found
that delivers the full ID and a presence signal, it needs a small, well-understood firmware change,
and it removes the antenna design from the critical path. Its cost is the price: about $25 more per
unit than V1's reader, about $625 over 25 units.

**Evaluate option C separately, as a cost-down for a bulk buy.** If 50 units are on the table, the
roughly $27 per-unit saving (about $1,350) may pay for the antenna and firmware work. It should be
proven on a small test board (EM4095, PCB antenna, ESP32 dev board) before it goes onto the main
board. The main board's reader zone can be laid out so a later revision swaps the ID-12LA socket for
the EM4095 antenna without moving anything else.

What this does not fix: the ID-12LA is still effectively single-source. The Wiegand header is the
hedge, and option C is the long-term exit.

## 5. Load switching

All load paths are ≤1 A SELV pilot circuits: a VFD's logic input or the 5 VDC coil of the relay in
the separate mains enclosure; anything over 1 A goes through an external relay/contactor
[confirmed by Jason]. So the board needs a small pilot relay, not a power relay.

**Recommendation: Omron G5V-1-DC5 signal relay** (or equivalent) on M12 pins 3/4.

* Gold-clad contacts with a minimum load of about 1 mA at 5 VDC and a 1 A rating [snapshot: LCSC
  C28695 page text and RS spec sheet; Omron's datasheet could not be fetched, confirm before
  ordering]. That matters because a VFD input switches only a few mA, below what the silver
  contacts of V1's 10 A relay module reliably switch [assumed: typical power-relay minimum load is
  around 10 to 100 mA].
* Mechanical contact: tolerant of the coil kickback from the 5 V relay in the mains enclosure, and
  works for AC or DC.
* Alternative: a PhotoMOS solid-state relay such as Toshiba TLP241A (40 V, 2 A, LCSC C2152214,
  $1.55 at 1 [snapshot]). No wear and silent, but it needs a TVS across the output to survive coil
  kickback if the mains enclosure's relay has no flyback diode, and it leaks a little when off.
  Reasonable if relay chatter or wear ever becomes an issue.
* **Fail-safe:** AO3400A low-side driver with a 10 kΩ gate pull-down and a flyback diode. The relay
  is open whenever GPIO33 is not actively driven: during reset, boot and brown-out, and with the
  ESP32 unpowered. Espressif's IO_MUX table shows GPIO33 with output disabled and no pull at and
  after reset [confirmed, ESP32 datasheet Appendix A].
* **Second relay (M12 pin 6):** stays a 3.3 V logic output so existing second-relay setups still
  work, driven through a 74LVC1G08 AND gate (GPIO14 AND the primary relay drive), with a series
  resistor and ESD clamp. GPIO14's weak pull-up is enabled after reset until firmware configures it
  [confirmed, same table], so on V1 the line floats weakly high during boot; the AND gate blocks
  that while GPIO33 is low, and enforces in hardware what the server already does (second relay
  only while the primary is on). No firmware change. The common "GPIO14 outputs PWM at boot" claim
  has no Espressif source.
* On any reset the relay opens. With a non-latching relay there is no way to hold a load through
  an ESP32 reset, and the constitution requires relays to default off. The firmware already avoids
  self-reboots while the relay is on (section 7).
* Suppression at the far end: the 5 V relay in each mains enclosure should have a flyback diode
  across its coil [assumed: most 5 V relay modules include one; check the ones in use].

## 6. Power input

**Keep the external 5 V supply on M12 pins 1/2** [confirmed by Jason: the mains enclosure, or the
machine, provides it]. No mains on the board.

* 3.3 V main rail: AP7361C-33 (1 A LDO). The ESP32 draws up to about 500 mA in WiFi transmit
  bursts. AMS1117 is cheaper, but its 1.1 V dropout leaves little margin after the input protection.
* Reader rail: a separate AMS1117-3.3 (JLCPCB Basic part) for the ID-12LA, which asks for a
  clean linear-regulated supply; at about 35 mA load the dropout is not a problem.
* 5 V loads [assumed, measure on a prototype]: ESP32 about 250 mA average, LCD backlight about
  30 mA, relay coil about 30 mA (G5V-1, [assumed]), status LED up to 60 mA, reader 35 mA, button
  LED up to 20 mA. Well under 0.5 A in total, within the M12's 2 A per contact.

## 7. Protection, reset and watchdog

Input (M12 pins 1/2): 1.1 A PTC resettable fuse, AO3401A reverse-polarity P-MOSFET, SMBJ5.0A TVS,
47 to 100 µF bulk capacitance, and a ferrite between the relay/LED 5 V and the LDO inputs.

Signals: ESD arrays (SRV05-4) and series resistors on every off-board line: M12 pins 5 to 8, the
button and its LED, and the external-LED header. The reader, LCD and on-board LED no longer leave
the board, which removes most of V1's exposed lines.

Reset and brown-out:

* ESP32 internal brown-out detector stays on [assumed ESPHome default, verify].
* **APX803S-29 voltage supervisor on EN** in place of the usual RC, so the chip starts cleanly on a
  slowly rising supply (long cable, soft-start supply) and resets cleanly on a sag [assumed from
  common ESP32 practice].

External watchdog (problem 2):

* The documented lockups were the main loop stuck in an HTTP call that kept feeding the task
  watchdog. Firmware now bounds that call and panics the task watchdog after 60 s. An external
  watchdog would be an independent check that the main loop is alive.
* That case ("loop dead") is also the case where the Oops button does nothing, so resetting and
  dropping the relay is the safe outcome. Bronte's deliberate relay-on-mid-cut case was "loop alive,
  server unreachable", which the firmware handles and an external watchdog kicked from the main loop
  never sees.
* **Recommendation: footprint only, not fitted.** TPL5010 timer, about 120 s timeout (longer than the
  60 s task watchdog), reset output to EN through a not-fitted resistor, kicked from GPIO25 by an
  ESPHome `interval:`. Fitting it needs that firmware change.

## 8. Current sensing and the "machine switch left ON" problem

* The board cannot detect the machine switch position while its relay is open: no current flows and
  the board sees no mains. Pre-emptive fixes are at the machine: an NVR (no-volt release) paddle
  switch or magnetic starter, or an auxiliary contact on the machine switch wired back to an input.
  **NVR switches are the recommendation for problem 1.**
* A current input lets future firmware see current within a few hundred ms of the relay closing,
  then open the relay and show "turn machine switch off" if current flows before the operator
  presses start. The motor would still twitch. That is a mitigation, not a fix.
* **Recommendation: include the CT input now, firmware later.** Burden resistor footprint, 1.65 V
  bias, RC filter and ESD clamp into GPIO36 (ADC1; ADC2 cannot be used with WiFi) [confirmed ADC1 =
  GPIO32 to 39, ESP-IDF docs]. Sensor: a voltage-output split-core CT such as the YHDC SCT-013-030
  (30 A, 1 V) on one machine conductor inside the mains enclosure, wired to M12 pins 7/8. ESPHome's
  `ct_clamp` sensor platform reads it through an `adc` sensor [confirmed, esphome.io].
* No current-input ESPHome config exists today [confirmed: only `no-current-input.yaml`].

## 9. Programming and debug

* USB-C with a CH340C USB-UART and two-transistor auto-reset, plus BOOT and EN buttons. VBUS feeds
  the 5 V rail through a Schottky diode, so a board can be flashed and bench-tested without M12
  power and cannot back-feed the mains enclosure's supply.
* A 2.54 mm header with TX, RX, GND, 3.3 V, EN and GPIO0 for an external adapter or logic analyzer.
* **OTA stays the production path** (`ota: platform: esphome`). The USB connector is inside the
  housing.

## 10. Firmware compatibility (pin map)

| Function | V1 GPIO | V2 GPIO | Change |
|---|---|---|---|
| Reader data | Wiegand D0 16, D1 4 | **ID-12LA serial out → 16** (UART RX); Wiegand header keeps D0 16, D1 4 | config change if the ID-12LA is fitted (below) |
| Card present | 18 (`CST`) | 18 (ID-12LA Tag-in-Range, or header `CST`), with a pull-down | none; both are active high |
| LCD SDA / SCL | 22 / 23 | 22 / 23 | none: PCF8574 on the board at address 0x27, powered from 3.3 V, driving a 5 V LCD |
| Status LED data | 27 | 27 | none, except `rgb_order` for the LED fitted (below) |
| Oops button | 32 | 32 | none; the NC wiring is kept, so an unplugged button cable reads as "Oops pressed" |
| Oops LED | 5 | 5 | none; now drives a MOSFET, same polarity |
| Primary relay | 33 | 33 | none |
| Second relay (M12 pin 6) | 14 | 14 | none; ANDed with the relay drive in hardware |
| Tamper (M12 pin 5) | 12 | **35** | moved off strapping pin GPIO12; no config uses it today |
| CT clamp (M12 pins 7/8) | none | **36** | new; no config uses it today |
| External watchdog kick | none | **25** | new; only if the not-fitted watchdog is fitted |

Why GPIO12 must move: GPIO12 (MTDI) sets the flash supply voltage at reset, and the WROOM-32E
datasheet says "IO12 should be kept low when the module is powered on" [confirmed]. A tamper switch
pulling it high during reset selects a 1.8 V flash supply for 3.3 V flash, so the board would not
boot [inference from that]. GPIO35 is input-only with no internal pull-up, so the board adds one.

PCF8574 at 3.3 V driving a 5 V LCD: ESPHome's `lcd_pcf8574` driver only writes and never reads the
LCD (`pcf8574_display.cpp`) [confirmed], and the HD44780's logic-high threshold at 5 V is about
2.2 V [assumed from the Hitachi datasheet; verify on the prototype]. This removes the level
shifter and the I2C backpack.

Status LED colour order: V1's config uses `rgb_order: RGB` for LEDs cut from a string. Genuine
WS2812B and most through-hole addressable LEDs are GRB [assumed; check the part fitted].

**Config diff for an ID-12LA-fitted board (proposal only, not applied to any config):**

```diff
-wiegand:
-  - id: keypad
-    d0: GPIO16
-    d1: GPIO4
-    on_tag:
-      - lambda: ESP_LOGI("TAG", "received tag %s", x.c_str());
-      - lambda: |-
-            id(rfid_tag) = x.c_str();
-            ...
-      - script.execute: post_to_mac
+uart:
+  - id: rfid_uart
+    rx_pin: GPIO16
+    baud_rate: 9600
+
+rdm6300:
+  uart_id: rfid_uart
+  on_tag:
+    # rdm6300 fires on every frame while the card is held; act only on a new tag
+    - if:
+        condition:
+          lambda: 'return to_string(x) != id(rfid_tag);'
+        then:
+          - lambda: ESP_LOGI("TAG", "received tag %u", x);
+          - lambda: |-
+              id(rfid_tag) = to_string(x);
+              ...
+          - script.execute: post_to_mac
```

`to_string(x)` of the 32-bit ID is the same decimal string the `wiegand` component emits for a
34-bit frame, and the server zero-pads both to 10 digits, so no fob data changes [confirmed from
`rdm6300.cpp` line 49 and `wiegand.cpp` lines 83 to 93]. The `card_present` binary sensor on GPIO18
and its `on_release` logout are unchanged.

Proposed later additions (proposal only):

```yaml
binary_sensor:
  - platform: gpio
    pin: GPIO35          # tamper switch, M12 pin 5; external pull-up on the board
    name: "Tamper"
    device_class: tamper

sensor:
  - platform: adc
    pin: GPIO36          # CT clamp, M12 pins 7/8, biased to mid-rail on the board
    id: ct_adc
    attenuation: 12db
    update_interval: never
  - platform: ct_clamp
    sensor: ct_adc
    name: "Machine Current"
    sample_duration: 200ms
    update_interval: 2s
```

## 11. Draft BOM

Unit prices are LCSC's price at its quantity-10 break, or the nearest break (noted), read
2026-11-25. "Class" is the JLCPCB assembly class: Basic parts have no loading fee, each unique
Extended part has one. URL pattern: `https://www.lcsc.com/product-detail/<LCSC#>.html`.

### Board (option B reader)

| Ref | Function | Manufacturer / MPN | LCSC # | Qty | Unit (USD) | Class |
|---|---|---|---|---|---|---|
| U1 | MCU module | Espressif ESP32-WROOM-32E-N4 (or -32UE-N4, C701344) | C701341 | 1 | 3.3129 | Extended |
| U2 | USB-UART | WCH CH340C | C84681 | 1 | 0.4594 | Extended |
| J1 | USB-C receptacle | Korean Hroparts TYPE-C-31-M-12 | C165948 | 1 | 0.1888 (qty 5) | Extended |
| U3 | 3.3 V 1 A LDO | Diodes AP7361C-33E-13 | C500795 | 1 | 0.8833 | Extended |
| U4 | Reader 3.3 V LDO | AMS1117-3.3 | C6186 | 1 | 0.2032 (qty 5) | Basic |
| U5 | Reset supervisor | Diodes APX803S-29SA-7 | C143831 | 1 | 0.2862 | Extended |
| U6 | External watchdog (**not fitted**) | TI TPL5010DDCR | C473912 | 0 | 0.2727 | Extended |
| U7 | LCD I2C expander | NXP/TI PCF8574T | not priced | 1 | not priced | |
| K1 | Pilot relay | Omron G5V-1-DC5 | C28695 | 1 | not priced (RS UK GBP 2.57 [snapshot]) | Extended (THT) |
| Q1, Q2 | Relay driver, button LED driver | AOS AO3400A | C20917 | 2 | 0.0786 (qty 5) | Basic |
| Q3 | Reverse-polarity PFET | AOS AO3401A | C15127 | 1 | 0.0827 (qty 5) | Basic |
| D1, D2 | Flyback, misc. | JSCJ 1N4148WS | C2128 | 2 | 0.0098 (qty 50) | Basic |
| U8 | Second-relay AND gate | SN74LVC1G08DBVR (UMW) | C434068 | 1 | 0.0421 | Extended |
| U9 | LED data 3.3 → 5 V | TI SN74AHCT1G125DBVR | C7484 | 1 | 0.1109 (qty 5) | Extended |
| D3 | Input TVS | MDD SMBJ5.0A | C113974 | 1 | 0.0592 | Extended |
| U10, U11 | ESD arrays | Protek SRV05-4-P-T7 | C85364 | 2 | 0.2214 (qty 5) | Extended |
| F1 | PTC fuse, 1.1 A hold | Littelfuse 1812L110PR | C163516 | 1 | 0.0529 | Extended |
| J2, J3 | Button header; external LED header | JST B4B-XH-A(LF)(SN) | C144395 | 2 | 0.0522 | Extended (THT) |
| J4 | Wiegand reader header (fallback) | JST B5B-XH-A(LF)(SN) | C157991 | 1 | 0.091 (qty 5) | Extended (THT) |
| J5 | M12 lead terminal, plug half | Cixi Kefa KF2EDGK-3.81-8P | C440864 | 1 | 0.4448 | Extended (THT) |
| SW1, SW2 | BOOT, EN | XKB TS-1187A-B-A-B | C318884 | 2 | 0.0198 (qty 20) | Basic |
| (passives) | about 40 R and C | UNI-ROYAL 0603 (C21190, C25804), 100 nF 0603 (C14663), 10 µF 0805 (C15850) | | 40 | 0.0015 to 0.0311 | Basic |
| | **Priced subtotal** | | | | **6.98 + at most 1.24 passives = 8.22** | |

Not priced yet: PCF8574T, the G5V-1 in USD, the 8-position terminal header half, the 16-pin LCD
header, the ID-12LA socket (2 mm pitch [assumed]), the through-hole addressable LED, auto-reset
transistors, USB Schottky, bulk capacitor, ferrite. The passive line uses 40 times the most
expensive passive priced, as an upper bound.

### Front-face and panel parts

| Item | Unit (USD) | Source |
|---|---|---|
| ID Innovations ID-12LA (SparkFun SEN-11827) | 32.50 (1), 30.88 (25+), 29.25 (100+) | sparkfun.com, 2026-11-25 |
| 16x2 HD44780 LCD, bare (Adafruit 181) | 8.96 (10 to 99), 7.96 (100+) | adafruit.com/product/181, 2026-11-25; cheaper bare 1602 LCDs exist but no distributor price was found |
| 16 mm Oops button + cover | 5.49 | V1 table, Nov 2025, not re-checked |
| Addressable LED | 0.32 | V1 table, Nov 2025, not re-checked (12 mm string LED); through-hole part not priced |
| M12 socket + 2 m cable | 9.80 + about 15.49 | V1 table, Nov 2025, not re-checked; no US distributor price found for the Phoenix Contact 1436343 |
| Housing | 9.90 | V1 table (V1 printed enclosure) as a placeholder; the new housing is not designed yet |
| YHDC SCT-013-030 CT, only where current sensing is used | 12.90 to 15.33 | retailer search results [snapshot] |

### Option C reader parts (for the cost-down evaluation)

| Item | Price | Source |
|---|---|---|
| EM Microelectronic EM4095HMSO16A+/B+ | about 2.85 at 100+ (LCSC, out of stock); EUR 4.30 at 1 (TME) | [snapshot] |
| Antenna | PCB copper, about 120 µH (EM demo board) | EM AN404 [confirmed] |
| Resonant and filter capacitors | about 6 C0G/X7R capacitors | Basic passives |

## 12. DFM, ordering and cost

* **Board:** 2 layers, 1.6 mm FR-4, HASL, about 150 x 85 mm, one board per panel.
* **Assembly:** JLCPCB Economic PCBA, single-sided (all SMT on the back face). Through-hole parts
  (LCD header, reader socket, LED, relay, terminal, JST headers) by JLCPCB's hand-soldering service
  or by us. A full hand build is possible: the module has castellated pads and the smallest parts
  are 0603 and SOT-23.
* **JLCPCB fees** (jlcpcb.com/help/article/pcb-assembly-price, updated 2026-10-22, read
  2026-11-25): Economic setup $8.18, stencil $1.53, $0.0016 per SMT joint, $3.07 per Extended part
  type ([assumed] per unique part), $0.45 placement confirmation, $3.58 hand-soldering labour per
  order. With 11 Extended SMT part types (U1, U2, J1, U3, U5, U7, U8, U9, D3, U10/U11, F1; the PCF8574's class is [assumed] Extended) the fixed
  fees are **$43.93 per order**.
* **PCB price at 150 x 85 mm: not quoted.** The quote calculator could not be read by the research
  agent. The first revision's quote was $5.00 for 10 at 100 x 80 mm; above 100 x 100 mm the price
  rises. Get a live quote in Milestone 2.
* **Supply risk:** the reader (4.3) is the main one. The ESP32 module is in deep stock with a long
  longevity commitment; the M12 parts are multi-source.

### Cost comparison with V1

Per control box, using priced items only (the board subtotal of $8.22, fixed fees spread over the
order, the ID-12LA, the bare LCD, and V1 prices for the button, LED, M12 parts and housing
placeholder). The PCB itself, shipping, and the unpriced parts above are **not** included.

| | V1 | V2, 10 boards | V2, 25 boards | V2, 50 boards |
|---|---|---|---|---|
| Board parts | (dev board, breakout, level converter, relay module) $15.83 | $8.22 | $8.22 | $8.22 |
| JLCPCB fixed fees per board | n/a | $4.39 | $1.76 | $0.88 |
| Reader | $6.26 | $32.50 | $30.88 | $30.88 |
| LCD | $3.99 (with backpack) | $8.96 | $8.96 | $8.96 |
| Button, LED, M12 + cable, housing | $41.00 | $41.00 | $41.00 | $41.00 |
| **Total** | **$67.08** | **$95.07 + PCB + unpriced** | **$90.82 + PCB + unpriced** | **$89.94 + PCB + unpriced** |

The reader is the whole difference: V2's board is cheaper than the V1 parts it replaces, and the
ID-12LA adds about $25 per unit. With option C the reader costs about $3 to $5 [snapshot], which
would bring V2 to about the V1 total or below. A 50-unit bulk buy does little for the board (fixed
fees are already small at 25) and saves nothing on the ID-12LA below the 100-unit break.

## 13. Safety and compliance notes for mains switching

These are research notes on common practice, **not a certification or compliance claim**.

* **The external relay/contactor stays mandatory** for any load over 1 A [confirmed by Jason]. The
  control box never carries mains (sections 5 and 6).
* Mains enclosure: a listed enclosure (V1 uses a Carlon PVC box), with cord grips or strain reliefs
  on every cable, the machine's equipment-grounding conductor carried through and bonded, and
  contactors and supplies that are UL-recognized/listed parts rated for the load voltage and the
  motor's FLA (motor-rated, AC-3 or HP-rated contacts).
* Switch every ungrounded conductor: both legs for 240 V machines (V1's 2-pole contactor option
  already does this), the hot (never the neutral) for 120 V.
* Overcurrent protection: the branch circuit protects the cord and contactor; the 5 V supply is
  protected by its own internal fuse; a separate fuse on the 5 V supply's mains input is good
  practice for supplies without one.
* Clearance and creepage on any board that does carry mains: about 3 mm clearance and 4 mm creepage
  for basic insulation at 250 VAC, doubled for reinforced (from IEC 60664-1 tables, pollution
  degree 2; check the exact figures before relying on them). This is why mains stays off the board.
* Labeling: label the mains enclosure "controlled by access control; disconnect machine plug or
  breaker before servicing", and label the machine with how to clear an Oops. The access-control
  relay is **not** a lockout/tagout disconnect and must not be used as one.
* The access-control relay is also not an emergency stop. The Oops button is a request to the
  server, not a safety-rated stop; machines that need an E-stop keep their own.

## 14. Open questions for Jason

1. **Reader:** approve rev A with the ID-12LA (about $31 per unit, small config change) plus the
   Wiegand fallback header? And should option C (EM4095 + PCB antenna, about $27 per unit cheaper,
   new ESPHome component) be evaluated on a small test board in parallel, given a possible bulk buy?
2. **V1 reader format:** can you confirm from a V1 ESPHome log that the reader sends 34-bit frames
   (the log shows the bit count), or that a logged tag matches the 10-digit number printed on the
   card?
3. **MCU:** OK with the module soldered on the board (section 3), with the whole board as the
   field spare?
4. **Button and LED styles:** which button sizes should the faceplate design cover (16 mm only, or
   19/22 mm too), and is a through-hole 5 mm or 8 mm addressable LED on the board acceptable as the
   default, with V1's 12 mm LED as the header option?
5. **Pilot relay:** G5V-1 signal relay (mechanical) or a PhotoMOS (TLP241A)? Do the 5 V relays in
   the mains enclosures have flyback diodes?
6. **Hardware layout:** OK to create `hardware/v2_mcu/` holding a KiCad project (schematic, PCB,
   JLCPCB BOM/CPL exports, README) alongside `hardware/v1_mcu/`?
7. **Approval:** approve the rest (lid-mounted board, M12 and V1 pinout, 5 V input, CT input and
   not-fitted watchdog footprint, tamper on GPIO35) so the implementation plan can start?

## Implementation Plan

Proposed only; not started. Per `docs/features/README.md`, each milestone needs Jason's approval
before moving to the next. Commit prefix: `Custom MCU PCB - {Milestone}.{Task}`.

### Milestone 1: Schematic

* 1.1 Create `hardware/v2_mcu/` KiCad project and README (after question 6).
* 1.2 Schematic per sections 3 to 10, with LCSC part numbers on every SMT part; price the parts
  listed as not priced.
* 1.3 Review: a fresh reviewer checks the pin map against the ESPHome config and the fail-safe relay
  path.

### Milestone 2: Layout and order files

* 2.1 Board outline, faceplate reference points and mounting per section 1; hand the outline to the
  housing effort.
* 2.2 Layout, DRC, JLCPCB BOM/CPL export.
* 2.3 Live JLCPCB quote; **Jason approves before any order is placed.**

### Milestone 3: Prototype bring-up

* 3.1 Flash `hardware-test.yaml` and `no-current-input.yaml` (with the reader diff from section 10
  in a copy, not in the committed config, until Jason approves a firmware change); run
  `esphome-configs/2025.11.2/hardware-test.md`.
* 3.2 Measure: relay state through power-up, EN reset, brown-out and GPIO14 toggling; 5 V current;
  ID-12LA Tag-in-Range behaviour and read range in the 3D-printed and metal housings; WiFi with the
  32E and 32UE modules.
* 3.3 Fixes and a second revision if needed.

### Milestone 4 (optional): Option C reader evaluation

* 4.1 Small test board: EM4095, PCB antenna per AN404, header to an ESP32 dev board.
* 4.2 Prototype ESPHome external component; measure read range and card-present reliability.
* 4.3 Decide with Jason whether a later revision moves to option C.

### Milestone 5: Acceptance Criteria

* 5.1 Update `docs/source/hardware.rst` with a Version 2 section (components, wiring, pinout).
* 5.2 Add a V2 ESPHome config (only after Jason approves the firmware change).
* 5.3 Update `CLAUDE.md` if anything in it changes.
* 5.4 All nox sessions pass.
* 5.5 Move this file to `docs/features/completed/`.
