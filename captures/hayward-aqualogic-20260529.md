# Hayward AquaLogic — real discovery and sniffer capture

A real-world bring-up capture from a Hayward (Goldline) AquaLogic controller, walked through from
"I know nothing about this bus" to decoded frames. Every CRC below is verified by hand so you can
follow the same steps on your own controller.

## Contributors

Credit everyone who captured, reverse-engineered, or verified this data. Add yourself when you
extend it.

| Contributor | Contribution | Link |
|---|---|---|
| b3nj1 (@b3nj1) | Capture, baud sweep, CRC verification, frame decode | https://github.com/b3nj1 |
| swilson | Hayward wireless-remote frame layout and key encoding | https://github.com/swilson/aqualogic |

## Capture metadata

| | |
|---|---|
| Controller | Hayward / Goldline AquaLogic |
| Main software revision | 4.47 |
| Display software | RFRemote-04 r4.01 |
| VSP filter display software | r10.15 |
| VSP filter drive software | r0.73 |
| RF base software | r3.00, ID `6DCC` |
| Board | Waveshare ESP32-S3-RS485-CAN (ESP32-S3) |
| ESPHome | 2026.5.1 |
| rs485_frame | github://b3nj1/esphome@rs485_frame |
| Bus | 19200 baud, 8 data bits (parity/stop determined separately — see below) |
| Date | 2026-05-29 |
| Status | tested-on-hardware |

