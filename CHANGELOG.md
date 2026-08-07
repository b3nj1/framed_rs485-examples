# Changelog

All notable changes to the published configuration interface are documented here. This project uses
[Semantic Versioning](https://semver.org/) against the **public interface**: file paths, the hub
`id:`, substitution names/semantics (and which are required), and entity `id:`/`name:`. See
[CONTRIBUTING.md](CONTRIBUTING.md#8a-versioning-and-breaking-changes) for the rules.

- **MAJOR** — change a file path, hub `id`, substitution, or entity `id`/`name`.
- **MINOR** — additive: a new package file, a new optional substitution *with a default*, a new entity.
- **PATCH** — decoder or bug fix with no interface change.

## [4.0.0] - 2026-08-06

### Changed

- **`cmd_element_bytes` default changed from `"4"` to `"1"`; all `button_command` values now
  explicit byte arrays.** Each `button_command:` entry in `example-device.yaml` is now an unquoted
  YAML list of individual bytes, in the order they're sent on the wire, instead of a list of 4-byte
  hex words. E.g. `[0x80000000, 0x80000000]` becomes `[0x80, 0x00, 0x00, 0x00, 0x80, 0x00, 0x00,
  0x00]`. This removes the confusing "element_bytes / truncation" concept entirely: every list entry
  is now literally what a bus sniff shows. **Backward compatibility:** existing user configurations
  that define custom `button_command` values must either rewrite them to byte-array form or
  explicitly override `cmd_element_bytes: "4"` in their own device config to keep the old 4-byte
  mode. (github.com/b3nj1/rs485_frame-examples#3)

- **New `hayward/aqualogic/secondary_button.yaml` package** for buttons requiring a different wire
  format — specifically, the wired-local preamble `[0x00, 0x02]` needed by legacy-firmware
  (main board v2.85) menu/display-centric buttons (Service, Plus, Minus, Lights, Menu, Left,
  Right). Supersedes the old `btn_element_bytes: "2"` override guidance documented in the
  3.2.0-rc1 pass. `secondary_button.yaml` reads the same `${secondary_cmd_*}` substitutions
  (`secondary_cmd_preamble`, `secondary_cmd_postamble`, `secondary_cmd_element_bytes`) which
  `example-device.yaml` supplies with wired-local defaults. Auxiliary relay buttons (Filter,
  Pool/Spa Mode, AUX 1-14, Valve 3-4) remain unaffected and work fine on both firmware generations
  with the standard wireless preamble. (github.com/b3nj1/rs485_frame-examples#3)

---

## [3.2.0] - 2026-08-04

### Added

- **`hayward/aqualogic/bus.yaml`: row-split display view.** New `display_cols` substitution
  (default `20`, matching this repo's own hardware-verified 2x20 captures) and four new template
  text sensors, `Display Row 1`-`Row 4` (rows 3/4 disabled by default), splitting the existing
  `Display` sensor's text into LCD-width rows instead of one concatenated line. The existing
  `Display`/`Display Blink` sensors and the temperature/chlorinator/salt-level/filter-speed
  parsing are unchanged and still read the full unsplit text, since a parsed pattern can straddle
  a row boundary. Panels that wrap at a different width (e.g. 16 chars, reported on a legacy
  v2.85 unit) should override `display_cols`.
  (github.com/b3nj1/rs485_frame-examples#2)

- **`hayward/aqualogic/diagnostics.yaml`** (new optional package). Opt-in diagnostic tools
  for the `pool` hub: adds both `sniffer_stats:` (periodic per-frame-type statistics table)
  and `dump_frames:` (per-frame raw logging) via `id: !extend pool`. Uncomment its line in
  `example-device.yaml`'s `packages.rs485.files:` list to enable either or both. Ships with
  hardware-tuned defaults for the stats table that lived in the now-removed `sniffer.yaml`
  (`interval: 30s`, `max_frame_types: 32`, `max_unique_payloads: 24`, `payload_capture_bytes: 48`,
  `payload_dump_top: 8`), now exposed as optional `vars:` (`stats_interval`,
  `stats_max_frame_types`, `stats_max_unique_payloads`, `stats_payload_capture_bytes`,
  `stats_payload_dump_top`) plus a new `dump_frames_enable` var (default `"false"`) to toggle
  per-frame logging. Vars can be overridden per-device without editing the packaged file.
  `reference_frame_type: [0x01, 0x01]` and `ascii_strip_high_bit: true` are unchanged and
  not exposed as vars — they're Hayward protocol facts, not tuning knobs.

### Removed

- **`hayward/aqualogic/sniffer.yaml`.** Standalone, non-packaged diagnostic tool; never referenced
  via any `packages.files:` list, so no packaged device config is affected. Its tuning now ships as
  the opt-in package `hayward/aqualogic/diagnostics.yaml` (see Added, above). If you
  built directly off the old file (copied it, or pointed a local `!include` at it) rather than using
  the packaged `bus.yaml` + `example-device.yaml` flow, switch to `example-device.yaml` and uncomment
  the `hayward/aqualogic/diagnostics.yaml` line in its `packages.rs485.files:` list — the same
  tuned values are there unchanged.

- **`hayward/aqualogic/bus.yaml`: hardcoded `dump_frames: false` removed.** The line only duplicated
  the component's own schema default (`false`), so it was redundant on its own terms. Toggling this
  feature is now available via `hayward/aqualogic/diagnostics.yaml`'s `dump_frames_enable` var.

### Documentation

- **`hayward/aqualogic/button.yaml`, `hayward/aqualogic/example-device.yaml`: legacy-firmware
  (main board v2.85) 2-byte button note.** Documents a community report that menu/display-centric
  buttons (Service, Plus, Minus, Lights, Menu, Left, Right) are ignored by legacy-firmware
  mainboards unless sent as 2-byte frames (`btn_element_bytes: "2"`) instead of the 4-byte
  default; auxiliary relay buttons are unaffected. No default behavior changed — this is guidance
  plus the derived 2-byte values for users who hit it, not independently verified on this repo's
  own (newer-firmware) hardware.
  (github.com/b3nj1/rs485_frame-examples#3)

- **`Role:` header taxonomy renamed to follow ESPHome's own `packages:` vocabulary.** `bus package` +
  `equipment profile` → `package (required)` / `package (optional)`; `snippet` → `package as
  template` (ESPHome's own term, see [Packages as Templates](https://esphome.io/components/packages/#packages-as-templates));
  `standalone tool` → `device config (no remote packages)`; `device config` → `device config with
  remote packages`. `contributor skeleton` is unchanged (an ESPHome-neutral concept). `templates/`
  renamed to `skeletons/` to match and to remove the collision with the new `package as template`
  term. Every file's `Role:` line and `CONTRIBUTING.md`'s terminology table (§2, §7) updated to
  match; not a behavior change, and none of the renamed files are ever referenced via any
  `packages.files:` list, so no published interface path breaks.

## [3.0.2] - 2026-08-01

### Fixed

- aqualogic bug fix to v3.0.1: start payload at first character after frame type for display messages
  without padding. Otherwise the first char was dropped.

---
## [3.0.1] - 2026-07-26

### Fixed

- **Compile warning in `hayward/aqualogic/bus.yaml`**. The LED-mask lambda's
  `snprintf(hex_buf, sizeof(hex_buf), "0x%08X", mask)` passed a `uint32_t` (`long unsigned int`) to a
  `%X` conversion expecting `unsigned int`, producing a `-Wformat=` warning on ESP32 builds. Cast to
  `unsigned int` before formatting. No interface change.

---

## [3.0.0] - unreleased

### Changed

- **`value:` replaces `command:` on buttons** (breaking). All button entities now use `value:`
  instead of `command:`. Scalar or list form are both accepted: `value: 0x80000000` or
  `value: [0x80000000, 0x80000000]`.

- **`button_command` substitution is now a required list** (breaking). In
  `hayward/aqualogic/button.yaml` includes, `button_command` must be a YAML list of one or two
  hex values `[press, release]` — use the same value twice for a standard toggle. This replaces
  the previous scalar form and the removed `command_repeat` feature. Bus captures show Hayward's
  press and release halves can legitimately differ (e.g. simultaneous Left+Right press
  `0x05000000` followed by a Left-only release `0x04000000`), which `command_repeat` could not
  represent.

- **`value_element_bytes:` replaces `command_size:` inside `command_format:`** (breaking). The
  sub-key that specifies how many bytes each value element occupies on the wire is now
  `value_element_bytes: 4`. Valid values are `1`, `2`, `3`, or `4`.

- **`endian:` replaces `command_endian:` inside `command_format:`** (breaking). Shortened for
  consistency now that the `command_` prefix is removed from the block's other sub-keys.

- **`command_repeat:` removed from the `rs485_frame` component** (breaking for any config that
  set it explicitly). Remove the key; the list-mode `value:` above replaces its purpose.

- **New per-button `value_element_bytes:` override** (additive). A button may carry a top-level
  `value_element_bytes:` key to override only the element byte width while inheriting the hub's
  preamble, endian, and postamble. Mutually exclusive with a per-button `command_format:` block.

### Migration from 2.0.0

1. For each `button.yaml` include in your device config, change `button_command: 0x80000000` to
   `button_command: [0x80000000, 0x80000000]` (or the distinct press/release pair, if applicable).
2. For any inline `platform: rs485_frame` button entry, rename `command:` to `value:`.
3. In any `command_format:` block (hub-level or per-button), rename `command_size:` to
   `value_element_bytes:` and `command_endian:` to `endian:`.
4. If you added `command_repeat:` yourself, remove it.
5. Bump your package ref to `ref: v3.0.0`.

---

## [2.0.0] - 2026-06-05

### Changed

- **uart block moved to device config** (breaking for users upgrading from 1.0.0). The `uart:`
  block is no longer defined inside `hayward/aqualogic/bus.yaml` or `jandy/aqualink-rs/bus.yaml`.
  It must be declared directly in the device config with `id: pool_uart` (Hayward) or
  `- id: pool_uart` (Jandy). The family-specific constants (baud rate, data bits, parity,
  stop bits, rx_buffer_size) belong there too. The `jandy/aqualink-rs/allbutton.yaml`
  `uart: !extend` for `flow_control_pin` is likewise removed.

- **`substitutions:` now contains all user-facing setup values**: `name`, `friendly_name`,
  `board`, `tx_pin`, `rx_pin`, and `flow_control_pin` are all declared there as `BOARDXX` /
  `GPIOXX` placeholders. The `esp32:` and `uart:` blocks reference them via `${...}` and no
  longer need editing. To omit `flow_control_pin` (auto-direction adapters), delete the
  substitution and the `flow_control_pin: ${flow_control_pin}` line from the `uart:` block.

- **Placeholder values** changed from literal GPIO numbers and a specific board identifier to
  `GPIOXX` and `BOARDXX` throughout all config examples, matching the ESPHome documentation
  convention. ESPHome validation rejects these strings, ensuring users replace them before flash.

### Migration from 1.0.0

1. Add a `uart:` block directly to your device config **before** the `packages:` block, using
   `id: pool_uart` (Hayward) or `- id: pool_uart` (Jandy). Copy the family-specific baud/parity
   settings from the updated `example-device.yaml` (or Jandy equivalent).
2. Move `tx_pin`, `rx_pin`, and `flow_control_pin` into your `substitutions:` block with their
   real pin values. The `uart:` block references them via `${tx_pin}` etc.
3. Add `board` to `substitutions:` and change `esp32: board:` to `${board}`.
4. Bump your package ref to `ref: v2.0.0`.

---

## [1.0.0] - 2026-05-30

Initial released interface. Restructured the monolithic per-controller YAMLs into composable
[ESPHome `packages`](https://esphome.io/components/packages/): a per-family **bus package** plus one
**equipment profile** per piece of gear, assembled by a thin **device config**.

### Added

- `hayward/aqualogic/`: `bus.yaml` (hub: UART 19200 8N2, sum16_big_endian CRC, gate `[0x01,0x01]`,
  wireless `command_format`, panel LEDs + display + diagnostics + service button), `pump-vsp.yaml`,
  `heater.yaml`, `button.yaml` (parameterized nav/AUX buttons), `led.yaml` (parameterized LED
  binary sensor), and `example-device.yaml`.
- `jandy/aqualink-rs/` (UNTESTED drafts): `bus.yaml` (passive base), `leds-display.yaml`, `swg.yaml`,
  `epump.yaml`, `heater.yaml`, `allbutton.yaml` (active emulator), `example-passive.yaml`,
  `example-allbutton.yaml`.
- `templates/bus.yaml` and `templates/profile.yaml` skeletons with the standard metadata header.
- `CONTRIBUTING.md` (authoring guide), `captures/TEMPLATE.md` (capture publishing template), and a
  `## Contributors` section on the existing Hayward capture.

### Changed

- `hayward/aqualogic.yaml` → split into the `hayward/aqualogic/` package set.
- `hayward/sniffer.yaml` → `hayward/aqualogic/sniffer.yaml` (stays a monolithic diagnostic tool).
- `jandy-UNTESTED-DRAFT/` → `jandy/aqualink-rs/`. UNTESTED status now lives in each file's `Status`
  header and the README catalog, not the directory name.
- `README.md` rewritten for consumers (assemble-a-device-config flow + family catalog); decoder rules
  and the offset convention moved to `CONTRIBUTING.md`.
- `generic/` discovery / sniffer / skeleton remain monolithic bootstrap tools (exempt from the
  package structure) with header notes pointing at it for real integrations.

[3.2.0]: https://github.com/b3nj1/rs485_frame-examples/compare/v3.0.2...v3.2.0
[3.0.2]: https://github.com/b3nj1/rs485_frame-examples/compare/v3.0.1...v3.0.2
[3.0.1]: https://github.com/b3nj1/rs485_frame-examples/compare/v3.0.0...v3.0.1
[3.0.0]: https://github.com/b3nj1/rs485_frame-examples/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/b3nj1/rs485_frame-examples/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/b3nj1/rs485_frame-examples/releases/tag/v1.0.0
