# RS485 Frame examples

Ready-to-flash ESPHome configurations for pool and spa controllers that use DLE-framed RS485 buses
(Hayward AquaLogic / ProLogic, Jandy AquaLink RS, and similar). Each configuration builds on
the `rs485_frame` ESPHome component (currently on the
[staging branch](https://github.com/b3nj1/esphome/tree/rs485_frame); see [About the packages](#about-the-packages)
below).

You assemble a config for your system by copying one short **device config** and listing the
equipment you actually have — no hand-editing of decoder C++. If you want to *add* support for a new
controller or piece of equipment, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Quick start

**Hayward AquaLogic / ProLogic** — copy one of these two files, fill in your `substitutions:`, and
flash. Both are self-contained (no equipment to uncomment, no menu to trim) and differ only in the
board they target:

```yaml
packages:
  rs485:
    url: https://github.com/b3nj1/rs485_frame-examples
    ref: v3.0.1
    refresh: 1d
    files:
      - hayward/aqualogic/bus.yaml   # required
```

| File | Board | Status |
|---|---|---|
| [hayward/aqualogic/quickstart-waveshare.yaml](hayward/aqualogic/quickstart-waveshare.yaml) | Waveshare ESP32-S3-RS485-CAN (board + pins fixed) | tested-on-hardware |
| [hayward/aqualogic/quickstart-discrete.yaml](hayward/aqualogic/quickstart-discrete.yaml) | Bare ESP32 devkit + separate MAX485-style adapter (board + pins are placeholders) | tested-on-hardware decode path; your own board/pins |

Both ship core entities only (temperatures, display, diagnostics from `bus.yaml`, plus Home
Assistant's own automatic API online/offline indicator for the device — no separate bus-connectivity
entity is defined). Once one of
them flashes and reports data, move to
[hayward/aqualogic/example-device.yaml](hayward/aqualogic/example-device.yaml) — the full,
commented menu — to add pump/heater profiles and the AUX/valve buttons and LEDs your system has.
See [Hardware](#hardware) below for wiring and [After your first flash: Home Assistant](#after-your-first-flash-home-assistant)
for a starting dashboard.

**Jandy AquaLink RS** support exists in [jandy/aqualink-rs/](jandy/aqualink-rs/), but has no
quickstart yet and is **UNTESTED** (community-sourced protocol bytes, never verified on physical
hardware — see the warning under [Available configurations](#available-configurations)).

## Hardware

### Hayward keypad terminal wiring

Every Hayward AquaLogic / ProLogic wiring path below starts at the controller's RS485 keypad
terminal, a 4-wire connection:

| Keypad wire | Function |
|---|---|
| RED | 10-12 VDC power |
| BLACK | A+ (data) |
| YELLOW | B- (data) |
| GREEN | GND |

> **Warning:** the RED wire carries 10-12 VDC. Connect it only to a power input (a board's
> regulated VCC/power terminal, or a buck converter feeding a bare devkit's 5V/VIN pin) — never to
> a GPIO or an RS485 adapter's logic-level pin. Wiring it into a logic pin can damage the board or
> the adapter.

### Board: Waveshare ESP32-S3-RS485-CAN (recommended)

The ~$20 USD direct / ~$25 on Amazon
[Waveshare ESP32-S3-RS485-CAN](https://www.waveshare.com/esp32-s3-rs485-can.htm) (not an affiliate
link) is a near-turnkey option: it integrates an ESP32-S3 with a built-in RS485 transceiver and can
be powered directly from the Hayward AquaLogic / ProLogic keypad terminal's 10-12 VDC wire (into
its VCC power terminal, not a GPIO — see the warning above), so no separate power supply is needed.

| Keypad wire | Waveshare board terminal |
|---|---|
| RED (10-12 VDC) | VCC |
| BLACK (A+) | A+ |
| YELLOW (B-) | B- |
| GREEN (GND) | GND |

The board's onboard transceiver is wired internally to fixed GPIOs, which is why
[quickstart-waveshare.yaml](hayward/aqualogic/quickstart-waveshare.yaml) hardcodes them
(`esp32-s3-devkitc-1`, `tx_pin: GPIO17`, `rx_pin: GPIO18`, `flow_control_pin: GPIO21`) instead of
leaving them as placeholders — there is nothing to choose.

### Board: bare devkit + separate RS485 adapter

Any ESP32 variant with two UARTs works, plus a separate RS485 TTL adapter (e.g. MAX485). Half-duplex
adapters with a DE/RE direction pin use `flow_control_pin`; auto-direction or full-duplex adapters
do not need it — delete that substitution and the `uart:` line if so. The devkit needs its own power
(USB or a separate 5V/3.3V supply); don't route the keypad terminal's 10-12 VDC wire into it directly
(see the warning above) unless you're feeding a regulator built for that input range.

| Keypad wire | Adapter terminal | Devkit connection ([quickstart-discrete.yaml](hayward/aqualogic/quickstart-discrete.yaml) substitution) |
|---|---|---|
| RED (10-12 VDC) | — (power input only, see warning) | — |
| BLACK (A+) | A / A+ | — |
| YELLOW (B-) | B / B- | — |
| GREEN (GND) | GND | shared devkit GND |
| — | DE/RE | `flow_control_pin` |
| — | DI (adapter's data in / TX) | `tx_pin` |
| — | RO (adapter's data out / RX) | `rx_pin` |

If you receive no data, swap `tx_pin` and `rx_pin` — some adapters label DI/RO from the adapter's
own perspective, which is backwards from the devkit's.

### Recommended framework: ESP-IDF

All configs default to the ESP-IDF framework. Under ESP-IDF, setting `flow_control_pin` on the
`uart:` component activates the UART peripheral's hardware RS485 half-duplex mode: the DE/RE pin is
driven with shift-register-level timing by hardware. Under the Arduino framework on ESP8266 or
RP2040, the `uart:` component does not drive `flow_control_pin` at all — those platforms need an
**auto-DE transceiver chip** (e.g. MAX13487, MAX22025) where DE follows the TX line automatically.

### No data received, now what

If a quickstart flashes but nothing shows up: confirm the `tx_pin`/`rx_pin` swap above first, then
work through [Diagnostic tools for an unknown bus](#diagnostic-tools-for-an-unknown-bus) —
`generic/discovery.yaml` if you haven't confirmed the bus's framing bytes, or `generic/sniffer.yaml`
(or the Hayward-specific `hayward/aqualogic/sniffer.yaml`) once you have.

## After your first flash: Home Assistant

Every entity from a package lands on the single Home Assistant device created by your `name:` /
`friendly_name:` substitutions — there's no separate device per equipment profile, and no
vendor/package prefix in an entity's friendly name (`"Pool Temperature"`, `"Filter"`, `"AUX 1"`, not
`"AquaLogic Pool Temperature"`) since the one HA device card already groups everything. Entity IDs
follow Home Assistant's usual ESPHome-integration pattern, `<domain>.<device_name>_<slugified_name>`
(e.g. `sensor.aqualogic_pool_temperature` for the default `name: aqualogic`) — check
Settings > Devices & Services > ESPHome > your device if you renamed things and need the exact IDs.
Diagnostic entities (`CRC Failures`, `Command Drops`, the `LED Mask` hex sensor) carry
`entity_category: diagnostic`; most AUX/valve entities in the full menu start
`disabled_by_default: true` until you confirm your panel has that channel — enable what you need in
Settings > Entities.

For a starting dashboard once [quickstart-waveshare.yaml](hayward/aqualogic/quickstart-waveshare.yaml)
is flashed and reporting, see
[hayward/aqualogic/dashboard-example.yaml](hayward/aqualogic/dashboard-example.yaml) — a built-in
Home Assistant "entities" card covering that quickstart's entity set. No HACS custom card: this
project has no runtime dependency beyond ESPHome and Home Assistant themselves, and the sample
dashboard keeps that true.

## Available configurations

One row per controller family; per-profile descriptions and status live in that family's commented
`example-device.yaml` (the single source of truth).

| Controller family | Device config | Status |
|---|---|---|
| Hayward AquaLogic / ProLogic | [hayward/aqualogic/example-device.yaml](hayward/aqualogic/example-device.yaml) | Core (bus, nav buttons, temps, AUX 1-2) tested on hardware; AUX 3-14 and LED bits 9-25 are community-sourced (see file comments) |
| Jandy AquaLink RS — passive observer | [jandy/aqualink-rs/example-passive.yaml](jandy/aqualink-rs/example-passive.yaml) | **UNTESTED draft** |
| Jandy AquaLink RS — active AllButton emulator | [jandy/aqualink-rs/example-allbutton.yaml](jandy/aqualink-rs/example-allbutton.yaml) | **UNTESTED draft — transmits** |

> **WARNING — UNTESTED:** The Jandy configurations are 100% untested and speculative. They have never
> been verified on physical hardware by anyone. The protocol bytes (notably the AllButton ACK third
> byte `0x80`), device addresses, CRC, and the ~60 ms poll-cycle ACK timing are community
> reverse-engineering guesses and may be wrong. The AllButton emulator actively transmits, so a wrong
> guess can disrupt a live controller. Use at your own risk, validate against your own captures, and
> please open an issue with results.

## About the packages

`rs485_frame` is not yet in the ESPHome repository. The bus package for each controller family
includes an `external_components` block that pulls it from the
[staging branch](https://github.com/b3nj1/esphome/tree/rs485_frame). Once it is merged into an
official ESPHome release, that block goes away.

The device config pulls the package files shown in [Quick start](#quick-start) from this repo at a
**pinned release tag** — the tag never moves, so an update only happens when you bump `ref:`.
**Need to edit a decoder?** Copy the package files into your config directory and switch those
`files:` entries to local `!include`s — your edits then stay local. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the composition details (packages, `!extend`, the
substitution contract, and versioning policy).

## Diagnostic tools for an unknown bus

If you are bringing up a controller that is not listed above, work through `generic/` in order:

| File | Description |
|---|---|
| [generic/discovery.yaml](generic/discovery.yaml) | Passive framing/CRC discovery for a completely unknown bus. Logs candidate `dle`/`stx`/`etx`, the escape scheme, and any matching CRC. Run this first when you don't know the framing bytes. |
| [generic/sniffer.yaml](generic/sniffer.yaml) | Passive sniffer with `sniffer_stats:` once you know the framing. Logs a periodic per-frame-type table (cadence, unique payloads) to catalog frame types. |
| [generic/skeleton.yaml](generic/skeleton.yaml) | Starting point for a single monolithic config. Raw-form buttons and `rs485_frame.send_frame` for computed payloads. |

**[UNKNOWN-BUS-WALKTHROUGH.md](UNKNOWN-BUS-WALKTHROUGH.md) is the order to run these three tools
in** — discovery, then what its output tells you, then the sniffer, then what *that* tells you,
then writing your first decoder, with a real worked example alongside each step. Start there if
this is your first time bringing up an unfamiliar bus; the table above is the reference once you
know the workflow.

These stay monolithic by design — there are no equipment profiles to compose for an unknown bus.
Per-family sniffers (e.g. [hayward/aqualogic/sniffer.yaml](hayward/aqualogic/sniffer.yaml)) are the
same kind of self-contained tool. Once you have decoded the bus, package it up following
[CONTRIBUTING.md](CONTRIBUTING.md) and submit it.

## Sample capture

Not sure what a good run looks like? See a real, annotated capture from a Hayward AquaLogic
controller, walked from "unknown bus" to decoded frames — discovery + baud sweep, the sniffer table
on an idle bus and under live remote commands, and a version/ID frame cross-checked against the
controller's Diagnostic screen. Every CRC is verified by hand.

- [captures/hayward-aqualogic-20260529.md](captures/hayward-aqualogic-20260529.md)

When you publish your own, start from [captures/TEMPLATE.md](captures/TEMPLATE.md).

## Writing decoders / adding equipment

Reverse-engineering a new controller, or adding a new piece of equipment to an existing one? The
offset convention, decoder lambda best practices, composition mechanics, and the file/versioning
rules are all in [CONTRIBUTING.md](CONTRIBUTING.md). In short: decoding is payload-relative
(`payload[0..1]` = frame_type, data starts at `payload[2]`), and `on_frame` lambdas must not allocate
on the heap, must guard `payload.size()`, and must not block.

## Acknowledgements

The protocol decoders build on community reverse engineering of the Hayward and Jandy RS485 buses:

- **Hayward AquaLogic wireless remote** — frame layout and key encoding from
  [swilson/aqualogic](https://github.com/swilson/aqualogic).
- **Hayward AquaLogic LED bit table and command encoding** — confirmed against
  [smith288](https://github.com/smith288),
  [stoehrmark](https://github.com/stoehrmark), and
  [ChaseDurand/Pool-Pi](https://github.com/ChaseDurand/Pool-Pi).
- **Jandy AquaLink RS envelope format** (`DLE STX <data> <checksum> DLE ETX`) —
  [Jandy Pool Heater wiki](https://wiki.jmehan.com/display/KNOW/Jandy+Pool+Heater).
- **Jandy AllButton frame catalog, device addresses, and ACK byte sequence** —
  [earlephilhower/aquaweb](https://github.com/earlephilhower/aquaweb/blob/master/protocol.md).
- **Jandy AqualinkD** — extended equipment catalog (ePump, SWG, heater setpoint) from
  [aqualinkd/AqualinkD](https://github.com/aqualinkd/AqualinkD).
