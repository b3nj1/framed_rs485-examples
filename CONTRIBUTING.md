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
styles across configs**: optional packages extend the shared hub with `!extend` (see below), and
that is the only place `!extend` appears.

**Exempt: diagnostic / bootstrap tools.** `generic/discovery.yaml`, `generic/sniffer.yaml`, and
`generic/skeleton.yaml` are single-purpose device configs for an *unknown* bus, with no `packages:`
block — there are no optional packages to compose yet, so they stay monolithic and self-contained.
Hayward, the one family with tuned diagnostic tools, ships them as an ordinary
opt-in optional package (`hayward/aqualogic/diagnostics.yaml`) instead of a separate monolithic
tool — other packaged families (e.g. Jandy) don't have an equivalent yet, but the same pattern
applies whenever one is added.

## 2. Terminology and repo layout

"Device" is reserved for the ESPHome node (matching the ESPHome / Home Assistant dashboard's own
usage). RS485 bus members are called **equipment**, never "devices." The phrase "device profile" is
not used.

Role names follow ESPHome's own `packages:` vocabulary ([Local/Remote Packages](https://esphome.io/components/packages/),
[Packages as Templates](https://esphome.io/components/packages/#packages-as-templates)) rather than
inventing new terms, with two ESPHome-neutral additions: a required/optional qualifier on `package`
(ESPHome doesn't distinguish these; this repo's family-per-directory layout needs to), and
`contributor skeleton` (a concept specific to this repo, not an ESPHome one).

| Term | What it is | Reusable? | Edited by | Example |
|---|---|---|---|---|
| **Device config** (`with remote packages` / `(no remote packages)`) | The complete ESPHome config for one physical ESP board: `substitutions` + `wifi`/`api`/`ota`/secrets, plus a `packages:` list for families that have one. The only file flashed. | No (per-installation) | End user | `hayward/aqualogic/example-device.yaml` (with remote packages); `generic/sniffer.yaml` (no remote packages) |
| **Package (required)** | The shared RS485 hub for a controller family: `uart`, `framing`, `crc`, `tx`, `command_format` + panel-wide entities. One per family; its `packages:` line stays uncommented. | Yes | Contributor | `hayward/aqualogic/bus.yaml` |
| **Package (optional)** | One piece of equipment, keyed on the `frame_type`s it owns, contributing `on_frame` decoders + its own entities — or, for a diagnostics-only package, a non-decoder hub key instead (e.g. `sniffer_stats:` in `hayward/aqualogic/diagnostics.yaml`). Typically commented out by default in the device config's `packages:` list, though a specific device config may keep one uncommented when it doesn't make sense without it — see §7. | Yes | Contributor | `pump-vsp.yaml`, `swg.yaml`, `diagnostics.yaml` |
| **Package as template** | A package included via `path:` + `vars:`, parameterized per inclusion — ESPHome's own term for this pattern. | Yes | Contributor | `button.yaml`, `led.yaml`, `response_monitor.yaml` |
| **Contributor skeleton** | Copy-and-fill starting point for a new controller family; not usable as-is. | N/A | Contributor | `skeletons/bus.yaml`, `skeletons/profile.yaml` |

Layout: each controller family lives at `vendor/controller-family/` and holds `bus.yaml`, one file
per optional package, and `example-device.yaml` (one per operating mode where relevant, e.g. Jandy
passive vs. allbutton). Reusable skeletons live in `skeletons/`; captures in `captures/`.

**File naming:** lowercase, hyphenated, named for the equipment (`pump-vsp.yaml`, `heater.yaml`,
`leds-display.yaml`). `bus.yaml` is a fixed name. Every device config filename is prefixed
`example-` — `example-device.yaml` for a single-mode family, or `example-<mode>.yaml` (e.g. Jandy's
`example-passive.yaml` / `example-allbutton.yaml`) when a family ships more than one operating mode.
The prefix is what marks a file as "the one you flash" at a glance; no other file kind uses it.

## 3. The pluggable unit

An **optional package's identity is the set of `frame_type`s it owns** — in either direction. A
variable-speed pump owns both the controller→pump command frame (Hayward `0x0c 0x01`) and the
pump→bus report frame (`0x00 0x0c`); both belong in `pump-vsp.yaml`. Keying on owned frames composes
cleanly on a panel-mediated bus (Hayward) and a poll-response bus (Jandy) alike.

An optional package **may** contain:

- A partial hub entry that extends the shared hub by id (decoders only — see §4 — except a
  diagnostics-only package's entry, which may instead be a non-decoder key like `sniffer_stats:`).
- Its own entities (`sensor`, `binary_sensor`, `text_sensor`, `button`, ...).

An optional package **must not** contain `uart`, `framing`, `crc`, `command_format` (except where it
converts a passive base to active — see §6), or any `!secret`. Those belong to `bus.yaml` / the
device config.

**The `bus.yaml` contract.** The required package owns the bus-wide required hub fields (`uart`,
`framing`, `crc`, `tx`, optionally `command_format`) and panel-wide entities. It declares the hub
with a plain `id:` (e.g. `id: pool`); every optional package and entity references that id.

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

`!extend pool` finds the hub declared in `bus.yaml` and merges the optional package's dict into it;
because `on_frame` is a list, the package's handlers are concatenated onto the hub's. Several
optional packages can extend the same hub, each adding its own `on_frame` handlers and entities, and
they all land in one merged hub.

**Shared-frame decoding rule.** The hub fires **every** `on_frame` handler whose `frame_type` prefix
matches a received frame, not just the first. So one frame type can be decoded by several optional
packages: the Hayward LED-mask frame `0x01 0x02` is registered by `bus.yaml` (panel bits + display
sensors) and `heater.yaml` (heater active bit). `led.yaml` does not add an `on_frame` handler;
instead it polls the `g_led_mask` global that `bus.yaml` updates on every `0x01 0x02` frame.
**Register one `on_frame` handler per package, guard only your own bytes/bits, and never assume sole
ownership of a frame type.**

## 5. The substitution contract

A device config's `substitutions:` block contains everything the user fills in at setup time:
`name`, `friendly_name`, `tx_pin`, `rx_pin`, `flow_control_pin`, and any values packages
consume via `${...}`. The `esphome:` and `uart:` blocks are static templates that
reference substitutions via `${...}` and should not need editing. The sole exception is
`flow_control_pin`: if your adapter auto-manages RS485 direction, delete the `flow_control_pin`
substitution and the `flow_control_pin: ${flow_control_pin}` line from the `uart:` block.
The `esp32:` block's `board`/`variant` are filled in directly (not substitutions) — ESPHome
Device Builder raised a non-fatal error on the indirected `${board}` form, and `variant` matters
more than `board` per the ESP32 platform docs (it must match the hardware to flash; `board` is
mostly cosmetic pin-mapping). Per-vendor substitutions that packages consume (e.g. a
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
2. **Unquoted `${var}` cannot appear inside a YAML flow sequence/mapping.** `preamble: [${cmd_preamble}]`
   and `esphome: { name: ${name} }` fail to parse (the `{` in `${...}` confuses the flow parser). For a
   list-valued substitution, use block style (`esphome:` then `  name: ${name}`) or whole-value
   substitution (`preamble: ${cmd_preamble}` with `cmd_preamble` declared as a real YAML list). For a
   single scalar value inside an otherwise-compact `vars: { }` entry, quoting it side-steps the same
   parse ambiguity and keeps the one-line form: `vars: { bit: "${bit_aux1}", led_name: "AUX 1" }` parses
   fine, because YAML strips the quotes before ESPHome's substitution pass ever sees the value — quoted
   or not, it resolves identically.

**Secrets stay in the device config.** Remote git packages cannot contain `!secret`, so
`wifi`/`api`/`ota` and their secret lookups live in the device file.

## 6. Superset handling and role/mode selection

**AUX / VALVE channels — package as template.** Rather than ship a bloated enabled-by-default
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
difference is structural (passive observer vs. active emulator), use a small optional package that
**extends** the base: Jandy's `allbutton.yaml` flips `sniffer_only: false`, adds `command_format` +
`tx`, and extends the base. The device config's `uart:` block owns all pin config including the
optional `flow_control_pin`; the passive and active example device configs both show this.

## 6a. Keep the example menu complete (obligation)

`example-device.yaml` is the consumer's runnable, commented "menu" of every package for a family.
**When you add a required or optional package, add its commented `packages:` line — a one-line
description + `Status: tested|UNTESTED` — to that family's `example-device.yaml`(s).** The required
package's line stays uncommented (it is mandatory). This keeps the consumer-facing menu
authoritative; the PR checklist gates on it.

## 7. Skeletons and the standard metadata header

Two skeletons live in `skeletons/`: `skeletons/bus.yaml` (required package) and
`skeletons/profile.yaml` (optional package). Copy the matching one when authoring a new file.

Every reusable file (`bus.yaml`, optional packages, and the `skeletons/*` skeletons) opens with the
**full** standard metadata header:

```yaml
# =============================================================================
# <Vendor> <Controller family> — <bus | NAME>
# -----------------------------------------------------------------------------
# Role:        package (required) | package (optional) | contributor skeleton
# Status:      tested-on-hardware | UNTESTED-draft
# Tested on:   <controller model>, firmware <rev>; <ESP board>; ESPHome <x.y.z>;
#              rs485_frame <component version / git ref>
# Bus:         <baud> baud, <data><parity><stop>   (e.g. 19200 8N2)
# Owns frames: <frame_type list this file decodes/sends>  (required package: gate + command frames)
# Offsets:     payload-relative — payload[0..N-1] = frame_type, data starts at payload[N]
# References:  <reverse-engineering source links>
#
# Contributors:
#   - <Name (@handle)> — <contribution>  <link>
# =============================================================================
```

`example-device.yaml` carries a **lighter** header — `Role`, `Status`, `Tested on` (the exact system
the author verified), and `Contributors` — because frame ownership / offsets / references live in the
packages it pulls in.

**`Role:`** is a single line, one of four base values: `device config`, `package`, `package as
template`, or `contributor skeleton`. Two of these always carry a qualifier:

- `device config` is suffixed `with remote packages` or `(no remote packages)`, depending on whether
  the file has a `packages:` block.
- `package` is suffixed `(required)` or `(optional)`. `(required)` is reserved for the family's
  shared hub — always `bus.yaml`, exactly one per family. Every other package is `(optional)`, even
  one a specific device config keeps uncommented by default because that config doesn't make sense
  without it (e.g. Jandy's `allbutton.yaml` in `example-allbutton.yaml`) — optional describes the
  package's role in the taxonomy, not whether any single device config happens to enable it.

Every file in scope for this convention carries a `Role:` line, not only the files with the full
header above. Two file kinds have no `Status:` field to sit `Role:` next to, so it goes elsewhere in
their existing prose style rather than restructuring the header: `generic/discovery.yaml`,
`generic/sniffer.yaml`, and `generic/skeleton.yaml` (`device config (no remote packages)`) put it as
the very first `##` line of the file; `hayward/aqualogic/button.yaml` and `led.yaml` (`package as
template`) put it as the first line inside their existing boxed banner, immediately after the title
separator and before the descriptive prose.

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
| Raw bus capture, or `dump_frames` log (full wire frame — framing and CRC included) | `DLE` itself | `payload[0]` is the log's 3rd byte (`DLE`+`STX` stripped) |

When you publish findings, state the convention explicitly ("offsets are payload-relative:
`payload[0..1]` = frame_type, data starts at `payload[2]`").

**`on_frame` lambda best practices** — no heap allocation, always guard `payload.size()` before
indexing, and never block. The full list with rationale lives on the
[hub component page](https://esphome.io/components/rs485_frame/); follow it for every decoder.

## 8a. Versioning and breaking changes

Pointing users at this repo makes the package files a **published interface**. The breaking
surface is defined by a principle, not a fixed list: **any named identifier reachable via
`id(...)` in user-authored lambda code is part of the breaking surface**, exactly as much as an
entity's Home Assistant `entity_id` is — renaming one is never just an internal implementation
detail, because a user's own lambda code, automation, or dashboard may already reference it.
File **paths** and **substitution names/semantics** (and which substitutions are required) are
breaking for the same underlying reason: they're names a user's own config already references.

Known examples of this surface today (non-exhaustive — reason from the principle above for any
identifier type not yet listed here, including ones invented later, e.g. a new `script: id:` or a
new component's `id:`): file **paths**, the hub **`id:`** (entities use `rs485_frame_id:`),
**substitution names/semantics** and which are required, entity **`id:` / `name:`** (Home
Assistant entity_ids and users' automations derive from these), and **`globals: id:`** (a user's
own lambda code can reference it via `id(...)`, same as an entity id/name).

**Guardrails:**

1. **Pinned tags only.** Every published example uses `ref: vX.Y.Z` (an immutable release tag), never
   a branch. A tag never moves, so `refresh:` cannot deliver a surprise; users opt in by bumping the
   one `ref:`.
2. **Single-ref mapping form.** One `remote_package` block (`url:` + `ref:` + `files:`) per device
   config, so the ref lives in one place and the commented menu + aux `vars` entries share it.
3. **Semver against the interface.** MAJOR = change a path / hub id / substitution / entity
   id-or-name. MINOR = additive (new package file, new optional scalar substitution with a default,
   new entity). PATCH = decoder/bugfix. Additive-by-default: within a major line never hard-delete or
   rename a referenced file or entity; any new required substitution must ship a default if scalar,
   or be documented as required-in-device-config if list-valued (list defaults in packages
   concatenate rather than override — see §5).
4. **`CHANGELOG.md` + migration notes** for every breaking change.
5. **`ref:` pins track this repo's own releases.** Each family's example device file (currently
   `hayward/aqualogic/example-device.yaml`, `jandy/aqualink-rs/example-passive.yaml`,
   `jandy/aqualink-rs/example-allbutton.yaml`) hardcodes `ref: vX.Y.Z` in its `remote_package`
   block, pointing at an immutable tag of this same repo. It always matches the current release —
   a stale `ref:` would mean new content in this repo doesn't reach anyone using that file as their
   starting point, so this is checked before every release regardless of which family's own
   package files changed that cycle.
6. **Add the `CHANGELOG.md` footer link every time a version heading is added.** Each `## [X.Y.Z]`
   heading is a Markdown reference link — it only renders as a link if a matching
   `[X.Y.Z]: https://github.com/b3nj1/rs485_frame-examples/compare/v<prev>...vX.Y.Z` definition
   exists at the bottom of the file. Adding a heading without its footer line silently leaves a
   broken link; there is no lint that catches this, so it must be done by hand at the same time as
   the heading, not deferred to "tagging time" (three versions in a row — 4.0.0, 4.0.1, 4.0.2 — were
   missed this way because nothing said to do it until this guardrail was added).
7. **`external_components: source: github://b3nj1/esphome@vX.Y.Z` pins track the `esphome` fork's
   own release**, kept current the same way and for the same reason as guardrail 5's `ref:` above —
   every real `source:` field (not the illustrative `@rs485_frame` example in `skeletons/bus.yaml`)
   matches the current release, regardless of which example families changed that cycle.

## 9. `external_components` / staging ref

`rs485_frame` is not yet in an ESPHome release. The `external_components` block (pointing at the
staging branch) lives **once, in the flashable file** — the device config (`example-device.yaml`,
`example-passive.yaml`, `example-allbutton.yaml`) or a device config with no remote packages
(`generic/*.yaml`). `bus.yaml` is never flashed directly — it is package content pulled in via a
device config's `packages.files:` list, which is its real distinguishing trait — so it never carries
this block, and neither does any package. Remove the block entirely once `rs485_frame` ships in an
official ESPHome release.

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

- [ ] Standard metadata header present (full on packages/skeletons; lighter on device configs with
      remote packages; `Role:`-only in existing prose style on package-as-template files and device
      configs with no remote packages), and the `Role` and `Status` fields are both accurate.
- [ ] Config validates: `esphome config` passes on a device config that includes the new file.
- [ ] An optional package extends the hub with `id: !extend <hub>` (not a bare `id:`), defines no
      `uart`/`framing`/`crc`/`secret`, and guards every `payload.size()`.
- [ ] New package added as a commented `packages:` line (description + Status) to the family's
      `example-device.yaml`(s); the required package's line kept uncommented.
- [ ] Capture attached for a new controller (`captures/`), with contributors credited.
- [ ] No duplicated `external_components` block (only the flashable file — a device config — has it;
      never `bus.yaml` or an optional package).
- [ ] **Touches the public interface (paths / hub id / substitutions / entity id-or-name)? → MAJOR
      version bump + `CHANGELOG.md` entry + migration note.**

For how end users consume this library, see the [README](README.md).
