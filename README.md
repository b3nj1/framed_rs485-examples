# RS485 Frame examples

Ready-to-flash ESPHome configurations for pool and spa controllers that use DLE-framed RS485 buses
(Hayward AquaLogic / ProLogic, Jandy AquaLink RS, and similar). Each configuration builds on
the `rs485_frame` ESPHome component (currently on the
[staging branch](https://github.com/b3nj1/esphome/tree/rs485_frame); see Status note below).

You assemble a config for your system by copying one short **device config** and listing the
equipment you actually have — no hand-editing of decoder C++. If you want to *add* support for a new
controller or piece of equipment, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Status note

`rs485_frame` is not yet in the ESPHome repository. Each device config includes an
`external_components` block that pulls it from the
[staging branch](https://github.com/b3nj1/esphome/tree/rs485_frame). Once it is merged into an
official ESPHome release, that block goes away.

## Hardware

### Recommended: Waveshare ESP32-S3-RS485-CAN

The ~$20 USD direct / ~$25 on Amazon
[Waveshare ESP32-S3-RS485-CAN](https://www.waveshare.com/esp32-s3-rs485-can.htm) (not an affiliate
link) is a near-turnkey option: it integrates an ESP32-S3 with a built-in RS485 transceiver and can
be powered directly from the Hayward AquaLogic / ProLogic RS485 header, so no separate power supply
or adapter is needed.

**Hayward AquaLogic / ProLogic RS485 header wiring:**

| Controller header | Wire color | Board terminal |
|---|---|---|
| 10-12 VDC | RED | VCC |
| A+ | BLACK | A+ |
| B- | YELLOW | B- |
| GND | GREEN | GND |

Set `board`/`variant` in the config's `esp32:` block to a valid ESP32-S3 board/variant name from
https://esphome.io/components/esp32 (for example `board: esp32-s3-devkitc-1`, `variant: esp32s3`).
This board's built-in RS485 transceiver uses these `substitutions:`:

```yaml
substitutions:
  tx_pin: GPIO17
  rx_pin: GPIO18
  flow_control_pin: GPIO21
```

### Recommended framework: ESP-IDF

All configs default to the ESP-IDF framework. Under ESP-IDF, setting `flow_control_pin` on the
`uart:` component activates the UART peripheral's hardware RS485 half-duplex mode: the DE/RE pin is
driven with shift-register-level timing by hardware. Under the Arduino framework the `uart:`
component does not drive `flow_control_pin` at all — Arduino users must use an **auto-DE transceiver
chip** (e.g. MAX13487, MAX22025) where DE follows the TX line automatically.

### Generic wiring

Any ESP32 variant with two UARTs works, plus a separate RS485 TTL adapter. Half-duplex adapters with
a DE/RE direction pin use `flow_control_pin`; auto-direction or full-duplex adapters do not need it.
Connect adapter TX/RX to the device UART pins in your config. If you receive no data, swap `tx_pin`
and `rx_pin` — some adapters label DI/RO from the adapter's own perspective.

```
your flow_control_pin --> DE/RE
your tx_pin           --> DI  (TX)
your rx_pin           --> RO  (RX)
```

## Quick start: assemble your device config

Each controller family ships an `example-device.yaml` — a runnable, fully commented **menu** of every
optional package available for that controller. **Pick yours from [Available configurations](#available-configurations)
below first** (Jandy owners: both Jandy files are currently UNTESTED). Then assemble it in the same four
steps every time:

1. **Copy** the family's `example-device.yaml` into your ESPHome directory and rename it (the name
   becomes your device's hostname).
2. **Fill in `substitutions:`** — the UART pins and any family-specific knob (e.g. Hayward's
   transmit role `cmd_preamble`) — and the `esp32:` block's `board`/`variant`.
3. **Uncomment the equipment you have** in the `packages.rs485.files` list and **delete the rest**.
   The `bus.yaml` line is required — leave it uncommented. Each AUX channel is a `button.yaml` entry
   (the command) and/or a `led.yaml` entry (the status light); the menu shows the pairing.
4. **Add your secrets** — `wifi_ssid` / `wifi_password` to `secrets.yaml`. (Remote packages cannot
   contain `!secret`, so `wifi`/`api`/`ota` stay in the device file.)

The device config pulls the package files from this repo at a **pinned release tag**:

```yaml
packages:
  rs485:
    url: https://github.com/b3nj1/rs485_frame-examples
    ref: VX.X.X
    refresh: 1d
    files:
      - hayward/aqualogic/bus.yaml          # required
      # - hayward/aqualogic/pump-vsp.yaml   # uncomment what you have
```

The tag never moves, so an update only happens when you bump `ref:`. **Need to edit a decoder?** Copy
the package files into your config directory and switch those `files:` entries to local `!include`s —
your edits then stay local. See [CONTRIBUTING.md](CONTRIBUTING.md) for the composition details.

## Available configurations

One row per controller family; per-package descriptions and status live in that family's commented
`example-device.yaml` (the single source of truth).

| Controller family | Device config | Status |
|---|---|---|
| Hayward AquaLogic / ProLogic | [hayward/aqualogic/example-device.yaml](hayward/aqualogic/example-device.yaml) | Core (bus, nav buttons, temps, AUX 1-2) tested on hardware; AUX 3-14 and LED bits 9-25 are community-sourced (see file comments) |
| Hayward AquaLogic / ProLogic — switch-outputs variant | [hayward/aqualogic/example-device-switches.yaml](hayward/aqualogic/example-device-switches.yaml) | Sibling of the file above: toggleable relays (Lights, Filter, AUX 1-14, Valve 3/4, System Off, Service) are single optimistic `switch` entities instead of separate LED + button pairs. Pick one or the other, not both. Config-validated; not yet flashed as this combined file |
| Jandy AquaLink RS — passive observer | [jandy/aqualink-rs/example-passive.yaml](jandy/aqualink-rs/example-passive.yaml) | **UNTESTED draft** |
| Jandy AquaLink RS — active AllButton emulator | [jandy/aqualink-rs/example-allbutton.yaml](jandy/aqualink-rs/example-allbutton.yaml) | **UNTESTED draft — transmits** |

> **WARNING — UNTESTED:** The Jandy configurations are 100% untested and speculative. They have never
> been verified on physical hardware by anyone. The protocol bytes (notably the AllButton ACK third
> byte `0x80`), device addresses, CRC, and the ~60 ms poll-cycle ACK timing are community
> reverse-engineering guesses and may be wrong. The AllButton emulator actively transmits, so a wrong
> guess can disrupt a live controller. Use at your own risk, validate against your own captures, and
> please open an issue with results.

## Diagnostic tools for an unknown bus

If you are bringing up a controller that is not listed above, work through `generic/` in order:

| File | Description |
|---|---|
| [generic/discovery.yaml](generic/discovery.yaml) | Passive framing/CRC discovery for a completely unknown bus. Logs candidate `dle`/`stx`/`etx`, the escape scheme, and any matching CRC. Run this first when you don't know the framing bytes. |
| [generic/sniffer.yaml](generic/sniffer.yaml) | Passive sniffer with `sniffer_stats:` once you know the framing. Logs a periodic per-frame-type table (cadence, unique payloads) to catalog frame types. |
| [generic/skeleton.yaml](generic/skeleton.yaml) | Starting point for a single monolithic config. Raw-form buttons and `rs485_frame.send_frame` for computed payloads. |

These stay monolithic by design — there are no optional packages to compose for an unknown bus. Once
you have decoded the bus, package it up following [CONTRIBUTING.md](CONTRIBUTING.md) and submit it.
Hayward's packaged config set ships its diagnostic tools as an ordinary opt-in
package instead — `hayward/aqualogic/diagnostics.yaml`, enabled with one commented-out line in
`hayward/aqualogic/example-device.yaml` — rather than a separate monolithic device config. Other
packaged families (e.g. Jandy) don't have an equivalent yet.

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
