# discovery_capture.py

Offline trigger/response/ambient-state correlation over an ESPHome `dump_frames: true` log —
for deriving an on/off protocol signature from a captured `esphome logs` session, not for
consumption by another program. See the module docstring in `discovery_capture.py` for the full
design rationale.

## Usage

```
python3 discovery_capture.py <logfile> --config <config.yaml>
python3 discovery_capture.py --help    # full config-schema reference and worked examples
```

`crc_len` can be overridden on the command line with `--crc-len N` without editing the config;
`escape_mode`/`escape_byte` likewise with `--escape-mode`/`--escape-byte`.
`--config` itself is optional — with none given (or an empty `triggers`/`trackers`), you still get
a full RX/TX inventory (everything falls into `ORPHAN RX`), which is a reasonable way to start
looking at a capture you know nothing about yet before writing any config at all.

## Two ways to start: named buttons vs. blind discovery

You don't need to already know a bus's command bytes to get value out of this tool. A `triggers`
entry with `discover_bytes: N` is a wildcard: it matches a broad prefix (e.g. "some button was
pressed over the wireless preamble") and then auto-splits occurrences into one distinct, separately
reported bucket per observed value of the next N bytes — labeled `"{label} [xx..]"` — instead of
requiring every button to be named and enumerated by hand first. Once a bucket's meaning is
figured out from its bit/ascii diffs, promote it to a named `payload_prefix` trigger.

- `configs/hayward_aqualogic_discovery.yaml` — three wildcard triggers (wireless, wired-local,
  wired-remote preambles), no button names assumed at all. Run this first on an unfamiliar
  AquaLogic capture.
- `configs/hayward_aqualogic.yaml` — the nine wireless AquaLogic buttons, named, from
  `hayward/aqualogic/button.yaml`'s command table, plus an LED-Mask ambient tracker. Use once
  you've identified what you're looking at (or start here if you're already working from that
  table).

Both are validated against a real capture in `tests/test_bundled_configs.py`.

A caveat the discovery config's own tests pin down: pick `discover_bytes` wide enough. AquaLogic's
Lights and its AUX-relay commands share a first data byte of `0x00`, differing only in the *next*
byte — `discover_bytes: 1` would silently merge them into one bucket; `discover_bytes: 2` (what the
bundled config uses) separates them. A bucket with a suspiciously large occurrence count, mixing
what look like unrelated responses, used to be the only signal to widen it by hand — **`auto_split`
(on by default) now catches this case itself**: it diffs each bucket's own trigger-frame bytes
beyond whatever `payload_prefix`/`discover_bytes` already consumed, and if they're not constant
across the bucket's occurrences, splits it into labeled sub-buckets (`"{label} [xx] [yy]"`),
recursively — so a bucket that's still heterogeneous even one level deeper (a two-level collapse)
gets caught in the same run instead of requiring a second hand-added `discover_bytes` trigger. Set
`auto_split: false` in the config, or pass `--no-auto-split`, to get the old flat grouping back
(e.g. to match a hand-authored config's own intentional `discover_bytes` granularity without the
extra sub-bucket noise).

Another caveat specific to the broad wildcards a blind-discovery config leans on:
`until_next_trigger` (default on) closes a trigger's response window at the next occurrence of
**any** configured trigger, not just another occurrence of the *same* one — documented, intentional
behavior (it's what lets a busy capture's triggers not run each other's windows over). With the
narrow, hand-picked triggers of `configs/hayward_aqualogic.yaml` this rarely bites. But
`hayward_aqualogic_discovery.yaml`'s wildcards (`discover_bytes` on a short, broad prefix) are wide
enough to match most bus traffic, so in a busy capture — wired-panel activity happening during a
wireless-button test, or rapid-fire discovery probing — a genuinely slow-but-real ack for one
trigger can get truncated out of its own window because an unrelated trigger fires first, landing
in *that* trigger's window instead (or becoming an orphan) and making the original occurrence look
silent. The tool can't tell you this didn't happen; it can only tell you when it did — an
occurrence report line reading `window closed early at line N (trigger "...")` means exactly that:
don't trust that occurrence's `(no response)` at face value, go check what landed just after line
N. There's no config knob to disable this — the window-closing behavior itself is unchanged; only
the report's visibility into it is new.

## Trigger precedence

A single line can match more than one configured trigger — e.g. a named `"Filter"` trigger
(`payload_prefix: "00 83 01 80"`) and a broader `"wireless"` wildcard (`payload_prefix: "00 83 01"`,
`discover_bytes`) both match a real Filter-button press. Each line produces exactly one occurrence,
never more: **the longest matching `payload_prefix` wins** (the more specific trigger), with ties
(equal prefix length) broken by config list order, first-listed wins. `configs/hayward_aqualogic.yaml`
relies on this deliberately — it mixes named buttons with wildcard catch-alls for anything not yet
identified, in one file, and precedence is what keeps a named button's presses from also showing up
a second time under the wildcard's bucket.

**A response that also matches a trigger's own prefix is claimed by that trigger, not delivered as
a response.** A line gets exactly one role: either it's a trigger occurrence, or it's a response
candidate sitting inside some other trigger's open window — never both. So if a genuine ack for
trigger A's window happens to also match trigger B's matcher, it becomes its own B occurrence
instead of showing up in A's response groups: A reads `(no response)`/silent even though a real
reply arrived, and the reply surfaces looking like an unrelated B press. This is a known,
deliberate limitation (rs485_frame-206.3.11), not something the tool detects or warns about at
runtime — it was judged not worth the structural rework (merging window computation and occurrence
detection into one pass) relative to the risk on buses currently bundled here: every Hayward
AquaLogic ack uses frame_type `04 0a`, which is disjoint from the wireless/wired-local/wired-remote
wildcard prefixes (`00 83 01`/`00 02`/`00 03`), so no bundled config actually collides today. It's a
real risk for any bus/config where an ack could plausibly share a command's prefix family (e.g. a
future Jandy AquaLink RS config, or a Hayward config with wildcard prefixes broadened beyond what's
bundled) — if you're writing triggers for a bus like that, keep each wildcard's prefix scoped so it
can't also match that bus's own ack shape, or set `direction: tx` on a broad wildcard meant to
enumerate outgoing commands only, so an RX-originated ack can never be claimed by it.

## Config shape

```yaml
crc_len: 2
escape_mode: escape_byte   # double (default) | escape_byte
escape_byte: 0x00          # required when escape_mode is escape_byte
default_window_ms: 3000
default_until_next_trigger: true
ascii_min_run: 8
min_occurrences_for_signature: 2
keepalive_payloads: ["0101"]
triggers:
  - label: "Lights"
    payload_prefix: "00 83 01 00 01"
    match_mask: null
    direction: "any"
    window_ms: null
    until_next_trigger: null
    discover_bytes: 0
trackers:
  - label: "LED Mask"
    match_prefix: "01 02"
    offset: 2
    width: 4
    endian: "little"
```

- Both `triggers` and `trackers` are optional lists — omit either or both. Response bit/ascii-diff
  works with zero trackers configured (it diffs the raw RX response payloads within a trigger's
  windows); trackers only add the ambient-state snapshot and the before/after tracker-diff on top
  of that. There's no "trackers are required to get useful output" step.
- `payload_prefix`/`match_prefix` and `match_mask` are hex strings, whitespace-insensitive,
  matched against the logical (de-stuffed, CRC-stripped) payload — never the raw wire bytes.
- `direction: any` (the default) matches the same command regardless of whether it originated as
  an HA-issued `TX` or an OEM-panel-issued `RX` — set `tx`/`rx` to restrict a trigger to one side.
- `discover_bytes` — see "Two ways to start" above.
- `keepalive_payloads` is optional; if omitted, any RX payload repeated at least 5 times is
  auto-classified as ambient noise. This only ever affects whether a trigger occurrence is
  reported `(no response)` vs `(baseline-only response)` — a trigger whose only in-window RX is a
  baseline payload is `(baseline-only response)`, distinct from a truly silent trigger with no RX
  at all; a report's `SUMMARY` line breaks out both counts separately. Auto-classified payloads are
  never dropped from the response bit/ascii-diff, and the report prints an
  `AUTO-KEEPALIVE BASELINE` banner listing exactly which payload(s) got folded in and their
  whole-log repeat count, so a bus whose real ack happens to be a short, unvarying frame — and so
  crosses the auto-detect threshold during any session with many button presses — never reads as
  silent. If auto-detection folds in the wrong payload, override it by setting
  `keepalive_payloads:` explicitly (which also suppresses the banner, since a manually-specified
  baseline doesn't need to be surfaced back to you as a discovery).
- `crc_len` defaults to 2 (Hayward AquaLogic's `sum16_big_endian`); set to 1 for a single-byte
  CRC variant, or 0 to leave the CRC bytes in the logical payload untouched.
- `escape_mode` defaults to `double` (a literal DLE byte wire-stuffed as `DLE DLE`). Hayward's
  AquaLogic/ProLogic bus actually stuffs a literal DLE as `DLE` + a fixed marker byte instead
  (`escape_mode: escape_byte`, `escape_byte: 0x00` for Hayward) — both bundled Hayward configs
  set this. Get it wrong and any command whose payload byte happens to equal `0x10` (DLE) is
  silently dropped as an unparseable line rather than reported.
- A tracker's `offset` is the index of the field's **first byte on the wire** (its wire-earliest
  byte, at the lowest payload index), `width` is the field's length in bytes, and `endian` says
  how those `width` bytes at `[offset, offset+width)` combine into one integer:
  `endian: "little"` treats `payload[offset]` as the *least*-significant byte (and
  `payload[offset+width-1]` as most-significant); `endian: "big"` treats `payload[offset]` as the
  *most*-significant byte instead. Worked example, the bundled `LED Mask (01 02)` tracker
  (`match_prefix: "01 02"`, `offset: 2, width: 4, endian: "little"` — the field width and frame
  come straight from `hayward/aqualogic/bus.yaml`'s own `[0x01, 0x02]` decoder, an explicit
  32-bit little-endian mask, not guessed from observed values): payload bytes `[2:6]` are
  `e8 01 00 00` on the wire, and since `little` makes byte 2 the LSB, that decodes to `0x000001e8`
  — not `0xe8010000`, which is what `endian: "big"` would have produced from the same four bytes
  instead.

  `04 0a` is *not* a coincidental second carrier of the same field — it's a genuine tagged
  container frame under active investigation as a single-frame stand-in for the separate
  `01 02`/`01 03` pair (see `bus.yaml`'s own `[[0x01,0x02],[0x01,0x03],[0x04,0x0A]]` multi-dispatch
  handler): `payload[2:4]` is a constant `83 00` header, then a `0x02` tag byte means an 8-byte LED
  body follows immediately, and/or a `0x03` tag means display text follows — either sub-block can
  be absent, and the display sub-block's position shifts depending on whether the LED sub-block
  came first. A tracker at a bare fixed `offset: 5` would only be correct when the LED sub-block
  happens to be present there; it would silently misread arbitrary display-text bytes as the mask
  otherwise. The fix is to fold the tag byte into `match_prefix` itself —
  `match_prefix: "04 0a 83 00 02"` only ever matches (and therefore only ever extracts) when byte 4
  really is the `0x02` tag, guaranteeing `offset: 5` is genuinely the mask's first byte whenever it
  fires. The bundled config tracks both `LED Mask (01 02)` and `LED Mask (04 0a)` side by side for
  exactly this reason: if they ever disagreed at the same moment, that would be a real finding
  about `04 0a`'s reliability as positive confirmation, not something to average away into one
  tracker.

  `little` here is not a workspace-wide default — it's specific to this one RX status field,
  confirmed independently of the source comment: pressing Lights always flips wire byte 2's
  `0x40` bit, and only under `little` does that land on value bit 6, which is documented as
  "Lights" in `bus.yaml`'s own bit table; under `big` the same wire byte would land on bit 30,
  which isn't in that table at all. Elsewhere in this same protocol, `cmd_endian: "big"` governs
  how HA-issued *button commands* pack their 4-byte value into an outgoing TX frame — a different
  field, a different direction of travel, and a different byte order, not a contradiction. Don't
  assume one endianness for a whole protocol; get it from a decoder/spec (or verify it against a
  documented bit/field meaning, as here) per field.

### Per-bit/per-character flags: `kind`, `regions`, `bit`, `index_set`

A tracker's default `kind: scalar` (the `offset`/`width`/`endian` field above, backed by a single
top-level `match_prefix`) reads one fixed-offset integer. Some signals aren't one integer, though
— a per-character flag bit across a variable-length text span, or a mask that only means something
once ANDed against a second mask. Two more `kind`s cover that, both backed by a `regions` list
instead of a single `match_prefix`:

- `kind: flag_scan` — checks bit `bit` of every byte in the resolved region. A 1-byte region
  reports a plain bool (is the flag set); a wider region reports a tuple of the byte positions
  where it's set. `index_set`, if given, only counts a byte as flagged when its whole value is
  also a member of the set — this guards against misreading an unrelated odd value (the bit
  incidentally set) as the flag, on hardware/firmware generations where that byte carries a
  different meaning.
- `kind: paired_flag_and` — ANDs two consecutive `width`-byte spans starting at the region,
  bit-by-bit, reporting a tuple of the set bit positions. For a field that's really two masks back
  to back (e.g. a solid-state mask and a second mask), this is "which bits are set in both."

Each entry in `regions` is one place the field can be found, tried in order (first match wins):
either a direct offset from the end of that region's own `match_prefix` (the common case), or,
with `subblock_tag` set, the body of a tagged sub-block inside a container frame (Hayward's
`04 0a`, where `payload[2:4]` is a constant `83 00` header followed by an optional `0x02`-tagged
LED body and/or an optional `0x03`-tagged display-text body — see the worked `04 0a` example
above). `sub_offset` (default 0) then indexes further into whichever span was found, and `width`
is the field's length in bytes there (doubled automatically for `paired_flag_and`'s two spans).
This is how the same logical field — e.g. Hayward's 40-character display text, whose bit 7 per
character is a blink flag — gets tracked across both of its two frame shapes with one `TrackerDef`:
one region for the standalone `01 03` frame (`width: 40`, direct offset), one for `04 0a`'s `03`
sub-block (`subblock_tag: 0x03`, same `width: 40`).

An optional `note` on any tracker is printed as a caveat line under that tracker's diff in the
report — e.g. flagging that a signal is only meaningful on certain firmware/hardware generations.

## Report output

Each trigger occurrence shows its ambient tracker snapshot and the distinct RX payload groups
found in its response window. Below the occurrence list, two independent kinds of diff appear,
labeled to make clear which is which:

- **response diff** (`bit-diff`/`ascii-diff`) — computed from the raw RX response payloads
  themselves, grouped by payload shape (frame_type + length); each line includes an
  `example: <hex>` so the diff can be related back to an actual frame, and for bit-diff, the
  specific observed values at each varying byte position (not just an opaque XOR mask). Present
  even with zero trackers configured.
- **tracker diff** (`tracker-diff`) — only present per-tracker if that tracker is configured;
  aggregates each occurrence's (ambient-before, in-window-after) pair for that tracker across
  every occurrence of the trigger, showing which bits of the *tracked field* actually flip.

Once you know which frames matter (i.e. you have at least one tracker configured), pass
`--only-tracked` to drop every RX group — orphan or in-window — and every response bit-diff/
ascii-diff entry that doesn't match any tracker, so the report stops showing chatter you've
already identified as uninteresting. This is strictly by tracker byte-pattern match, including
ascii-decodable payloads that don't happen to match a tracker — `--only-tracked` means "only what
I configured a tracker for," not "or anything that looks like text."

## Tests

```
pip install -r requirements-dev.txt
pytest
```

Any defect found in this tool gets a failing test proving the defect before the fix lands — see
`tests/test_keepalive_baseline.py` for the pattern (a regression test written against a bug found
while building out the coverage-accounting tests, kept as the permanent guard against it
reappearing).

# validate_examples.py

Runs every entry-point `example-device*.yaml` (and the standalone `generic/*.yaml` configs)
through a real `esphome config` call — placeholders filled with dummy-but-valid values, every
independent optional equipment package enabled, `packages:`/`external_components:` pointed at a
local checkout instead of a released tag. Catches YAML/schema bugs in package files (e.g. a
duplicate top-level key) before they reach a user's build, which nothing else here checks: `pytest`
above only covers `discovery_capture.py`'s own config format, not these ESPHome device configs.

```
pip install esphome   # or: pip install -e /path/to/an/esphome/checkout
python3 tools/validate_examples.py --esphome-path /path/to/esphome/checkout
```

`--esphome-path` is optional — omit it to validate `external_components:` against whatever
released tag is currently pinned (a real network fetch) instead of a local checkout. `--examples-ref`
defaults to this repo's current HEAD commit; pass a released tag to instead validate exactly what a
user pulling that tag would get. Run automatically in CI (`.github/workflows/tests.yml`) against
the `b3nj1/esphome` fork's matching branch.
