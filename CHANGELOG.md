# Changelog

All notable changes to the published configuration interface are documented here. This project uses
[Semantic Versioning](https://semver.org/) against the **public interface**: file paths, the hub
`id:`, substitution names/semantics (and which are required), and entity `id:`/`name:`. See
[CONTRIBUTING.md](CONTRIBUTING.md#8a-versioning-and-breaking-changes) for the rules.

- **MAJOR** — change a file path, hub `id`, substitution, or entity `id`/`name`.
- **MINOR** — additive: a new profile file, a new optional substitution *with a default*, a new entity.
- **PATCH** — decoder or bug fix with no interface change.

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

[3.0.1]: https://github.com/b3nj1/rs485_frame-examples/compare/v3.0.0...v3.0.1
[3.0.0]: https://github.com/b3nj1/rs485_frame-examples/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/b3nj1/rs485_frame-examples/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/b3nj1/rs485_frame-examples/releases/tag/v1.0.0
