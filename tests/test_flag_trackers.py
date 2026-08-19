"""Tests for TrackerDef's region-based flag mechanisms (kind: flag_scan / paired_flag_and),
covering the three Hayward AquaLogic per-character/per-bit flag signals: a display-text
character flag (bit 7 of each of the 40 display-text bytes, present in both the standalone
`01 03` frame and the `04 0A` container's `03` sub-block), a paired LED-mask flag (AND of two
consecutive 4-byte spans -- solid mask and a second mask -- present in `01 02` and `04 0A`'s
`02` sub-block), and a legacy-firmware single-bit flag on the `01 03` trailing byte, gated to a
known set of byte values via `index_set`.

Also covers the report-level correlation these mechanisms exist for: does a flagged ambient
tracker value line up with whether the trigger's response window shows a visible RX change
(`occ.silent`)? Both the "holds" and "does not hold" cases are tested per mechanism -- these are
hypotheses to verify against real data, not invariants the tool should assume or enforce.
"""

from discovery_capture import Config, Matcher, Region, TrackerDef, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log

PLUS_HEX = "00 83 01 20 00 00 00 20 00 00 00"
MINUS_HEX = "00 83 01 10 00 00 00 10 00 00 00"


# ---------------------------------------------------------------------------
# Mechanism 1: display-text character flag -- bit 7 of each of 40 text bytes.
# ---------------------------------------------------------------------------


def _text_flag_tracker():
    return TrackerDef(
        label="Display Text Flag",
        kind="flag_scan",
        bit=7,
        regions=[
            Region(Matcher.from_hex("01 03"), width=40),
            Region(Matcher.from_hex("04 0a 83 00"), width=40, subblock_tag=0x03),
        ],
    )


def _text_payload_hex(flagged=()):
    chars = bytearray(b"\x20" * 40)
    for i in flagged:
        chars[i] |= 0x80
    return "01 03" + chars.hex() + "00"


def _text_payload_04_0a_hex(flagged=()):
    chars = bytearray(b"\x20" * 40)
    for i in flagged:
        chars[i] |= 0x80
    return "04 0a 83 00 03" + chars.hex() + "00"


def test_display_text_flag_extracts_positions_from_standalone_01_03():
    payload = bytes.fromhex(_text_payload_hex(flagged=(3, 17)).replace(" ", ""))
    tracker = _text_flag_tracker()
    assert tracker.matches(payload)
    assert tracker.extract(payload) == (3, 17)


def test_display_text_flag_extracts_positions_from_04_0a_subblock():
    payload = bytes.fromhex(_text_payload_04_0a_hex(flagged=(0, 39)).replace(" ", ""))
    tracker = _text_flag_tracker()
    assert tracker.matches(payload)
    assert tracker.extract(payload) == (0, 39)


def test_display_text_flag_empty_tuple_when_nothing_flagged():
    payload = bytes.fromhex(_text_payload_hex().replace(" ", ""))
    tracker = _text_flag_tracker()
    assert tracker.extract(payload) == ()


def test_display_text_flag_ignores_the_trailing_display_flags_byte():
    # sub_offset defaults to 0, width 40 -- the region must stop at the 40th text char and never
    # read bit 7 of the 41st (Display Flags/NUL) byte as though it were part of the text.
    payload_hex = "01 03" + ("20" * 40) + "ff"  # trailing byte has every bit set, including 7
    payload = bytes.fromhex(payload_hex.replace(" ", ""))
    tracker = _text_flag_tracker()
    assert tracker.extract(payload) == ()


