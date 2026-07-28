# From an unknown bus to a working config

A narrative walkthrough for bringing up a DLE/STX/ETX-framed RS485 bus you know nothing about yet —
a pool/spa controller, or any similar half-duplex serial device that uses this style of framing. It
chains the three diagnostic tools in `generic/` into one flow: what each one tells you, and how that
feeds the next step. `README.md`'s
["Diagnostic tools for an unknown bus"](README.md#diagnostic-tools-for-an-unknown-bus) lists the
files; this doc is the order to run them in and what to look for.

If you already know your controller is Hayward AquaLogic/ProLogic or Jandy AquaLink RS, skip this —
use the family config under `hayward/` or `jandy/` directly (status and caveats are in each family's
`example-device.yaml`). This walkthrough is for a controller not listed there yet.

Throughout, [`captures/hayward-aqualogic-20260529.md`](captures/hayward-aqualogic-20260529.md) is
referenced as a concrete worked example — real log output from a real bring-up, not just what this
doc describes in the abstract. It is not something to copy verbatim (your bus will have different
frame types and byte values); it is here so you know what a normal run looks like.

## Before you start: wiring

You need physical access to the bus (RS485 A/B pair, plus GND if your controller exposes it) and a
transceiver on your ESP board wired the same way `README.md`'s
[hardware section](README.md#hardware) describes — the discovery and sniffer tools below capture
nothing if the transceiver's DE/RE direction pin is wrong, so get a config booting and idling first
before worrying about protocol details.

## Step 1: Discovery — find the framing

Flash [`generic/discovery.yaml`](generic/discovery.yaml). With `discovery:` present the hub does no
framing, validation, or transmission — it passively segments raw bytes into bursts by idle gap and,
every `interval` (default 30 s), reports:

- candidate `dle`/`stx`/`etx` delimiter bytes — the most common start/end byte pairs across bursts
- a framing confidence percentage (the weaker of the top start-pair and top end-pair vote share)
- whether the escape scheme could be confirmed (`double`, or `escape_byte` + marker) — often it
  cannot yet, if no payload happens to contain a literal DLE during the capture window
- any CRC scheme (`sum8`/`sum16`/`xor8`/`crc16_modbus`, header-inclusive or payload-only) that
  matches consistently across captured frames
- a ready-to-paste `framing:` block once confidence and CRC agree

If you do not know the baud rate either, uncomment `discovery.baud_sweep` in the file: it tries each
candidate baud (crossed with `data_bits_sweep`) for `dwell` (default 10 s) and locks onto the one
with the best framing confidence, tie-broken by CRC match. This needs ESP-IDF or ESP8266 (runtime
UART reconfiguration is not available elsewhere).

**What this step tells you, and why CRC — not framing confidence — is the tiebreaker:** the delimiter
bytes can survive a wrong data-bit width or a harmonic baud rate, so more than one candidate can reach
100% framing confidence. In the reference capture, `19200 8`, `19200 7`, and `38400 8` all did — but
only `19200 8` produced payloads whose CRC matched consistently; `19200 7` was silently dropping the
8th data bit and corrupting every payload despite framing perfectly. Trust the CRC match over the
confidence number whenever they disagree.

Escape scheme staying `unconfirmed` is a normal, correct result, not a failure — it just means no
payload byte happened to equal `DLE` during the capture window. Start with the escape mode your
protocol family is known to use (Hayward: `escape_byte` with marker `0x00`) if you have that
information from elsewhere; otherwise leave discovery running longer, since a longer capture is more
likely to catch a payload DLE.

**End of Step 1, you have:** baud rate, data bits, `dle`/`stx`/`etx`, a CRC scheme (or `none` if
nothing matched — see the sniffer note below), and possibly a confirmed escape scheme. Parity and
stop bits are never determined here — they cannot be detected passively, since a receiver decodes
fine even when parity/stop bits disagree with what the sender used. They only start to matter once
you transmit; if your commands are ignored later, try `EVEN` parity or `stop_bits: 2` before assuming
something else is wrong.

## Step 2: Sniffer — catalog the frame types

Flash [`generic/sniffer.yaml`](generic/sniffer.yaml) with the framing (and CRC, if found) from Step
1 filled in. If Step 1 found no CRC match, set `crc: {type: none}` for now — the sniffer will accept
every structurally valid frame regardless of checksum, which is fine for cataloging; add the real CRC
scheme once you know it. With `sniffer_stats:` enabled, the hub logs a periodic table, one row per
distinct frame type, every `interval`:

```
type  cnt    d-ref(min/med/max)    d-same(min/med/max)   payloads
```

- **`cnt`** — how many frames of this type arrived in the window.
- **`d-ref`** — milliseconds from the configured `reference_frame_type` to this frame. `-` for the
  reference frame itself.
- **`d-same`** — milliseconds between consecutive frames of the same type; a tight, low-jitter
  `d-same` at high frequency is the signature of a keep-alive or poll frame.
- **`payloads`** — how many distinct payloads this frame type has carried (`+N` if more arrived than
  the capture buffer held).

**What this step tells you:** run it twice — once idle, once while operating the controller (press
buttons on its own keypad/remote, not through your ESPHome device, since you have no commands wired
up yet). Diffing the two runs separates the bus's constant background traffic (status polling, a
keep-alive) from the frame types that only appear under user action (key/state reports, display
updates). The reference capture shows this clearly: on an idle Hayward bus, `0101` is the highest
frequency and tightest-jitter frame by a wide margin — that is the keep-alive, and it is what you
want as both `reference_frame_type` and (later) `tx.gate.frame_type`. Adding remote button presses
made a new frame type (`0083`) appear that was completely absent on the idle bus, riding in tight
lockstep just after the keep-alive — a strong signal that it is the state/key report.

Frame types with mostly-ASCII payloads (readable in the `|...|` column) are the easy first wins —
you can often identify what a frame means just by reading the text, before writing a single line of
decoder code. Binary frames need the next step.

## Step 3: Move to a transmitting config, hand-verify a CRC, then write decoders

Discovery and sniffer are deliberately receive-only, and that matters for what comes next.
`generic/discovery.yaml` never transmits by design, and `generic/sniffer.yaml` additionally sets
`sniffer_only: true` and `dump_frames: false` to stay passive — a hub running either config can never
log a TX line, because it never sends anything. Verifying a CRC by hand needs the TX side (below), so
this is the point where you leave the sniffer-only tools behind and move to
[`generic/skeleton.yaml`](generic/skeleton.yaml) — a real transmitting starting config, with
`dump_frames: true` already on and at least one raw `frame_type:`/`payload:` button to build from.

Fill in `skeleton.yaml`'s `rs485_frame:` block with the framing/CRC/gate you found in Steps 1-2, and
point one of its buttons' `frame_type:`/`payload:` at bytes you actually saw on the bus in Step 2 —
replaying a sequence you already watched the real controller or its own remote send is far lower risk
on live hardware than guessing a command. Flash it and press that button once. The hub logs the exact
frame it wrote, e.g. `TX 100200830100010000000100000000981003`. Now you have a CRC to check by hand:
verify it before trusting it — this catches byte-offset mistakes (an off-by-one in where the
frame_type ends and data begins is the most common one) before they propagate into every decoder you
write. `on_frame:`/`sniffer_stats` payloads cannot be used for this — the CRC is already stripped from
them before your lambda or the stats table ever sees the bytes (that is what makes decoder lambdas
simple); the TX log is the only place the CRC bytes are visible, logged as the complete frame — DLE,
STX, payload, CRC, DLE, ETX — exactly as written to the wire. The reference capture's
[CRC walkthrough](captures/hayward-aqualogic-20260529.md#verifying-the-crc-by-hand) shows the full
arithmetic for `sum16_big_endian header_inclusive` against a TX line in this same format — the same
method applies to whichever CRC type Step 1 found for your bus.

With framing, CRC, and a catalog of frame types in hand, write `on_frame:` lambdas for the types you
care about, starting with the ASCII display frames if you have any (least effort per frame). Two
rules that matter for correctness, not just style:

- **Offsets are payload-relative.** By the time your lambda runs, DLE+STX, escapes, and the CRC are
  already gone. `payload[0..N-1]` is the frame_type (`N` = however many bytes you configured); data
  starts at `payload[N]`. This trips people up when porting offsets from a community reference that
  counts from the first data byte instead of the frame_type — add the frame_type length to translate.
- **No heap allocation, guard `payload.size()`, never block.** These lambdas run on the hub's RX
  path; the full rationale and more decoder patterns are in
  [`CONTRIBUTING.md`](CONTRIBUTING.md#8-decoder-rules-and-the-offset-convention).

`skeleton.yaml` starts with `tx.gate.mode: idle_gap` (transmit once the bus has been silent for
`min_silence`), which needs no keep-alive frame and is a reasonable default while you are still
reverse-engineering. Once you know the keep-alive/poll frame from Step 2, switch to
`tx.gate.mode: frame_trigger` and set both `tx.gate.frame_type` and `reference_frame_type` to it —
that schedules transmits at a known-safe point in the bus's cycle instead of just "the bus went
quiet," which matters once other devices (a controller's own remote, a second bus master) are
sharing the line.

## Once you have something working

Package it up following [`CONTRIBUTING.md`](CONTRIBUTING.md) — the bus-package/equipment-profile
split, the metadata header, and the PR checklist all live there — and consider publishing your own
annotated capture from [`captures/TEMPLATE.md`](captures/TEMPLATE.md) so the next person bringing up
the same controller has a worked example, the way the Hayward one did for this doc.
