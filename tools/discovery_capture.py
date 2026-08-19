#!/usr/bin/env python3
"""Offline trigger/response/ambient-state correlation over an ESPHome ``dump_frames: true`` log.

Parses ``[D][rs485_frame:NNN]: RX <hex>`` / ``TX <hex>`` lines, groups the responses that follow
a configured trigger pattern, reconstructs ambient state (e.g. an LED-mask bitfield) at each
trigger, and diffs responses across all occurrences of a trigger to surface which bits/characters
actually move. Output is a human-readable report for a person deriving an on/off signature, not
consumed by another program.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

DLE = 0x10
STX = 0x02
ETX = 0x03

_LOG_LINE_RE = re.compile(
    r"\[(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\.(?P<ms>\d{3})\]"
    r"\[D\]\[rs485_frame:\d+\]:\s+(?P<dir>RX|TX)\s+(?P<hex>[0-9A-Fa-f]+)\s*$"
)

# `esphome logs` run against a color-capable output (e.g. an interactive terminal, not a plain
# pipe/redirect) wraps each severity tag in an SGR escape and resets it at line end, e.g.
# "[18:03:16.291]\x1b[0;36m[D][rs485_frame:335]: RX ...\x1b[0m" -- strip these before matching,
# or _LOG_LINE_RE's literal "][D]" never matches and the whole capture silently parses to zero
# lines (no error raised).
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def hex_to_bytes(s: str) -> bytes:
    s = s.replace(" ", "").replace("\t", "")
    return bytes.fromhex(s)


def bytes_to_hex(b: bytes, sep: str = " ") -> str:
    return sep.join(f"{x:02x}" for x in b)


class MalformedFrame(ValueError):
    pass


def destuff(raw: bytes, escape_mode: str = "double", escape_byte: Optional[int] = None) -> bytes:
    """Strip DLE/STX...DLE/ETX framing and undo DLE-escaping. Returns frame_type+data+CRC bytes.

    escape_mode "double" (default): a literal DLE is wire-stuffed as DLE DLE.
    escape_mode "escape_byte": a literal DLE is wire-stuffed as DLE + escape_byte (the marker
    value configured on the rs485_frame hub's framing.escape.byte, e.g. Hayward's 0x00) -- this
    matters because a wireless command byte that happens to equal DLE (0x10) round-trips as
    "10 00" on Hayward's actual escape_byte/0x00 scheme, not "10 10".
    """
    if escape_mode not in ("double", "escape_byte"):
        raise ValueError(f"unknown escape_mode: {escape_mode!r}")
    if escape_mode == "escape_byte" and escape_byte is None:
        raise ValueError("escape_byte is required when escape_mode is escape_byte")
    marker = DLE if escape_mode == "double" else escape_byte
    if len(raw) < 4 or raw[0] != DLE or raw[1] != STX or raw[-2] != DLE or raw[-1] != ETX:
        raise MalformedFrame(f"not a DLE/STX...DLE/ETX frame: {bytes_to_hex(raw)}")
    body = raw[2:-2]
    out = bytearray()
    i = 0
    while i < len(body):
        b = body[i]
        if b == DLE:
            if i + 1 < len(body) and body[i + 1] == marker:
                out.append(DLE)
                i += 2
                continue
            raise MalformedFrame(f"unescaped DLE mid-payload: {bytes_to_hex(raw)}")
        out.append(b)
        i += 1
    return bytes(out)


@dataclass(frozen=True)
class LogLine:
    line_no: int
    ts: float  # seconds-of-day, monotonic within one capture
    direction: str  # "RX" | "TX"
    raw_hex: str
    payload: Optional[bytes]  # de-stuffed, CRC-stripped logical payload; None if malformed


def parse_log(
    path: Path, crc_len: int, escape_mode: str = "double", escape_byte: Optional[int] = None
) -> list[LogLine]:
    lines: list[LogLine] = []
    with open(path, "r", errors="replace") as f:
        for line_no, text in enumerate(f, start=1):
            text = _ANSI_RE.sub("", text)
            m = _LOG_LINE_RE.search(text)
            if not m:
                continue
            ts = (
                int(m.group("h")) * 3600
                + int(m.group("m")) * 60
                + int(m.group("s"))
                + int(m.group("ms")) / 1000.0
            )
            raw_hex = m.group("hex")
            payload: Optional[bytes]
            try:
                raw = hex_to_bytes(raw_hex)
                body = destuff(raw, escape_mode=escape_mode, escape_byte=escape_byte)
                payload = body[: len(body) - crc_len] if crc_len > 0 else body
            except (MalformedFrame, ValueError):
                payload = None
            lines.append(LogLine(line_no, ts, m.group("dir"), raw_hex, payload))
    return lines


@dataclass(frozen=True)
class Matcher:
    prefix: bytes
    mask: Optional[bytes] = None

    def matches(self, payload: bytes) -> bool:
        if payload is None or len(payload) < len(self.prefix):
            return False
        mask = self.mask if self.mask is not None else bytes([0xFF] * len(self.prefix))
        for p, m, b in zip(self.prefix, mask, payload):
            if (b & m) != (p & m):
                return False
        return True

    @classmethod
    def from_hex(cls, prefix_hex: str, mask_hex: Optional[str] = None) -> "Matcher":
        prefix = hex_to_bytes(prefix_hex)
        mask = hex_to_bytes(mask_hex) if mask_hex else None
        return cls(prefix, mask)


@dataclass
class TriggerDef:
    label: str
    matcher: Matcher
    direction: str = "any"  # "any" | "tx" | "rx"
    window_ms: Optional[int] = None
    until_next_trigger: Optional[bool] = None
    discover_bytes: int = 0
    """When >0, this def is a wildcard: matches are further split by the next `discover_bytes`
    bytes immediately following the matched prefix, each distinct value becoming its own reported
    trigger labeled "{label} [xx..]" -- so a single broad def (e.g. payload_prefix "00 83 01",
    discover_bytes 1) can stand in for a whole family of not-yet-named buttons/commands sharing
    that prefix, without requiring the family to be enumerated by hand up front."""

    def direction_ok(self, line_direction: str) -> bool:
        return self.direction == "any" or self.direction.upper() == line_direction

    def effective_label(self, payload: bytes) -> str:
        if self.discover_bytes <= 0:
            return self.label
        start = len(self.matcher.prefix)
        disc = payload[start : start + self.discover_bytes]
        return f"{self.label} [{bytes_to_hex(disc, sep='')}]"


_SUBBLOCK_BODY_WIDTH = {0x02: 8, 0x03: 41}
"""Body width (bytes, not counting the tag byte) of each known Hayward `04 0A` sub-block: 0x02 is
the 8-byte LED solid+blink mask, 0x03 the 40-char display text plus its trailing Display
Flags/NUL byte -- both byte-identical to their standalone `01 02`/`01 03` frame bodies."""


def _split_tagged_subblocks(payload: bytes, header_len: int) -> dict[int, bytes]:
    """Splits the tagged sub-blocks following a container header (e.g. `04 0A`'s `83 00`) into
    {tag: body}, using `_SUBBLOCK_BODY_WIDTH` to know each body's length. Sub-blocks are
    independently optional and, when more than one is present, arrive in a fixed order; an
    unrecognized tag byte stops the split rather than guessing a width, returning whatever
    sub-blocks were already parsed."""
    result: dict[int, bytes] = {}
    i = header_len
    while i < len(payload):
        tag = payload[i]
        width = _SUBBLOCK_BODY_WIDTH.get(tag)
        if width is None:
            break
        body = payload[i + 1 : i + 1 + width]
        if len(body) < width:
            break
        result[tag] = body
        i += 1 + width
    return result


@dataclass
class Region:
    """One place a tracker's field can be found. Either a direct offset from the end of
    `matcher.prefix` (`subblock_tag` omitted), or the body of a tagged sub-block located via
    `_split_tagged_subblocks` (`subblock_tag` set) -- e.g. Hayward's `04 0A` container, where the
    LED mask/display text only exist at a fixed offset when a preceding tag byte says so.
    `sub_offset` (default 0) then indexes further into whichever span was found; `width` is the
    field's length in bytes, doubled by the caller for a paired_flag_and tracker (two consecutive
    same-width spans instead of one)."""

    matcher: Matcher
    width: int
    subblock_tag: Optional[int] = None
    sub_offset: int = 0

    def resolve(self, payload: Optional[bytes], span_multiplier: int = 1) -> Optional[bytes]:
        if payload is None or not self.matcher.matches(payload):
            return None
        actual_width = self.width * span_multiplier
        if self.subblock_tag is None:
            start = len(self.matcher.prefix) + self.sub_offset
            end = start + actual_width
            if len(payload) < end:
                return None
            return payload[start:end]
        subblocks = _split_tagged_subblocks(payload, header_len=len(self.matcher.prefix))
        body = subblocks.get(self.subblock_tag)
        if body is None:
            return None
        end = self.sub_offset + actual_width
        if len(body) < end:
            return None
        return body[self.sub_offset : end]


@dataclass
class TrackerDef:
    label: str
    matcher: Optional[Matcher] = None
    offset: int = 0
    width: int = 0
    endian: str = "little"
    kind: str = "scalar"
    """"scalar" (default): the existing fixed offset+width+endian integer read, via `matcher`/
    `offset`/`width`/`endian` -- zero migration cost for configs written before `regions` existed.
    "flag_scan": bit `bit` of every byte in the resolved region -> a bool (single-byte region) or
    a tuple of the byte positions where it's set (multi-byte region). "paired_flag_and": two
    consecutive `width`-byte spans starting at the resolved region, ANDed bit-by-bit -> a tuple of
    the set bit positions (0 = LSB of the region's first byte)."""
    regions: list[Region] = field(default_factory=list)
    bit: Optional[int] = None
    index_set: Optional[set[int]] = None
    """flag_scan only: when set, a byte only ever counts as flagged if its whole value is also a
    member of this set -- guards against misreading an unrelated odd value (bit 0 incidentally
    set) as the flag on hardware/firmware where the byte means something else."""
    note: Optional[str] = None
    """Optional caveat surfaced next to this tracker's diff in the report, e.g. a firmware-version
    gating note -- purely informational, never affects matching/extraction."""

    def matches(self, payload: Optional[bytes]) -> bool:
        """A region-based tracker "matches" a payload only if it can actually extract a value
        from it -- checking just the region's outer matcher isn't enough for a subblock_tag
        region, since a container frame (e.g. `04 0a`) matches that outer prefix even when it
        carries a *different* sub-block than the one this tracker wants (its sub-blocks are each
        independently optional). Treating that as a match would extract None and, via the
        ambient-replay "last write wins" contract, wrongly overwrite a real prior value with
        "unknown"."""
        if payload is None:
            return False
        if self.regions:
            return self._resolve_span(payload) is not None
        return self.matcher is not None and self.matcher.matches(payload)

    def _resolve_span(self, payload: Optional[bytes]) -> Optional[bytes]:
        multiplier = 2 if self.kind == "paired_flag_and" else 1
        for region in self.regions:
            span = region.resolve(payload, span_multiplier=multiplier)
            if span is not None:
                return span
        return None

    def _flagged(self, b: int) -> bool:
        if self.index_set is not None and b not in self.index_set:
            return False
        return bool((b >> self.bit) & 1)

    def _extract_flag_scan(self, span: bytes):
        if len(span) == 1:
            return self._flagged(span[0])
        return tuple(i for i, b in enumerate(span) if self._flagged(b))

    def _extract_paired_flag_and(self, span: bytes) -> tuple[int, ...]:
        half = len(span) // 2
        a, b = span[:half], span[half:]
        return tuple(
            i
            for i in range(half * 8)
            if (a[i // 8] >> (i % 8)) & 1 and (b[i // 8] >> (i % 8)) & 1
        )

    def extract(self, payload: Optional[bytes]):
        """`kind: scalar` (no regions): `offset` is the field's first byte on the wire (lowest
        payload index), `width` its length in bytes. `endian` picks which end of that slice is
        most-significant: "little" means payload[offset] (the wire-earliest byte) is the
        LEAST-significant byte of the result; "big" means payload[offset] is the MOST-significant
        byte instead. E.g. payload[5:7] == b"\\xe8\\x01" extracts to 0x01e8 under "little" but
        0xe801 under "big". `kind: flag_scan`/`paired_flag_and` (regions-based): resolves the
        first matching region and dispatches per `kind` -- see the `kind` field's docstring."""
        if not self.regions:
            if payload is None or len(payload) < self.offset + self.width:
                return None
            chunk = payload[self.offset : self.offset + self.width]
            return int.from_bytes(chunk, byteorder=self.endian)  # type: ignore[arg-type]
        span = self._resolve_span(payload)
        if span is None:
            return None
        if self.kind == "flag_scan":
            return self._extract_flag_scan(span)
        if self.kind == "paired_flag_and":
            return self._extract_paired_flag_and(span)
        raise ValueError(f"tracker {self.label!r}: unsupported kind {self.kind!r} for a regions-based tracker")


@dataclass
class Config:
    crc_len: int = 2
    escape_mode: str = "double"
    escape_byte: Optional[int] = None
    default_window_ms: int = 3000
    default_until_next_trigger: bool = True
    ascii_min_run: int = 8
    min_occurrences_for_signature: int = 2
    keepalive_payloads: list[bytes] = field(default_factory=list)
    triggers: list[TriggerDef] = field(default_factory=list)
    trackers: list[TrackerDef] = field(default_factory=list)
    auto_split: bool = True
    """Default on. When a trigger's own occurrences (already bucketed by label/discover_bytes)
    disagree on the raw frame bytes beyond whatever payload_prefix/discover_bytes already
    consumed, auto-partition them into labeled sub-buckets instead of silently reporting one
    homogeneous-looking group that's actually several distinct buttons sharing a prefix -- see
    `_auto_split_group`. Set false (CLI: --no-auto-split) to get the old flat grouping back, e.g.
    to match a hand-authored config's own intentional discover_bytes granularity exactly."""

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        triggers = [
            TriggerDef(
                label=t["label"],
                matcher=Matcher.from_hex(t["payload_prefix"], t.get("match_mask")),
                direction=t.get("direction", "any"),
                window_ms=t.get("window_ms"),
                until_next_trigger=t.get("until_next_trigger"),
                discover_bytes=t.get("discover_bytes", 0),
            )
            for t in d.get("triggers", [])
        ]
        def _region(r: dict) -> Region:
            return Region(
                matcher=Matcher.from_hex(r["match_prefix"]),
                width=r["width"],
                subblock_tag=r.get("subblock_tag"),
                sub_offset=r.get("sub_offset", 0),
            )

        trackers = [
            TrackerDef(
                label=t["label"],
                matcher=Matcher.from_hex(t["match_prefix"]) if "match_prefix" in t else None,
                offset=t.get("offset", 0),
                width=t.get("width", 0),
                endian=t.get("endian", "little"),
                kind=t.get("kind", "scalar"),
                regions=[_region(r) for r in t.get("regions", [])],
                bit=t.get("bit"),
                index_set=set(t["index_set"]) if t.get("index_set") is not None else None,
                note=t.get("note"),
            )
            for t in d.get("trackers", [])
        ]
        keepalive = [hex_to_bytes(h) for h in d.get("keepalive_payloads", [])]
        escape_mode = d.get("escape_mode", "double")
        if escape_mode not in ("double", "escape_byte"):
            raise ValueError(f"config escape_mode must be 'double' or 'escape_byte', got {escape_mode!r}")
        escape_byte = d.get("escape_byte")
        if escape_mode == "escape_byte" and escape_byte is None:
            raise ValueError("config escape_byte is required when escape_mode is escape_byte")
        return cls(
            crc_len=d.get("crc_len", 2),
            escape_mode=escape_mode,
            escape_byte=escape_byte,
            default_window_ms=d.get("default_window_ms", 3000),
            default_until_next_trigger=d.get("default_until_next_trigger", True),
            ascii_min_run=d.get("ascii_min_run", 8),
            min_occurrences_for_signature=d.get("min_occurrences_for_signature", 2),
            keepalive_payloads=keepalive,
            triggers=triggers,
            trackers=trackers,
            auto_split=d.get("auto_split", True),
        )


@dataclass
class Occurrence:
    trigger: TriggerDef
    line: LogLine
    label: str  # trigger.label, or trigger.label + " [disc]" under discover_bytes bucketing


@dataclass
class Group:
    payload: bytes
    first_offset_ms: float
    count: int
    raw_hex_example: str


@dataclass
class OccurrenceReport:
    occurrence: Occurrence
    window_end_ts: float
    ambient: dict[str, Optional[int]]  # tracker label -> value strictly before the trigger line
    after: dict[str, Optional[int]]  # tracker label -> first matching value inside the window
    groups: list[Group]
    silent: bool


@dataclass
class TriggerReport:
    label: str
    occurrences: list[OccurrenceReport]
    # Response bit/ascii-diff: computed from the raw RX response payloads seen in this trigger's
    # windows, grouped by payload length -- entirely independent of whether any tracker is
    # configured. This is the "blind first pass" path: it works with zero trackers defined.
    bit_diffs: dict[int, dict]  # length -> {"example_hex", "varying_mask", "byte_values", "n"}
    ascii_diffs: dict[int, list[dict]]  # length -> [{"example_hex", "span", "values"}]
    # Tracker diff: only present per-tracker if that tracker is configured. Diffs the ambient
    # "before" value against the first in-window "after" value matching the tracker, aggregated
    # across every occurrence of this trigger -- this is the piece that actually answers "which
    # bit does this button flip in the field I'm tracking," as opposed to the response diff above
    # which only says which bits vary in the raw response bytes themselves.
    tracker_diffs: dict[str, dict]  # tracker label -> {"pairs": [(before, after), ...], "varying_bits": int}


@dataclass
class Report:
    trigger_reports: list[TriggerReport]
    orphan_groups: list[Group]
    orphan_span: Optional[tuple[float, float]]
    total_lines: int
    total_rx: int


def _find_occurrences(lines: list[LogLine], config: Config) -> list[Occurrence]:
    """Each line produces at most one occurrence, even if several trigger defs match it -- e.g. a
    named "Filter" trigger (payload_prefix "00 83 01 80") and a broader wildcard trigger
    (payload_prefix "00 83 01", discover_bytes) both match the same real Filter-button TX line.
    Precedence: longest matcher.prefix wins (the more specific def), so a config can mix named
    triggers for buttons you've identified with a catch-all wildcard for everything else without
    every named button's presses also being double-counted under the wildcard's bucket. Ties
    (equal prefix length) fall back to config list order, first-listed wins -- max() with a single
    key only replaces the running best on a strictly greater value, so it keeps the first-seen
    candidate on a tie.
    """
    occurrences: list[Occurrence] = []
    for line in lines:
        if line.payload is None:
            continue
        candidates = [
            trig
            for trig in config.triggers
            if trig.direction_ok(line.direction) and trig.matcher.matches(line.payload)
        ]
        if not candidates:
            continue
        best = max(candidates, key=lambda t: len(t.matcher.prefix))
        occurrences.append(Occurrence(best, line, best.effective_label(line.payload)))
    occurrences.sort(key=lambda o: o.line.line_no)
    return occurrences


def _window_end(
    occ: Occurrence, next_any_ts: Optional[float], config: Config
) -> float:
    trig = occ.trigger
    effective_window_ms = trig.window_ms if trig.window_ms is not None else config.default_window_ms
    cap_ts = occ.line.ts + effective_window_ms / 1000.0
    until_next = (
        trig.until_next_trigger
        if trig.until_next_trigger is not None
        else config.default_until_next_trigger
    )
    if until_next and next_any_ts is not None:
        return min(cap_ts, next_any_ts)
    return cap_ts


def _fold(payloads_with_offsets: list[tuple[bytes, float, str]]) -> list[Group]:
    order: list[bytes] = []
    seen: dict[bytes, Group] = {}
    for payload, offset_ms, raw_hex in payloads_with_offsets:
        if payload not in seen:
            seen[payload] = Group(payload, offset_ms, 1, raw_hex)
            order.append(payload)
        else:
            seen[payload].count += 1
    return [seen[p] for p in order]


def _is_baseline(payload: bytes, baseline: set[bytes]) -> bool:
    return payload in baseline


_KEEPALIVE_MIN_COUNT = 5


def _auto_keepalive_baseline(lines: list[LogLine]) -> set[bytes]:
    """A payload is treated as ambient keepalive noise only once it's repeated often enough to be
    distinguishable from a one-off response by frequency alone. In a sparse/synthetic log where
    every payload happens to appear once, nothing crosses the threshold and nothing is folded away
    -- the alternative (falling back to "most frequent, ties included") would misclassify every
    such payload as baseline, since a tie at count 1 includes all of them.
    """
    counts: dict[bytes, int] = {}
    for line in lines:
        if line.direction == "RX" and line.payload is not None:
            counts[line.payload] = counts.get(line.payload, 0) + 1
    if not counts:
        return set()
    max_count = max(counts.values())
    if max_count < _KEEPALIVE_MIN_COUNT:
        return set()
    return {p for p, c in counts.items() if c == max_count}


def _ambient_snapshot(
    trackers: list[TrackerDef], lines: list[LogLine], before_line_no: int
) -> dict[str, Optional[int]]:
    snapshot: dict[str, Optional[int]] = {t.label: None for t in trackers}
    for line in lines:
        if line.line_no >= before_line_no:
            break
        if line.payload is None:
            continue
        for t in trackers:
            if t.matches(line.payload):
                snapshot[t.label] = t.extract(line.payload)
    return snapshot


def _bit_diff(payloads: list[bytes]) -> Optional[dict]:
    """Aggregates across all `payloads` (same length, one per occurrence-shape instance).
    varying_mask bit k is set iff not every payload agrees on that bit -- computed as the OR of
    (payload[i] XOR payloads[0]) for i>0, which is exactly the full pairwise-XOR-OR set (any bit
    that isn't constant across the whole set must differ from the arbitrarily-chosen reference
    payloads[0] in at least one other payload, by pigeonhole)."""
    if len(payloads) < 2:
        return None
    length = len(payloads[0])
    if any(len(p) != length for p in payloads):
        return None
    base = payloads[0]
    varying_mask = bytearray(length)
    for p in payloads[1:]:
        for i in range(length):
            varying_mask[i] |= base[i] ^ p[i]
    byte_values = {
        i: sorted({p[i] for p in payloads}) for i in range(length) if varying_mask[i] != 0
    }
    return {
        "example_hex": bytes_to_hex(base),
        "varying_mask": bytes(varying_mask),
        "byte_values": byte_values,
        "n": len(payloads),
    }


def _ascii_runs(payload: bytes, min_run: int) -> list[tuple[int, int]]:
    runs = []
    start = None
    for i, b in enumerate(payload):
        printable = 0x20 <= b <= 0x7E
        if printable and start is None:
            start = i
        elif not printable and start is not None:
            if i - start >= min_run:
                runs.append((start, i))
            start = None
    if start is not None and len(payload) - start >= min_run:
        runs.append((start, len(payload)))
    return runs


def _ascii_diff(payloads: list[bytes], min_run: int) -> list[dict]:
    if len(payloads) < 2:
        return []
    length = len(payloads[0])
    if any(len(p) != length for p in payloads):
        return []
    runs = _ascii_runs(payloads[0], min_run)
    diffs = []
    for start, end in runs:
        varying_positions = [
            i for i in range(start, end) if len({p[i] for p in payloads}) > 1
        ]
        if not varying_positions:
            continue
        span_start, span_end = min(varying_positions), max(varying_positions) + 1
        values = sorted({p[span_start:span_end].decode("ascii", errors="replace") for p in payloads})
        diffs.append({"example_hex": bytes_to_hex(payloads[0]), "span": (span_start, span_end), "values": values})
    return diffs


def _ascii_annotation(payload: bytes, min_run: int) -> Optional[str]:
    """Decode every printable run in payload (>= min_run bytes) for display next to the raw hex --
    e.g. "Blower ... Turned On" instead of making the reader eyeball 42 6c 6f 77 65 72 by hand.
    Purely cosmetic (never affects matching/diffing, which stay byte-exact); returns None if the
    payload has no run long enough to be worth showing."""
    runs = _ascii_runs(payload, min_run)
    if not runs:
        return None
    return " | ".join(payload[start:end].decode("ascii", errors="replace") for start, end in runs)


def _tracker_diff_int(pairs: list[tuple[int, int]]) -> dict:
    """pairs: (before, after) tracker values across every occurrence of one trigger. Same
    aggregation as _bit_diff's varying-bit logic, but over scalar ints (a bit position, not a
    byte position) -- reports which bits of the tracked field ever flip between before and after,
    across all occurrences, and the distinct (before, after) values observed for context."""
    varying_bits = 0
    for before, after in pairs:
        varying_bits |= before ^ after
    return {"pairs": pairs, "varying_bits": varying_bits}


def _tracker_diff_bool(pairs: list[tuple[bool, bool]]) -> dict:
    """A flag_scan tracker over a single-byte region reports bool, not int -- the before/after
    grid this aggregates is the bool equivalent of _tracker_diff_int's varying_bits: whether the
    flag ever toggled at all across the trigger, plus the count landing in each of the four
    (before, after) combinations for context."""
    counts = {"False->False": 0, "False->True": 0, "True->False": 0, "True->True": 0}
    for before, after in pairs:
        counts[f"{before}->{after}"] += 1
    toggled = any(before != after for before, after in pairs)
    return {"pairs": pairs, "toggled": toggled, "counts": counts}


def _tracker_diff_tuple(pairs: list[tuple[tuple[int, ...], tuple[int, ...]]]) -> dict:
    """A flag_scan/paired_flag_and tracker over a multi-byte region reports a tuple of set
    positions, not int -- the position-set equivalent of _tracker_diff_int's varying_bits: the
    symmetric difference (positions whose membership changed) between before and after, OR'd
    across every occurrence, same idea as _bit_diff's OR-of-XOR applied to position sets instead
    of byte values."""
    varying: set[int] = set()
    for before, after in pairs:
        varying |= set(before) ^ set(after)
    return {"pairs": pairs, "varying_positions": tuple(sorted(varying))}


def _tracker_diff(pairs: list[tuple]) -> dict:
    """Dispatches on the tracked value's type -- scalar trackers (kind: scalar) yield int,
    flag_scan yields bool (single-byte region) or a tuple of positions (multi-byte region), and
    paired_flag_and always yields a tuple of positions."""
    sample = pairs[0][0]
    if isinstance(sample, bool):
        return _tracker_diff_bool(pairs)
    if isinstance(sample, tuple):
        return _tracker_diff_tuple(pairs)
    return _tracker_diff_int(pairs)


def _tail_diff_span(tails: list[bytes]) -> Optional[tuple[int, int]]:
    """Finds the leading contiguous run of byte positions where `tails` disagree, starting at the
    first position any two tails differ. Only the *leading* run is returned, not every differing
    position -- a later, non-contiguous difference (e.g. positions 0 and 7 differ but 1-6 agree)
    is left for a subsequent recursive call to find, once the leading run has been split off and
    the constant bytes between it and position 7 no longer mask it. Returns None if every tail
    (up to the shortest) agrees and none differ in length -- i.e. genuinely homogeneous."""
    if len(tails) < 2:
        return None
    min_len = min(len(t) for t in tails)
    diff_positions = [i for i in range(min_len) if len({t[i] for t in tails}) > 1]
    if not diff_positions:
        lengths = {len(t) for t in tails}
        if len(lengths) > 1:
            return (min_len, max(lengths))
        return None
    start = diff_positions[0]
    diff_set = set(diff_positions)
    end = start + 1
    while end in diff_set:
        end += 1
    return (start, end)


def _auto_split_group(label: str, occ_windows: list, consumed_start: int) -> dict[str, list]:
    """Recursively partitions one label's occurrences by the raw trigger payload bytes beyond
    `consumed_start` (whatever payload_prefix/discover_bytes already consumed). Each recursive
    call only looks at bytes from its own `consumed_start` onward, so a two-level collapse (a
    bucket that's still heterogeneous even after one split) gets caught in the same pass instead
    of requiring a second hand-added discover_bytes trigger -- see rs485_frame-206.3.8's wired-
    local "00 02 00 00" example, which needed exactly this: one split on the top-level 2-byte
    subcode, then a second split 2 bytes deeper to separate Valve3/Valve4/Heater1."""
    tails = [ow[0].line.payload[consumed_start:] for ow in occ_windows]
    span = _tail_diff_span(tails)
    if span is None:
        return {label: occ_windows}
    start, end = span
    buckets: dict[bytes, list] = {}
    order: list[bytes] = []
    for ow, tail in zip(occ_windows, tails):
        key = tail[start:end]
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(ow)
    result: dict[str, list] = {}
    for key in order:
        sub_label = f"{label} [{bytes_to_hex(key, sep='')}]"
        result.update(_auto_split_group(sub_label, buckets[key], consumed_start + end))
    return result


def analyze(lines: list[LogLine], config: Config) -> Report:
    occurrences = _find_occurrences(lines, config)
    occ_by_line_no = {o.line.line_no: o for o in occurrences}
    keepalive_baseline = (
        set(config.keepalive_payloads) if config.keepalive_payloads else _auto_keepalive_baseline(lines)
    )

    windows: list[tuple[Occurrence, float, float]] = []  # (occ, start_ts, end_ts)
    for idx, occ in enumerate(occurrences):
        next_any_ts = occurrences[idx + 1].line.ts if idx + 1 < len(occurrences) else None
        end_ts = _window_end(occ, next_any_ts, config)
        windows.append((occ, occ.line.ts, end_ts))

    # Keyed by effective label (post discover_bytes bucketing), not the raw TriggerDef.label --
    # one wildcard def can produce many distinct reported labels.
    label_order: list[str] = []
    trigger_to_windows: dict[str, list[tuple[Occurrence, float, float]]] = {}
    for occ, start, end in windows:
        if occ.label not in trigger_to_windows:
            label_order.append(occ.label)
        trigger_to_windows.setdefault(occ.label, []).append((occ, start, end))

    if config.auto_split:
        expanded_label_order: list[str] = []
        expanded_windows: dict[str, list[tuple[Occurrence, float, float]]] = {}
        for label in label_order:
            occ_windows = trigger_to_windows[label]
            trig = occ_windows[0][0].trigger
            consumed_start = len(trig.matcher.prefix) + trig.discover_bytes
            for sub_label, sub_windows in _auto_split_group(label, occ_windows, consumed_start).items():
                expanded_label_order.append(sub_label)
                expanded_windows[sub_label] = sub_windows
        label_order = expanded_label_order
        trigger_to_windows = expanded_windows

    covered_line_nos: set[int] = {occ.line.line_no for occ in occurrences}
    occurrence_reports: dict[int, OccurrenceReport] = {}

    for occ, start, end in windows:
        in_window_lines = [
            line
            for line in lines
            if line.direction == "RX"
            and line.payload is not None
            and start < line.ts <= end
            and line.line_no not in occ_by_line_no
        ]
        for line in in_window_lines:
            covered_line_nos.add(line.line_no)
        in_window = [(line.payload, (line.ts - start) * 1000.0, line.raw_hex) for line in in_window_lines]
        groups = _fold(in_window)
        non_baseline_groups = [g for g in groups if not _is_baseline(g.payload, keepalive_baseline)]
        silent = len(non_baseline_groups) == 0
        ambient = _ambient_snapshot(config.trackers, lines, occ.line.line_no)
        after: dict[str, Optional[int]] = {t.label: None for t in config.trackers}
        for line in in_window_lines:
            for t in config.trackers:
                if after[t.label] is None and t.matches(line.payload):
                    after[t.label] = t.extract(line.payload)
        occurrence_reports[occ.line.line_no] = OccurrenceReport(occ, end, ambient, after, groups, silent)

    trigger_reports = []
    for label in label_order:
        occs = trigger_to_windows[label]
        occ_reports = [occurrence_reports[o.line.line_no] for o, _, _ in occs]

        by_length: dict[int, list[bytes]] = {}
        for orep in occ_reports:
            for g in orep.groups:
                if _is_baseline(g.payload, keepalive_baseline):
                    continue
                by_length.setdefault(len(g.payload), []).append(g.payload)

        bit_diffs = {}
        ascii_diffs = {}
        for length, payloads in by_length.items():
            if len(payloads) >= config.min_occurrences_for_signature:
                bd = _bit_diff(payloads)
                if bd:
                    bit_diffs[length] = bd
                ad = _ascii_diff(payloads, config.ascii_min_run)
                if ad:
                    ascii_diffs[length] = ad

        tracker_diffs = {}
        for t in config.trackers:
            pairs = [
                (orep.ambient[t.label], orep.after[t.label])
                for orep in occ_reports
                if orep.ambient[t.label] is not None and orep.after[t.label] is not None
            ]
            if len(pairs) >= config.min_occurrences_for_signature:
                td = _tracker_diff(pairs)
                if t.note:
                    td["note"] = t.note
                tracker_diffs[t.label] = td

        trigger_reports.append(TriggerReport(label, occ_reports, bit_diffs, ascii_diffs, tracker_diffs))

    orphan_lines = [
        line
        for line in lines
        if line.direction == "RX" and line.payload is not None and line.line_no not in covered_line_nos
    ]
    # Keepalive/baseline payloads are kept here (not dropped), consistent with in-window groups
    # (which also keep them, only excluding them from silent-trigger/diffing logic) -- otherwise
    # the total-line coverage accounting below would silently lose baseline orphan lines while
    # still counting baseline in-window lines, an asymmetry with no principled reason behind it.
    orphan_groups = _fold([(l.payload, 0.0, l.raw_hex) for l in orphan_lines])
    orphan_span = (
        (orphan_lines[0].ts, orphan_lines[-1].ts) if orphan_lines else None
    )

    total_rx = sum(1 for l in lines if l.direction == "RX")
    return Report(trigger_reports, orphan_groups, orphan_span, len(lines), total_rx)


def filter_to_tracked(report: Report, trackers: list[TrackerDef]) -> Report:
    """Drop everything that doesn't match at least one tracker's matcher -- "hide the chatter once
    you know what you're looking for," strictly by tracker byte-pattern, ascii-decodable or not.
    (An earlier revision carved out an exception keeping any human-readable payload regardless of
    tracker match; reverted on user request -- --only-tracked means "only what I configured a
    tracker for," full stop, not a second implicit "or it looked like text" rule layered on top.)
    This includes not just the RX group listings (orphan and in-window) but also the response
    bit-diff/ascii-diff entries: a shape whose own example payload isn't itself a tracked frame is
    exactly the kind of chatter --only-tracked exists to hide, so leaving those diff blocks behind
    while the groups they're about disappear would be inconsistent. Trigger lines themselves and
    the ambient/tracker-diff sections are never filtered -- those describe the trigger and the
    tracked field, not incidental bus traffic."""
    if not trackers:
        raise ValueError("filter_to_tracked requires at least one tracker in the config")

    def keep(payload: bytes) -> bool:
        return any(t.matches(payload) for t in trackers)

    def keep_hex(example_hex: str) -> bool:
        return keep(hex_to_bytes(example_hex))

    filtered_trigger_reports = []
    for tr in report.trigger_reports:
        filtered_occs = [
            OccurrenceReport(
                orep.occurrence,
                orep.window_end_ts,
                orep.ambient,
                orep.after,
                [g for g in orep.groups if keep(g.payload)],
                orep.silent,
            )
            for orep in tr.occurrences
        ]
        filtered_bit_diffs = {
            length: bd for length, bd in tr.bit_diffs.items() if keep_hex(bd["example_hex"])
        }
        filtered_ascii_diffs = {
            length: ads
            for length, ads in tr.ascii_diffs.items()
            if ads and keep_hex(ads[0]["example_hex"])
        }
        filtered_trigger_reports.append(
            TriggerReport(tr.label, filtered_occs, filtered_bit_diffs, filtered_ascii_diffs, tr.tracker_diffs)
        )
    filtered_orphan = [g for g in report.orphan_groups if keep(g.payload)]
    return Report(filtered_trigger_reports, filtered_orphan, report.orphan_span, report.total_lines, report.total_rx)


def _all_printable(values: list[int]) -> bool:
    return all(0x20 <= v <= 0x7E for v in values)


def _render_shape_diffs(tr: TriggerReport) -> list[str]:
    """One combined block per payload shape (length), not two separate bit-diff/ascii-diff passes.
    Within a shape, a byte range already covered by an ascii-diff span is folded into that ascii
    line instead of also being repeated as a raw byte[i] entry -- printing "byte[47] in {0x66,
    0x6e}" right next to "chars[47:49]: ['ff', 'n ']" is the same fact shown twice in a worse
    encoding. But "this byte's index falls inside a run that happened to be printable in the
    first example payload" is not proof the byte is actually text -- a numeric field (a bitmask
    byte, say) can coincidentally land in the printable range in one occurrence without being
    text at all, and would fail to be printable in another occurrence. So a byte is only folded
    away here if *every* observed value at that position, across every occurrence, is itself
    printable ASCII; the moment even one occurrence shows a non-printable byte there, it stays in
    the bit-diff listing too (shown in both places, never silently hidden as text)."""
    lines: list[str] = []
    lengths = sorted(set(tr.bit_diffs) | set(tr.ascii_diffs))
    for length in lengths:
        bd = tr.bit_diffs.get(length)
        ads = tr.ascii_diffs.get(length, [])
        example = bd["example_hex"] if bd else ads[0]["example_hex"]
        n_str = f", n={bd['n']}" if bd else ""
        lines.append(f"  shape len={length} (example: {example}{n_str}):")
        ascii_covered: set[int] = set()
        for ad in ads:
            start, end = ad["span"]
            ascii_covered.update(range(start, end))
            lines.append(f"    chars[{start}:{end}] (ascii): {ad['values']}")
        if bd:
            remaining = {
                i: vals
                for i, vals in bd["byte_values"].items()
                if not (i in ascii_covered and _all_printable(vals))
            }
            if remaining:
                byte_values_str = ", ".join(
                    f"byte[{i}] in {{{', '.join(f'0x{v:02x}' for v in vals)}}}"
                    for i, vals in remaining.items()
                )
                lines.append(f"    {byte_values_str}")
    return lines


def _fmt_tracker_value(val) -> str:
    if val is None:
        return "unknown"
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, tuple):
        return "{" + ", ".join(str(i) for i in val) + "}"
    return "0x%08X" % val


def _fmt_tracker_pair(before, after) -> str:
    if isinstance(before, tuple):
        return f"{_fmt_tracker_value(before)}->{_fmt_tracker_value(after)}"
    if isinstance(before, bool):
        return f"{before}->{after}"
    return f"0x{before:x}->0x{after:x}"


def _group_line(g: Group, prefix: str, ascii_min_run: int) -> str:
    line = f"{prefix}x{g.count}  RX {bytes_to_hex(g.payload)}"
    ascii_text = _ascii_annotation(g.payload, ascii_min_run)
    if ascii_text:
        line += f'  ascii="{ascii_text}"'
    return line


def render_report(report: Report, ascii_min_run: int = 8) -> str:
    out = []
    silent_count = sum(1 for tr in report.trigger_reports for o in tr.occurrences if o.silent)
    trigger_count = sum(len(tr.occurrences) for tr in report.trigger_reports)
    out.append(
        f"SUMMARY: {trigger_count} triggers, {silent_count} silent, "
        f"{len(report.orphan_groups)} orphan-RX distinct groups"
    )
    out.append("")

    if report.orphan_groups:
        span = report.orphan_span
        span_str = f" ({span[0]:.3f}-{span[1]:.3f})" if span else ""
        out.append(f"ORPHAN RX{span_str}")
        for g in report.orphan_groups:
            out.append(_group_line(g, "  ", ascii_min_run))
        out.append("")

    for tr in report.trigger_reports:
        for orep in tr.occurrences:
            occ = orep.occurrence
            marker = " (no response)" if orep.silent else ""
            out.append(
                f"[{occ.line.ts:.3f}] TRIGGER \"{tr.label}\" (origin: {occ.line.direction})"
                f"{marker}  raw={occ.line.raw_hex}"
            )
            for label, val in orep.ambient.items():
                out.append(f"  ambient: {label}={_fmt_tracker_value(val)}")
            for g in orep.groups:
                out.append(_group_line(g, f"  +{g.first_offset_ms:.0f}ms  ", ascii_min_run))

        diff_lines = _render_shape_diffs(tr)
        if diff_lines:
            out.append("  -- response diff (raw RX payloads in this trigger's windows; no tracker required) --")
            out.extend(diff_lines)

        if tr.tracker_diffs:
            out.append("  -- tracker diff (before/after each configured tracker, across occurrences) --")
        for label, td in tr.tracker_diffs.items():
            pairs_str = ", ".join(_fmt_tracker_pair(b, a) for b, a in td["pairs"])
            if "varying_bits" in td:
                summary = f"varying_bits=0x{td['varying_bits']:x}"
            elif "varying_positions" in td:
                summary = f"varying_positions={_fmt_tracker_value(td['varying_positions'])}"
            else:
                summary = f"toggled={td['toggled']} counts={td['counts']}"
            out.append(f"  tracker-diff {label}: {summary} (pairs: {pairs_str})")
            if td.get("note"):
                out.append(f"    note: {td['note']}")
        out.append("")

    return "\n".join(out)


def load_config(path: Optional[Path]) -> Config:
    if path is None:
        return Config()
    with open(path) as f:
        return Config.from_dict(yaml.safe_load(f))


_EPILOG = """\
example:
  python3 discovery_capture.py mylog.txt --config configs/hayward_aqualogic.yaml
  python3 discovery_capture.py mylog.txt --config configs/hayward_aqualogic.yaml --only-tracked

what it does:
  Reads an ESPHome log captured with `dump_frames: true` (lines shaped
  "[HH:MM:SS.mmm][D][rs485_frame:NNN]: RX <hex>" / "TX <hex>"). For each configured trigger
  (typically a button-press command byte pattern), it groups the distinct RX response payloads
  that land in a window after the trigger, reconstructs any configured ambient-state trackers
  (e.g. an LED-mask bitfield) as of just before the trigger, and diffs responses/tracker values
  across every occurrence of that trigger to show which bytes/bits/characters actually move.
  Triggers and trackers are both optional -- with zero of either configured, you still get a
  full RX/TX inventory (everything falls into ORPHAN RX) as a starting point for a blind first
  pass over a capture you know nothing about yet.

config file (YAML), all fields optional except triggers[].payload_prefix and label:
  crc_len: 2                         # trailing CRC bytes to strip (2 = Hayward sum16)
  escape_mode: double                # double (default, DLE DLE) | escape_byte (DLE + escape_byte,
                                      #   e.g. Hayward's actual scheme -- see escape_byte below)
  escape_byte: 0x00                  # required when escape_mode is escape_byte; the marker byte
                                      #   the bus's rs485_frame hub declares as framing.escape.byte
  default_window_ms: 3000            # response-window safety cap
  default_until_next_trigger: true   # also close a window at the next trigger, if sooner
  ascii_min_run: 8                   # min length of a printable run to auto-diff as text
  min_occurrences_for_signature: 2   # occurrences needed before a diff is reported
  keepalive_payloads: ["0101"]       # optional; omit to auto-detect (>=5 repeats)
  auto_split: true                   # default; auto-partitions a trigger bucket whose own frame
                                      #   bytes (beyond payload_prefix/discover_bytes) turn out to
                                      #   be heterogeneous, recursively -- see "Two ways to start"
                                      #   in tools/README.md. Set false (or --no-auto-split) for
                                      #   the old flat grouping.
  triggers:
    # Precedence when >1 trigger matches the same line: longest payload_prefix wins (ties ->
    # first-listed wins). This is what lets a named trigger and a broader wildcard covering
    # the same family coexist in one config -- the named one always wins for lines it covers.
    - label: "Lights"
      payload_prefix: "00 83 01 00 01"   # hex, matched against the de-stuffed payload
      match_mask: null                   # optional hex mask, same length as prefix
      direction: "any"                   # any (default) | tx | rx
      discover_bytes: 0                  # >0: auto-split this wildcard by the next N
                                          #     bytes, one report entry per distinct value
                                          #     -- use this instead of naming every command
                                          #     up front, e.g. payload_prefix "00 83 01",
                                          #     discover_bytes 1 finds every wireless
                                          #     command byte in the log on its own.
  trackers:
    # offset = index of the field's first byte ON THE WIRE (lowest payload index).
    # width   = field length in bytes -- match the field's real width, not just what's been
    #           observed to vary so far (get this from a decoder/spec if one exists, e.g. the
    #           example below is a 32-bit field per hayward/aqualogic/bus.yaml's own comment,
    #           even though every currently-observed value happens to fit in the low 16 bits).
    # endian  = how those `width` bytes combine into one integer: "little" means
    #           payload[offset] is the LEAST-significant byte; "big" means payload[offset]
    #           is the MOST-significant byte. Example: payload[2:6] = "e8 01 00 00" on the
    #           wire decodes to 0x000001e8 under "little" (byte 2 is the LSB), 0xe8010000
    #           under "big".
    # For a TAGGED/optional field (e.g. Hayward's 04 0a container, where the LED body is only
    # at a fixed offset when a preceding tag byte says so), fold the tag into match_prefix
    # itself so the tracker only ever fires where offset is actually valid -- see
    # tools/README.md's "offset/width/endian" section for the worked 04 0a example.
    - label: "LED Mask"
      match_prefix: "01 02"
      offset: 2
      width: 4
      endian: "little"

    # kind: flag_scan / paired_flag_and -- for a per-bit or per-character flag instead of one
    # scalar field, backed by `regions` (each with its own match_prefix, resolved via a direct
    # offset or, with subblock_tag set, via a tagged sub-block lookup within a container frame
    # like 04 0a) instead of a single top-level match_prefix/offset. flag_scan reports bit `bit`
    # of every byte in the region: a bool for a 1-byte region, or a tuple of the byte positions
    # where it's set for a wider one. `index_set`, if given, only counts a byte as flagged when
    # its whole value is also a member of the set -- guards against misreading an unrelated odd
    # value as the flag on hardware/firmware where the byte means something else.
    # paired_flag_and reports the AND, bit-by-bit, of two consecutive `width`-byte spans starting
    # at the region, as a tuple of set bit positions -- e.g. a solid-state mask ANDed against a
    # second mask to find which bits are active in both.
    - label: "Display Text Flag"
      kind: flag_scan
      bit: 7
      regions:
        - match_prefix: "01 03"
          width: 40
        - match_prefix: "04 0a 83 00"
          subblock_tag: 0x03
          width: 40
      note: "optional caveat printed next to this tracker's diff in the report"

See tools/README.md for the full field reference and tools/configs/ for ready-to-run examples.
"""


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("logfile", type=Path, help="an esphome logs capture with dump_frames: true")
    parser.add_argument(
        "--config", type=Path, default=None, help="YAML config (see below); omit to run with no triggers/trackers"
    )
    parser.add_argument("--crc-len", type=int, default=None, help="overrides config crc_len")
    parser.add_argument(
        "--escape-mode",
        choices=("double", "escape_byte"),
        default=None,
        help="overrides config escape_mode (double: DLE DLE; escape_byte: DLE + --escape-byte, e.g. Hayward's 0x00)",
    )
    parser.add_argument(
        "--escape-byte",
        type=lambda s: int(s, 0),
        default=None,
        help="overrides config escape_byte (marker byte for escape_mode escape_byte, e.g. 0x00); accepts decimal or 0x-hex",
    )
    parser.add_argument(
        "--only-tracked",
        action="store_true",
        help="hide RX groups and diff entries that don't match any configured tracker (requires >=1 tracker)",
    )
    parser.add_argument(
        "--no-auto-split",
        action="store_true",
        help="disable auto-splitting a trigger bucket whose own frame bytes are heterogeneous "
        "(overrides config auto_split); use this to reproduce the old flat discover_bytes-only "
        "grouping, e.g. to match a hand-authored config's own intentional granularity",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.no_auto_split:
        config.auto_split = False
    if args.crc_len is not None:
        config.crc_len = args.crc_len
    if args.escape_mode is not None:
        config.escape_mode = args.escape_mode
    if args.escape_byte is not None:
        config.escape_byte = args.escape_byte
    if config.escape_mode == "escape_byte" and config.escape_byte is None:
        parser.error("escape_mode escape_byte requires --escape-byte (or config escape_byte)")
    if args.only_tracked and not config.trackers:
        parser.error("--only-tracked requires at least one tracker in --config")

    lines = parse_log(args.logfile, config.crc_len, escape_mode=config.escape_mode, escape_byte=config.escape_byte)
    report = analyze(lines, config)
    if args.only_tracked:
        report = filter_to_tracked(report, config.trackers)
    print(render_report(report, ascii_min_run=config.ascii_min_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
