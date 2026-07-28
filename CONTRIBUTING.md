# Contributing configurations

This guide is for **contributors** who are reverse-engineering a controller and authoring reusable
config files for the library. If you just want to *use* an existing controller config, see the
[README](README.md) instead.

The library is built so that no two installations have to share a hand-edited file. A contributor
authors small, composable package files; an end user assembles a device config from them by listing
the equipment they have. This document explains how to author those files.

## 1. Scope and the single layering style

Standardize on ESPHome [`packages`](https://esphome.io/components/packages/). A device config pulls
reusable files in via `packages:` — remote git packages (pinned tag) by default, or local copies as
a fallback for users who must edit a decoder. **Do not mix `!include` / `packages` / `!extend`
styles across configs**: equipment profiles extend the shared hub with `!extend` (see below), and
that is the only place `!extend` appears.

**Exempt: diagnostic / bootstrap tools.** `generic/discovery.yaml`, `generic/sniffer.yaml`,
`generic/skeleton.yaml`, and the per-family `sniffer.yaml` are single-purpose tools for an *unknown*
bus — there are no equipment profiles to compose yet, so they stay monolithic and self-contained.

## 2. Terminology and repo layout

"Device" is reserved for the ESPHome node (matching the ESPHome / Home Assistant dashboard's own
usage). RS485 bus members are called **equipment**, never "devices." The phrase "device profile" is
not used.

| Term | What it is | Reusable? | Edited by | Example |
|---|---|---|---|---|
| **Device config** | The complete ESPHome config for one physical ESP board: `substitutions` + `wifi`/`api`/`ota`/secrets + a `packages:` list. The only file flashed. | No (per-installation) | End user | `hayward/aqualogic/example-device.yaml` |
| **Quickstart** | A device config, but fixed to core entities only (`bus.yaml` alone, no equipment `files:` entries) and pinned to one hardware path. Exists to make first flash turnkey; `example-device.yaml` stays the full menu. | No (per-installation, or copied as-is for the pinned board) | End user | `hayward/aqualogic/quickstart-waveshare.yaml` |
| **Bus package** | The shared RS485 hub for a controller family: `uart`, `framing`, `crc`, `tx`, `command_format` + panel-wide entities. One per family. | Yes | Contributor | `hayward/aqualogic/bus.yaml` |
| **Equipment profile** | One piece of equipment, keyed on the `frame_type`s it owns. Contributes `on_frame` decoders + its own entities. | Yes | Contributor | `pump-vsp.yaml`, `swg.yaml` |
| **Opt-in add-on** | Not included by any device config or quickstart by default; a user adds it deliberately, per call site, alongside the feature it extends. Marked EXPERIMENTAL (or similar) in its header when the behavior carries a real tradeoff the default install shouldn't take on silently. | Yes (paired with the file it extends, by matching var, e.g. `button_id`) | Contributor | `hayward/aqualogic/confirm-retry.yaml` |

Layout: each controller family lives at `vendor/controller-family/` and holds `bus.yaml`, one file
per equipment profile, `example-device.yaml` (one per operating mode where relevant, e.g. Jandy
passive vs. allbutton), and, where offered, one or more `quickstart-*.yaml` files and opt-in
add-ons. Reusable skeletons live in `templates/`; captures in `captures/`.

**File naming:** lowercase, hyphenated, named for the equipment (`pump-vsp.yaml`, `heater.yaml`,
`leds-display.yaml`) or, for a quickstart, the hardware path it targets (`quickstart-waveshare.yaml`,
`quickstart-discrete.yaml`). `bus.yaml` and `example-device.yaml` are fixed names.

## 3. The pluggable unit

An **equipment profile is the set of `frame_type`s it owns** — in either direction. A variable-speed
pump owns both the controller→pump command frame (Hayward `0x0c 0x01`) and the pump→bus report frame
(`0x00 0x0c`); both belong in `pump-vsp.yaml`. Keying on owned frames composes cleanly on a
panel-mediated bus (Hayward) and a poll-response bus (Jandy) alike.

A profile **may** contain:

- A partial hub entry that extends the shared hub by id (decoders only — see §4).
- Its own entities (`sensor`, `binary_sensor`, `text_sensor`, `button`, ...).

A profile **must not** contain `uart`, `framing`, `crc`, `command_format` (except where it converts a
passive base to active — see §6), or any `!secret`. Those belong to `bus.yaml` / the device config.

**The `bus.yaml` contract.** The bus package owns the bus-wide required hub fields (`uart`,
`framing`, `crc`, `tx`, optionally `command_format`) and panel-wide entities. It declares the hub
with a plain `id:` (e.g. `id: pool`); every profile and entity references that id.

## 4. Composition mechanics

ESPHome merges packages with `merge_config`: dicts merge key-by-key, and **lists are concatenated** —
there is *no* automatic "merge components by id." To add to an existing component, use ESPHome's
[`!extend`](https://esphome.io/components/packages/#extend):

```yaml
# bus.yaml — declares the hub
rs485_frame:
  - id: pool
    uart_id: pool_uart
    framing: { escape: { mode: escape_byte, byte: 0x00 } }
    crc: { type: sum16_big_endian, tx_variant: header_inclusive }
    # ...
```

```yaml
# pump-vsp.yaml — adds to it
rs485_frame:
  - id: !extend pool          # <-- REQUIRED. A bare `id: pool` creates a SECOND hub and fails.
    on_frame:
      - frame_type: [0x0c, 0x01]
        then: [ lambda: !lambda "..." ]
```

`!extend pool` finds the hub declared in `bus.yaml` and merges the profile's dict into it; because
`on_frame` is a list, the profile's handlers are concatenated onto the hub's. Several profiles can
extend the same hub, each adding its own `on_frame` handlers and entities, and they all land in one
merged hub.

**Shared-frame decoding rule.** The hub fires **every** `on_frame` handler whose `frame_type` prefix
matches a received frame, not just the first. So one frame type can be decoded by several profiles:
the Hayward LED-mask frame `0x01 0x02` is registered by `bus.yaml` (panel bits + display sensors)
and `heater.yaml` (heater active bit). `led.yaml` does not add an `on_frame` handler; instead it
polls the `g_led_mask` global that `bus.yaml` updates on every `0x01 0x02` frame. **Register one
`on_frame` handler per profile, guard only your own bytes/bits, and never assume sole ownership of
a frame type.**

## 5. The substitution contract

A device config's `substitutions:` block contains everything the user fills in at setup time:
`name`, `friendly_name`, `board`, `tx_pin`, `rx_pin`, `flow_control_pin`, and any values packages
consume via `${...}`. The `esphome:`, `esp32:`, and `uart:` blocks are static templates that
reference substitutions via `${...}` and should not need editing. The sole exception is
`flow_control_pin`: if your adapter auto-manages RS485 direction, delete the `flow_control_pin`
substitution and the `flow_control_pin: ${flow_control_pin}` line from the `uart:` block. Per-vendor substitutions that packages consume (e.g. a
transmit-role command preamble,
temperature units) are documented in that family's `bus.yaml` header. **Scalar substitutions**
follow last-write-wins, so defaults for purely scalar knobs (e.g. `temp_unit`) live in `bus.yaml`
and are overridden in the device config. **Exception: keep logically related knobs together.** All
four `command_format` knobs (`cmd_preamble`, `cmd_postamble`, `cmd_element_bytes`, `cmd_endian`) live in the
device config — none are defaulted in `bus.yaml` — so the transmit role is fully self-contained in
one place and contributors cannot accidentally split it.

**Two substitution gotchas, both verified with `esphome config`:**

1. **List-valued substitutions must be defined in exactly ONE place — the device config.** When the
   same list substitution is set in both a package file and the device config, ESPHome
   *concatenates* the two lists rather than overriding (`[0x00,0x83,0x01,0x00,0x83,0x01]`, not an
   override). A list-valued knob like a command preamble **must not be defaulted in a package file**;
   reference it whole-value (`preamble: ${cmd_preamble}`) and require the device config to supply it
   as an unquoted YAML list: `cmd_preamble: [0x00, 0x83, 0x01]`.
2. **`${var}` cannot appear inside a YAML flow sequence/mapping.** `preamble: [${cmd_preamble}]` and
   `esphome: { name: ${name} }` fail to parse (the `{` in `${...}` confuses the flow parser). Use
   block style (`esphome:` then `  name: ${name}`) or whole-value substitution (`preamble:
   ${cmd_preamble}` with `cmd_preamble` declared as a real YAML list).

**Secrets stay in the device config.** Remote git packages cannot contain `!secret`, so
`wifi`/`api`/`ota` and their secret lookups live in the device file.

## 6. Superset handling and role/mode selection

**AUX / VALVE channels — packages-as-template.** Rather than ship a bloated enabled-by-default
superset, the Hayward set splits a channel into two small parameterized templates, each included
once per channel: `button.yaml` (the command) and `led.yaml` (the status bit). The device config
lists the ones it has:

```yaml
files:
  - hayward/aqualogic/bus.yaml
  - path: hayward/aqualogic/button.yaml
    vars: { button_name: "AUX 1", button_command: [0x00020000, 0x00020000] }
  - path: hayward/aqualogic/led.yaml
    vars: { bit: 7, led_name: "AUX 1", device_class: running, disabled_by_default: "true" }
```

`button.yaml` adds one button that sends `button_command` through the hub's `command_format`;
`led.yaml` adds one binary_sensor that polls `g_led_mask` bit `${bit}` (it adds no `on_frame`
handler — `bus.yaml` maintains the mask). Keeping the command and the status bit as separate
includes lets a device expose a button with no status LED, or a status LED with no button. For
local-copy use the `!include` form works the same:
`!include { file: led.yaml, vars: { bit: 7, led_name: "AUX 1" } }`. A template file may carry a
`defaults:` block supplying `vars` not provided by the include.

**Vendor role / mode selection.** Prefer a substitution over separate files when the difference is a
few bytes. Hayward's wireless/wired transmit role is the `${cmd_preamble}` substitution (a one-line
edit in the device config; verified values are listed in `hayward/aqualogic/bus.yaml`). When the
difference is structural (passive observer vs. active emulator), use a small profile that **extends**
the base: Jandy's `allbutton.yaml` flips `sniffer_only: false`, adds `command_format` + `tx`, and
extends the base. The device config's `uart:` block owns all pin config including the optional
`flow_control_pin`; the passive and active example device configs both show this.

## 6a. Keep the example menu complete (obligation)

`example-device.yaml` is the consumer's runnable, commented "menu" of every profile for a family.
**When you add a bus package or equipment profile, add its commented `packages:` line — a one-line
description + `Status: tested|UNTESTED` — to that family's `example-device.yaml`(s).** The bus line
stays uncommented (it is mandatory). This keeps the consumer-facing menu authoritative; the PR
checklist gates on it.

This obligation does not extend to `quickstart-*.yaml` files — they are deliberately fixed to
`bus.yaml` alone (see the Quickstart row in the terminology table above) and never gain equipment
`files:` entries as profiles are added. A new profile needs an `example-device.yaml` line; it does
not need a quickstart change.

## 7. Templates and the standard metadata header

Two skeletons live in `templates/`: `templates/bus.yaml` (bus package) and `templates/profile.yaml`
(equipment profile). Copy the matching one when authoring a new file.

Every reusable file (`bus.yaml`, equipment profiles, and the `templates/*` skeletons) opens with the
**full** standard metadata header:

```yaml
# =============================================================================
# <Vendor> <Controller family> — <bus package | equipment profile: NAME>
# -----------------------------------------------------------------------------
# Status:      tested-on-hardware | UNTESTED-draft
# Tested on:   <controller model>, firmware <rev>; <ESP board>; ESPHome <x.y.z>;
#              rs485_frame <component version / git ref>
# Bus:         <baud> baud, <data><parity><stop>   (e.g. 19200 8N2)
# Owns frames: <frame_type list this file decodes/sends>  (bus package: gate + command frames)
# Offsets:     payload-relative — payload[0..N-1] = frame_type, data starts at payload[N]
# References:  <reverse-engineering source links>
#
# Contributors:
#   - <Name (@handle)> — <contribution>  <link>
# =============================================================================
```

`example-device.yaml` carries a **lighter** header — `Status`, `Tested on` (the exact system the
author verified), and `Contributors` — because frame ownership / offsets / references live in the
packages it pulls in.

## 8. Decoder rules and the offset convention

**Offset convention: payload-relative.** `payload[0]` is the first byte of the `frame_type` prefix.
For a 2-byte frame_type the first data byte is `payload[2]`. The `payload` vector the lambda receives
has already had the DLE+STX preamble stripped, escapes unwrapped, and CRC removed — but the
frame_type bytes are still at the start.

Community references often strip the frame_type before counting, so their "byte 0" is our
`payload[2]`. When porting offsets, add the frame_type length (usually 2) to translate.

| Source | Their "byte 0" of the frame | Equivalent in our `payload[]` |
|---|---|---|
| **`rs485_frame`** (this component) | first byte of the frame_type | `payload[0]` |
| [swilson/aqualogic](https://github.com/swilson/aqualogic) | first byte after the frame_type | `payload[2]` (2-byte frame_type) |
| [earlephilhower/aquaweb](https://github.com/earlephilhower/aquaweb) | mixed; see the Python source | translate per-field |
| Raw bus capture (dump_frames log) | `DLE` itself | DLE+STX stripped before `payload[0]` |

When you publish findings, state the convention explicitly ("offsets are payload-relative:
`payload[0..1]` = frame_type, data starts at `payload[2]`").

**`on_frame` lambda best practices** — no heap allocation, always guard `payload.size()` before
indexing, and never block. The full list with rationale lives on the
[hub component page](https://esphome.io/components/rs485_frame/); follow it for every decoder.

**Only build a sensor for a value the bus reports reliably, not for whatever a session happened to
catch on the display.** A sniffer capture will incidentally decode all kinds of menu/settings
screens (a heater setpoint, a schedule, a config value) that only appear on the display while
someone is actively standing at the panel navigating to them — unlike Pool/Spa/Air Temp, which
rotate through the display on their own. A sensor built from a screen like that goes stale the
moment the menu is left, and HA has no way to tell "not seen since boot" from "confirmed value from
six weeks ago" unless you also add a `timeout:` filter (`esphome/components/sensor/filter.py`) to
make the gap visible. Default to **not** shipping the sensor at all for anything that isn't
reliably periodic; if you do ship one anyway, it must be `disabled_by_default: true` and carry a
`timeout:` filter, not just a throttle.

## 8a. Versioning and breaking changes

Pointing users at this repo makes the package files a **published interface**. The breaking surface
is: file **paths**, the hub **`id:`** (entities use `rs485_frame_id:`), **substitution
names/semantics** and which are required, and entity **`id:` / `name:`** (Home Assistant entity_ids
and users' automations derive from these).

**Guardrails:**

1. **Pinned tags only.** Every published example uses `ref: vX.Y.Z` (an immutable release tag), never
   a branch. A tag never moves, so `refresh:` cannot deliver a surprise; users opt in by bumping the
   one `ref:`.
2. **Single-ref mapping form.** One `remote_package` block (`url:` + `ref:` + `files:`) per device
   config, so the ref lives in one place and the commented menu + aux `vars` entries share it.
3. **Semver against the interface.** MAJOR = change a path / hub id / substitution / entity
   id-or-name. MINOR = additive (new profile file, new optional scalar substitution with a default,
   new entity). PATCH = decoder/bugfix. Additive-by-default: within a major line never hard-delete or
   rename a referenced file or entity; any new required substitution must ship a default if scalar,
   or be documented as required-in-device-config if list-valued (list defaults in packages
   concatenate rather than override — see §5).
4. **`CHANGELOG.md` + migration notes** for every breaking change.
5. **Bump every affected `example-device*.yaml`'s pinned `ref:`** when cutting a tag. The tag itself
   doesn't propagate anywhere automatically — each family's example device file (currently
   `hayward/aqualogic/example-device.yaml`, `jandy/aqualink-rs/example-passive.yaml`,
   `jandy/aqualink-rs/example-allbutton.yaml`) hardcodes `ref: vX.Y.Z` and stays on the old tag until
   someone edits it. Grep `ref: v` across the repo before tagging a release and bump every hit whose
   package files changed in that release.

## 9. `external_components` / staging ref

`rs485_frame` is not yet in an ESPHome release. Every standalone config (quickstarts,
`example-device.yaml`, the Jandy examples, `generic/*.yaml`) carries its own `external_components`
block; within a device config assembled from `bus.yaml` as a remote package it lives **once, in
`bus.yaml`** — equipment profiles must not repeat it (`external_components` is a list and would
duplicate). Remove the block entirely when `rs485_frame` ships in an official ESPHome release.

**Pin the component the same way the guardrails in §8a pin the examples: an immutable tag, never
the `rs485_frame` branch directly.** The branch is the live PR/development target and moves under
active fixes; `github://b3nj1/esphome@rs485_frame` in a shipped example would let a reflash pull in
different component code with no change on the examples side, which is exactly the `refresh:`
surprise §8a guardrail 1 exists to prevent. Instead:

1. When cutting an examples release whose package files depend on component-side behavior, commit
   the component changes on the fork's `rs485_frame` branch, then tag that commit
   `rs485_frame-<YYYYMMDD>` (date of the tag, not necessarily the release) and push both the branch
   and the tag.
2. Point every `external_components: source:` at that tag, not the branch. Grep
   `b3nj1/esphome@rs485_frame` across the repo before tagging a release and bump every hit.
3. State the pairing in `CHANGELOG.md`: which component tag a given examples release was tested
   against (see §8a's changelog format). A capture doc's "software versions used" table is an
   exception — it documents what was actually running at capture time and should not be rewritten
   to point at a tag that didn't exist yet.

## 10. UNTESTED policy

Status lives in the header's `Status` field and the README catalog badge — **not** in a directory
name. For untested or actively-transmitting configs (e.g. the Jandy drafts), keep the strong warning
banner at the top of each file and in the README catalog. Never silently promote a draft to "tested"
without a capture to back it.

## 11. Capture publishing

Publish a capture for any new controller. Start from [`captures/TEMPLATE.md`](captures/TEMPLATE.md)
and require: controller model, firmware revision(s), bus parameters, ESP board, ESPHome version, and
the `rs485_frame` component version; a `## Contributors` credit table; and a `Status` row. **Scrub
custom display text** (pool/spa names, schedule text) before sharing. The worked example is
[`captures/hayward-aqualogic-20260529.md`](captures/hayward-aqualogic-20260529.md).

## 12. PR checklist

- [ ] Standard metadata header present (full on packages/profiles/templates; lighter on
      `example-device.yaml`), and the `Status` field is accurate.
- [ ] Config validates: `esphome config` passes on a device config that includes the new file.
- [ ] Equipment profile extends the hub with `id: !extend <hub>` (not a bare `id:`), defines no
      `uart`/`framing`/`crc`/`secret`, and guards every `payload.size()`.
- [ ] New profile / bus added as a commented `packages:` line (description + Status) to the family's
      `example-device.yaml`(s); bus line kept uncommented.
- [ ] Capture attached for a new controller (`captures/`), with contributors credited.
- [ ] No duplicated `external_components` block (only `bus.yaml` has it).
- [ ] **Touches the public interface (paths / hub id / substitutions / entity id-or-name)? → MAJOR
      version bump + `CHANGELOG.md` entry + migration note.**

For how end users consume this library, see the [README](README.md).