> The firmware revisions above come from the controller's on-panel **Diagnostic** screen. They
> also appear on the wire in frame type `0x0004` — see [Version / ID frame](#version--id-frame-0x0004).

> **Scrub before publishing your own capture.** This controller exposes only generic Hayward menu
> strings (`Settings`, `Lights`, `Air Temp 62_F`, ...). If yours shows a custom pool/spa name or
> schedule text, redact it. Bus traffic never carries WiFi credentials, but ASCII display frames
> can carry whatever you typed into the controller.

## Step 1: Discovery with a baud sweep

Config: `generic/discovery.yaml` with `discovery.baud_sweep` enabled. The hub knows nothing — no
baud rate, framing bytes, escape scheme, or CRC. It sweeps the candidate line settings, scores the
framing at each, and locks onto the best.

```
[I][app:151]: ESPHome version 2026.5.1 compiled on 2026-05-29 20:46:45 -0700
[I][app:158]: ESP32 Chip: ESP32-S3 rev0.2, 2 core(s)
[I][rs485_frame.discovery]: Baud sweep result: 9600 baud 7 data bits  -> framing confidence 86%,  no CRC match,   0 frames
[I][rs485_frame.discovery]: Baud sweep result: 9600 baud 8 data bits  -> framing confidence 85%,  no CRC match,   0 frames
[I][rs485_frame.discovery]: Baud sweep result: 19200 baud 7 data bits -> framing confidence 100%, no CRC match, 128 frames
[I][rs485_frame.discovery]: Baud sweep result: 19200 baud 8 data bits -> framing confidence 100%, CRC matched,  121 frames
[I][rs485_frame.discovery]: Baud sweep result: 38400 baud 7 data bits -> framing confidence 100%, no CRC match,   2 frames
[I][rs485_frame.discovery]: Baud sweep result: 38400 baud 8 data bits -> framing confidence 100%, no CRC match,  18 frames
[I][rs485_frame.discovery]: Baud sweep complete: locked to 19200 baud, 8 data bits (framing confidence 100%, CRC matched). Continuing discovery at these settings.
[I][rs485_frame.discovery]: RS485 discovery: collecting traffic (55 bursts, 60 frames so far)
...
[I][rs485_frame.discovery]: RS485 discovery (cumulative since boot): 337 bursts, 371 frames extracted
[I][rs485_frame.discovery]:   Framing: DLE=0x10 STX=0x02 ETX=0x03  (confidence 100%, start pair x337, end pair x337 of 337 bursts)
[I][rs485_frame.discovery]:   Escape: unconfirmed - no in-frame DLE observed in 337 bursts. Capture longer / busier
[I][rs485_frame.discovery]:   CRC match: sum16_big_endian header_inclusive (unescaped) - 371/371 frames
[I][rs485_frame.discovery]:   CRC match: sum16_big_endian header_inclusive (raw wire bytes) - 371/371 frames
[I][rs485_frame.discovery]:   Suggested uart config (from sweep; parity/stop_bits not passively detectable):
[I][rs485_frame.discovery]:     uart:
[I][rs485_frame.discovery]:       baud_rate: 19200
[I][rs485_frame.discovery]:       data_bits: 8
[I][rs485_frame.discovery]:   Suggested framing/escape config:
[I][rs485_frame.discovery]:     framing:
[I][rs485_frame.discovery]:       dle: 0x10
[I][rs485_frame.discovery]:       stx: 0x02
[I][rs485_frame.discovery]:       etx: 0x03
[I][rs485_frame.discovery]:       # escape: unconfirmed - no DLE seen inside a payload yet; capture more traffic
```

What this run teaches:

- **Why CRC is the tiebreaker, not framing confidence.** Three candidates reached 100% framing
  confidence: `19200 8`, `19200 7`, and `38400 8`. The delimiter bytes (`10 02 ... 10 03`) survive
  at a wrong data-bit width or a harmonic baud, so confidence alone cannot pick the winner. Only
  `19200 8` produced bytes whose `sum16_big_endian` checksum agreed across every frame, so it wins. A wrong
  baud or data-bit width corrupts the payload, and no checksum can match consistently on garbage.
- **`19200 7` is the trap.** It framed 128 frames at 100% confidence but matched no CRC — the
  8th data bit was being dropped, corrupting every payload. Without the CRC tiebreak you could
  easily have locked to the wrong width.
- **Escape stays `unconfirmed`.** Hayward only stuffs a `0x00` after a payload `0x10`, which is
  rare, so none occurred in this window. That is correct behavior: discovery declines to guess.
  Start with `escape: {mode: escape_byte, byte: 0x00}` (the known Hayward value); it is a no-op
  until a payload DLE actually appears.

Detected so far: **19200 baud, 8 data bits, DLE=`0x10` STX=`0x02` ETX=`0x03`, CRC = sum16_big_endian
header-inclusive.** Parity and stop bits are not passively detectable; on this
controller they are `NONE` / `2` (8N2), determined later by transmitting (see the README note on
iterating parity/stop if commands are ignored).

## Step 2: Sniffer — idle bus (no remote commands)

Config: `generic/sniffer.yaml` with `sniffer_stats:` and the framing/CRC from Step 1. This is the
bus with nobody pressing buttons — just the controller's steady polling.

```
[I][rs485_frame.stats]: RS485 sniffer stats over 30002 ms (sorted by count):
[I][rs485_frame.stats]:   type  cnt    d-ref(min/med/max)    d-same(min/med/max)   payloads
[I][rs485_frame.stats]:   0101   301        -     -     -       59   100   134   1 unique
[I][rs485_frame.stats]:   0C01    15       28    31    33     1996  2000  2020   1 unique
[I][rs485_frame.stats]:   000C    15       37    37    38     1999  2000  2016   1 unique
[I][rs485_frame.stats]:   040A    15       81    82    86     1995  2000  2017   1 unique
[I][rs485_frame.stats]:   0102    15       90    90    95     1995  2000  2016   1 unique
[I][rs485_frame.stats]:   0103    15      119   119   120     1999  2000  2017   1 unique
[I][rs485_frame.stats]:   0004     3       34    35    36       98   103   103   3 unique
[I][rs485_frame.stats]:   0407     1       33    33    33        -     -     -   1 unique
[I][rs485_frame.stats]:   04A0     1       32    32    32        -     -     -   1 unique
[I][rs485_frame.stats]:   04AE     1       28    28    28        -     -     -   1 unique
[I][rs485_frame.stats]:   0101 payloads:
[I][rs485_frame.stats]:       301 @ 01 01 00 14  |....|
[I][rs485_frame.stats]:   0C01 payloads:
[I][rs485_frame.stats]:        15 @ 0C 01 00 00 00 1F  |......|
[I][rs485_frame.stats]:   000C payloads:
[I][rs485_frame.stats]:        15 @ 00 0C 00 00 00 00 00 00 1E  |.........|
[I][rs485_frame.stats]:   040A payloads:
[I][rs485_frame.stats]:        15 @ 04 0A 83 00 02 08 00 00 00 00 00 00 00 03 20 20 20 20 20 20 53 65 74 74 69 6E 67 73 20 20 20 20  |..............      Settings    |
[I][rs485_frame.stats]:   0102 payloads:
[I][rs485_frame.stats]:        15 @ 01 02 08 00 00 00 00 00 00 00 00 1D  |............|
[I][rs485_frame.stats]:   0103 payloads:
[I][rs485_frame.stats]:        15 @ 01 03 20 20 20 20 20 20 53 65 74 74 69 6E 67 73 20 20 20 20 20 20 20 20 20 20 20 20 20 20 4D 65  |..      Settings              Me|
```

Reading the table:

- **Columns.** `cnt` = frames seen this 30 s window. `d-ref` = ms from the reference frame (the
  keep-alive) to this frame. `d-same` = ms between consecutive frames of the same type. `payloads`
  = distinct payloads captured (`+N` = more arrived than the capture buffer held).
- **`0101` is the keep-alive.** Highest count (~10/s), `d-ref` is `-` (it *is* the reference), and
  its `d-same` is a tight 59/100/134 ms — exactly the "high frequency, low jitter" signature you
  look for when you do not yet know the reference frame. Its payload never changes (`1 unique`).
  This is the frame to use as `tx.gate.frame_type` and `reference_frame_type`.
- **The ~2000 ms cluster.** `0C01`, `000C`, `040A`, `0102`, `0103` each arrive once every ~2 s
  (`d-same` ~2000) at staggered offsets from the keep-alive (`d-ref` 28→119 ms). This is the
  controller's round-robin status/display refresh.

### Verifying the CRC by hand

> **Note on the payload tables above.** The `payloads` columns in Step 2/3 show `rx_payload_` — the
> bytes an `on_frame:` lambda sees. Today that stops before the CRC (`rs485_frame.cpp:394`), so a
> current capture would print two bytes fewer per row than shown above (e.g. `0101` would read
> `01 01`, not `01 01 00 14`). The tables are kept as originally captured rather than re-run, but it
> means they can no longer be hand-CRC-verified directly — the CRC bytes just are not in them.

To hand-verify a CRC you need the CRC bytes, and those only ever appear on the **TX side**. Enable
`dump_frames: true` and the hub logs the complete frame it writes to the wire — `DLE STX
<escaped payload> <escaped CRC> DLE ETX` — exactly as sent, with nothing stripped
(`rs485_frame.cpp:602-606`). The example below is from a later capture of this same bus
(`debug.040a.20260726.log`, taken during the send-monitoring work — the discovery/sniffer run above
predates enabling `dump_frames`), logging a wireless-remote key command this device sent:

```
[D][rs485_frame:605]: TX 100200830100010000000100000000981003
```

Split into fields:

```
10 02   00 83 01 00 01 00 00 00 01 00 00 00   00 98   10 03
DLE STX └──────────── payload (12 bytes) ────────────┘ CRC   DLE ETX
```

`sum16_big_endian header_inclusive` (`calculate_crc_()`, `rs485_frame.cpp:449-456`) sums
`DLE + STX + every payload byte`, keeps the low 16 bits, and emits the result high byte first:

```
0x10 + 0x02                                       = 0x12
     + 0x00 + 0x83 + 0x01                          = 0x96
     + 0x00 + 0x01 + 0x00 + 0x00                   = 0x97
     + 0x00 + 0x01 + 0x00 + 0x00 + 0x00             = 0x98

sum = 0x0098  ->  CRC field = 00 98  ✓ matches the TX dump
```

A second frame from the same log, as a spot check: TX `1002008301020000000200000000009a1003` has
payload `00 83 01 02 00 00 00 02 00 00 00 00`. Summing `DLE + STX +` that payload gives `0x9A`, i.e.
`00 9A` — matches the frame's CRC field. Same method, different bytes.

When you write `on_frame:` lambdas, `payload[]` is `frame_type + data` with DLE/STX/ETX, escapes,
and the CRC already stripped (`payload[0..1]` = frame type for a 2-byte type, data from `payload[2]`
onward) — that is what makes lambdas simple, at the cost of the CRC not being there to check by eye.
`payload_dump_top` does not help here either — it dumps the same CRC-stripped `rx_payload_`. A TX
dump via `dump_frames: true` is the only place the CRC bytes are logged.

## Step 3: Sniffer — with OEM wireless remote commands

Same config, but now buttons are being pressed on the OEM wireless remote. Two things change: new
frame types appear, and the display frames sprout many `unique` payloads.

```
[I][rs485_frame.stats]: RS485 sniffer stats over 30015 ms (sorted by count):
[I][rs485_frame.stats]:   type  cnt    d-ref(min/med/max)    d-same(min/med/max)   payloads
[I][rs485_frame.stats]:   0101   300        -     -     -       66   100   134   1 unique
[I][rs485_frame.stats]:   040A    35       55    79    91      100   698  2000   16 unique +7
[I][rs485_frame.stats]:   0103    28      104   112   120      131   815  2000   9 unique
[I][rs485_frame.stats]:   0102    19       58    90    91      528  1983  2037   3 unique
[I][rs485_frame.stats]:   0083    17        6     7     7      700  1300  4000   7 unique
[I][rs485_frame.stats]:   0C01    15       24    29    33     1981  2000  2017   1 unique
[I][rs485_frame.stats]:   000C    15       29    37    38     1984  2000  2017   1 unique
[I][rs485_frame.stats]:   0103 payloads:
[I][rs485_frame.stats]:         6 @ 01 03 20 20 20 20 20 20 53 65 74 74 69 6E 67 73 ...  |..      Settings              Me|
[I][rs485_frame.stats]:         5 @ 01 03 20 20 20 20 20 20 20 4C 69 67 68 74 73 ...     |..       Lights            Turne|
[I][rs485_frame.stats]:         2 @ 01 03 20 20 41 69 72 20 54 65 6D 70 20 20 20 36 32 5F 46 ... |..  Air Temp   62_F          |
[I][rs485_frame.stats]:         2 @ 01 03 20 20 20 20 20 20 48 65 61 74 65 72 31 ...     |..      Heater1            Manua|
[I][rs485_frame.stats]:   0083 payloads:
[I][rs485_frame.stats]:         7 @ 00 83 01 02 00 00 00 02 00 00 00 C1 01 5B  |...........A.[|
[I][rs485_frame.stats]:         4 @ 00 83 01 01 00 00 00 01 00 00 00 C1 01 59  |...........A.Y|
[I][rs485_frame.stats]:         2 @ 00 83 01 00 04 00 00 00 04 00 00 C1 01 5F  |...........A._|
```

What changed:

- **`0083` appears only under user input.** Absent on the idle bus, 17 frames here, very tight
  cadence (`d-ref` 6/7/7 ms — it rides immediately behind the keep-alive). This is the remote's
  key/state report. The 4th byte (`00`/`01`/`02`/`04`) tracks the key/state; the `C1`/`C2` byte
  near the end looks like a small rolling counter or source id — left as homework. CRC verifies as
  sum16_big_endian: e.g. `00 83 01 02 00 00 00 02 00 00 00 C1` sums (with DLE+STX) to `0x15B` = `01 5B`. ✓
  (as-captured payload, trailing CRC included — see the caveat in
  [Verifying the CRC by hand](#verifying-the-crc-by-hand))
- **`040A` and `0103` are the display.** `0103` is the two-line display text; `040A` is a
  line/cell update carrying the same ASCII (`Settings`, `Lights`, `Aux2`, `Timers`, `Diagnostic`,
  `Configuration`, `Heater1`, `Air Temp 62_F`). As you scroll menus they cycle through many
  `unique` payloads — hence `16 unique +7`. ASCII frames like these are the easy wins: the text is
  right there in the `|...|` column.
- **Truncation caveat.** The display frames are cut at `payload_capture_bytes` (32 by default), so
  their last bytes (`...4D 65` = `Me`) are *data, not CRC* — the real CRC is past the capture
  length. Raise `payload_capture_bytes` if you want the full line plus its checksum.

## Version / ID frame `0x0004`

> Same caveat as the [CRC section](#verifying-the-crc-by-hand) above: the payloads below were
> captured before `rx_payload_` stopped including the trailing CRC bytes, so they are shown and
> hand-verified as originally captured. A current sniffer capture of these frames would print two
> fewer bytes per row (e.g. `00 04 CC 6D`, not `00 04 CC 6D 01 4F`); use a TX dump for a
> hand-verifiable CRC today.

Frame `0x0004` carries the firmware/ID strings that the controller also shows on its Diagnostic
screen. Three distinct payloads appeared:

```
00 04 02 00 18              |.....|     status/sequence byte 0x02, CRC 00 18
00 04 30 33 30 30 20 00 F9  |..0300 .|   ASCII "0300 ", CRC 00 F9
00 04 CC 6D 01 4F           |..Lm.O|     ID bytes CC 6D, CRC 01 4F
```

- `00 04 CC 6D 01 4F` decodes to **RF base ID `6DCC`**: bytes `CC 6D` are the ID in little-endian
  (`0x6DCC`), matching the `ID:6DCC` printed on the Diagnostic screen. CRC check:
  `0x10 + 0x02 + 0x00 + 0x04 + 0xCC + 0x6D = 0x14F` = `01 4F`. ✓ (Note the CRC's high byte `0x01`
  is *not* a data byte — easy to miscount.)
- `00 04 30 33 30 30 20` is the ASCII string `"0300 "`: `0x10 + 0x02 + 00 + 04 + 30 + 33 + 30 + 30
  + 20 = 0xF9` = `00 F9`. ✓

This is the payoff of a clean capture: a field you can cross-check against the front panel, with a
CRC that proves you have the byte boundaries right.

## What to do next

1. Put the detected settings into `generic/sniffer.yaml` (or `hayward/sniffer.yaml`): `uart:`
   `19200` / `8`, framing `10/02/03`, `escape: {mode: escape_byte, byte: 0x00}`, `crc:
   {type: sum16_big_endian, rx_accept: [header_inclusive]}`.
2. Use `0101` as `tx.gate.frame_type` and `reference_frame_type`.
3. Write `on_frame:` decoders for the frames you care about — the ASCII display frames first
   (`0103`/`040A`), then the binary state frames (`0083`, `0102`) using the byte positions you
   confirmed against the CRC.
4. See `hayward/aqualogic/example-device.yaml` for a complete worked integration built from exactly this process.