def test_correlation_holds_blinking_text_with_visible_plus_response(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex(_text_payload_hex(flagged=(5,)))),
        ("18:03:16.000", "TX", frame_hex(PLUS_HEX)),
        ("18:03:16.100", "RX", frame_hex(_text_payload_hex(flagged=(6,)))),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Plus", Matcher.from_hex(PLUS_HEX), window_ms=3000)],
        trackers=[_text_flag_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert occ.ambient["Display Text Flag"] == (5,)
    assert occ.silent is False


def test_correlation_holds_no_blink_and_no_visible_response(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex(_text_payload_hex())),
        ("18:03:16.000", "TX", frame_hex(PLUS_HEX)),
        # no RX at all inside the window
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Plus", Matcher.from_hex(PLUS_HEX), window_ms=3000)],
        trackers=[_text_flag_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert occ.ambient["Display Text Flag"] == ()
    assert occ.silent is True


def test_correlation_does_not_hold_blinking_text_but_no_visible_response(tmp_path):
    # The tool must report exactly what happened -- a blinking element with no visible
    # response -- rather than assuming or masking a mismatch with the hypothesis.
    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex(_text_payload_hex(flagged=(2,)))),
        ("18:03:16.000", "TX", frame_hex(PLUS_HEX)),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Plus", Matcher.from_hex(PLUS_HEX), window_ms=3000)],
        trackers=[_text_flag_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert occ.ambient["Display Text Flag"] == (2,)
    assert occ.silent is True


# ---------------------------------------------------------------------------
# Mechanism 2: paired LED-mask flag -- AND of two consecutive 4-byte spans.
# ---------------------------------------------------------------------------


def _led_mask_flag_tracker():
    return TrackerDef(
        label="LED Mask Flag",
        kind="paired_flag_and",
        regions=[
            Region(Matcher.from_hex("01 02"), width=4),
            Region(Matcher.from_hex("04 0a 83 00"), width=4, subblock_tag=0x02),
        ],
    )


def test_led_mask_flag_ands_the_two_spans_from_01_02():
    # solid mask byte0 = 0b0000_0101 (bits 0,2), second mask byte0 = 0b0000_0001 (bit 0) -> AND
    # leaves only bit 0 set.
    payload = bytes.fromhex("0102" + "05000000" + "01000000")
    tracker = _led_mask_flag_tracker()
    assert tracker.extract(payload) == (0,)


def test_led_mask_flag_ands_the_two_spans_from_04_0a_subblock():
    payload = bytes.fromhex("040a830002" + "05000000" + "01000000")
    tracker = _led_mask_flag_tracker()
    assert tracker.extract(payload) == (0,)


def test_led_mask_flag_empty_when_masks_share_no_set_bit():
    payload = bytes.fromhex("0102" + "01000000" + "02000000")
    tracker = _led_mask_flag_tracker()
    assert tracker.extract(payload) == ()


def test_matches_is_false_for_a_04_0a_frame_missing_this_trackers_subblock():
    # Regression: a 04 0a container frame carrying ONLY the display-text (0x03) sub-block still
    # matches this tracker's region's outer prefix ("04 0a 83 00") even though it has no 0x02 LED
    # sub-block at all -- each sub-block is independently optional. matches() must reflect
    # extractability (resolve the specific sub-block), not just the outer container prefix,
    # otherwise the ambient-replay "last write wins" logic in _ambient_snapshot wrongly overwrites
    # a real prior LED-mask value with "unknown" the moment a text-only 04 0a frame goes by.
    text_only = bytes.fromhex("040a830003" + ("20" * 40) + "00")
    tracker = _led_mask_flag_tracker()
    assert tracker.matches(text_only) is False
    assert tracker.extract(text_only) is None


def test_ambient_replay_does_not_blank_a_led_mask_flag_on_a_text_only_04_0a_frame(tmp_path):
    led_before = "0102" + "05000000" + "01000000"  # AND -> bit 0, a real value
    text_only = "040a830003" + ("20" * 40) + "00"  # no 0x02 sub-block at all
    p = write_log(
        tmp_path,
        ("18:03:14.000", "RX", frame_hex(led_before)),
        ("18:03:14.500", "RX", frame_hex(text_only)),
        ("18:03:15.000", "TX", frame_hex(MINUS_HEX)),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Minus", Matcher.from_hex(MINUS_HEX), window_ms=3000)],
        trackers=[_led_mask_flag_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert occ.ambient["LED Mask Flag"] == (0,)


def test_correlation_holds_led_flag_set_with_visible_plus_response(tmp_path):
    before = "0102" + "05000000" + "01000000"  # AND -> bit 0
    after = "0102" + "05000000" + "05000000"  # AND -> bits 0, 2
    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex(before)),
        ("18:03:16.000", "TX", frame_hex(MINUS_HEX)),
        ("18:03:16.100", "RX", frame_hex(after)),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Minus", Matcher.from_hex(MINUS_HEX), window_ms=3000)],
        trackers=[_led_mask_flag_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert occ.ambient["LED Mask Flag"] == (0,)
    assert occ.silent is False


def test_correlation_holds_no_led_flag_and_no_visible_response(tmp_path):
    idle = "0102" + "00000000" + "00000000"
    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex(idle)),
        ("18:03:16.000", "TX", frame_hex(MINUS_HEX)),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Minus", Matcher.from_hex(MINUS_HEX), window_ms=3000)],
        trackers=[_led_mask_flag_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert occ.ambient["LED Mask Flag"] == ()
    assert occ.silent is True


def test_correlation_does_not_hold_led_flag_set_but_no_visible_response(tmp_path):
    before = "0102" + "05000000" + "01000000"  # AND -> bit 0, flagged
    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex(before)),
        ("18:03:16.000", "TX", frame_hex(MINUS_HEX)),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Minus", Matcher.from_hex(MINUS_HEX), window_ms=3000)],
        trackers=[_led_mask_flag_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert occ.ambient["LED Mask Flag"] == (0,)
    assert occ.silent is True


# ---------------------------------------------------------------------------
# Mechanism 3: legacy local-settings display-flags bit 0, gated to a known index_set.
# ---------------------------------------------------------------------------


def _local_setting_index_flag_tracker():
    return TrackerDef(
        label="Local Setting Index Flag",
        kind="flag_scan",
        bit=0,
        index_set={0x05, 0x09},
        regions=[
            Region(Matcher.from_hex("01 03"), width=1, sub_offset=40),
            Region(Matcher.from_hex("04 0a 83 00"), width=1, subblock_tag=0x03, sub_offset=40),
        ],
    )


def test_local_setting_index_flag_true_for_a_known_index_value():
    payload = bytes.fromhex("0103" + ("20" * 40) + "05")
    tracker = _local_setting_index_flag_tracker()
    assert tracker.extract(payload) is True


def test_local_setting_index_flag_false_for_a_zero_trailing_byte():
    payload = bytes.fromhex("0103" + ("20" * 40) + "00")
    tracker = _local_setting_index_flag_tracker()
    assert tracker.extract(payload) is False


def test_local_setting_index_flag_filters_out_odd_values_outside_the_index_set():
    # bit 0 is set (0x07 is odd) but 0x07 isn't a known P-4 local-settings index -- index_set
    # exists precisely to avoid misreading an unrelated odd value on hardware/firmware where
    # this byte means something else.
    payload = bytes.fromhex("0103" + ("20" * 40) + "07")
    tracker = _local_setting_index_flag_tracker()
    assert tracker.extract(payload) is False


def test_local_setting_index_flag_from_04_0a_subblock():
    payload = bytes.fromhex("040a8300" + "03" + ("20" * 40) + "09")
    tracker = _local_setting_index_flag_tracker()
    assert tracker.extract(payload) is True


def test_correlation_holds_local_setting_flag_with_visible_plus_response(tmp_path):
    before = "0103" + ("20" * 40) + "05"
    after = "0103" + ("20" * 40) + "09"
    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex(before)),
        ("18:03:16.000", "TX", frame_hex(PLUS_HEX)),
        ("18:03:16.100", "RX", frame_hex(after)),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Plus", Matcher.from_hex(PLUS_HEX), window_ms=3000)],
        trackers=[_local_setting_index_flag_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert occ.ambient["Local Setting Index Flag"] is True
    assert occ.silent is False


def test_correlation_holds_no_local_setting_flag_and_no_visible_response(tmp_path):
    idle = "0103" + ("20" * 40) + "00"
    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex(idle)),
        ("18:03:16.000", "TX", frame_hex(PLUS_HEX)),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Plus", Matcher.from_hex(PLUS_HEX), window_ms=3000)],
        trackers=[_local_setting_index_flag_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert occ.ambient["Local Setting Index Flag"] is False
    assert occ.silent is True


def test_correlation_does_not_hold_local_setting_flag_set_but_no_visible_response(tmp_path):
    before = "0103" + ("20" * 40) + "05"
    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex(before)),
        ("18:03:16.000", "TX", frame_hex(PLUS_HEX)),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Plus", Matcher.from_hex(PLUS_HEX), window_ms=3000)],
        trackers=[_local_setting_index_flag_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert occ.ambient["Local Setting Index Flag"] is True
    assert occ.silent is True


# ---------------------------------------------------------------------------
# Open question: is a physical-panel Plus/Minus press (RX-originated) observed on the bus at
# all? `direction: any` must catch an RX-originated trigger line exactly like a TX one, so a
# real capture with a physical-panel press can answer this either way.
# ---------------------------------------------------------------------------


def test_direction_any_trigger_matches_an_rx_originated_press(tmp_path):
    from discovery_capture import _find_occurrences

    p = write_log(
        tmp_path,
        ("18:03:16.000", "RX", frame_hex(PLUS_HEX)),  # physical panel keypress, not our TX
    )
    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("Plus", Matcher.from_hex(PLUS_HEX), direction="any")])
    occs = _find_occurrences(lines, config)
    assert len(occs) == 1
    assert occs[0].line.direction == "RX"
