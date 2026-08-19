from discovery_capture import Config, Matcher, TrackerDef, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log

TRIG_HEX = "0083010001"
# 04 0a frame_type, mask bytes at offset 5:7 little-endian, mirroring the real LED-Mask capture.
MASK_BEFORE_HEX = "040a830002a801"  # bytes[5:7] = a8 01 -> 0x01a8
MASK_AFTER_HEX = "040a830002e801"  # bytes[5:7] = e8 01 -> 0x01e8


def _tracker():
    return TrackerDef("LED Mask", Matcher.from_hex("04 0a"), offset=5, width=2, endian="little")


def test_tracker_reads_little_endian_value(tmp_path):
    p = write_log(tmp_path, ("18:03:15.000", "RX", frame_hex(MASK_AFTER_HEX, "0000")))
    lines = parse_log(p, crc_len=2)
    config = Config(trackers=[_tracker()])
    from discovery_capture import _ambient_snapshot

    snap = _ambient_snapshot(config.trackers, lines, before_line_no=999)
    assert snap["LED Mask"] == 0x01E8


def test_offset_is_the_wire_earliest_byte_regardless_of_endian():
    # offset=5, width=2 always means "the field occupies payload[5] and payload[6] on the wire" --
    # endian only changes which of those two is treated as most-significant, not which bytes are
    # read. payload[5:7] == e8 01: little-endian makes byte 5 (0xe8) the LSB -> 0x01e8; big-endian
    # makes byte 5 the MSB instead -> 0xe801. Same two wire bytes, same offset, opposite value.
    payload = bytes.fromhex("040a830002e801")  # bytes[5:7] = e8 01
    little = TrackerDef("x", Matcher.from_hex("04 0a"), offset=5, width=2, endian="little")
    big = TrackerDef("x", Matcher.from_hex("04 0a"), offset=5, width=2, endian="big")
    assert little.extract(payload) == 0x01E8
    assert big.extract(payload) == 0xE801


def test_ambient_snapshot_is_strictly_before_trigger_not_including_response(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:15.971", "RX", frame_hex(MASK_BEFORE_HEX, "0000")),  # ambient before press
        ("18:03:16.291", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.348", "RX", frame_hex(MASK_AFTER_HEX, "0000")),  # response to the press
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        trackers=[_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    # The reported ambient value must be the pre-press 0x01a8, never the post-press 0x01e8 --
    # a tracker snapshot must not leak the trigger's own effect back into its precondition.
    assert occ.ambient["LED Mask"] == 0x01A8


def test_tracker_replay_is_chronological_by_line_order_not_just_timestamp(tmp_path):
    # Same millisecond timestamp for two updates -- line order must still be respected.
    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex(MASK_BEFORE_HEX, "0000")),
        ("18:03:15.000", "RX", frame_hex(MASK_AFTER_HEX, "0000")),
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        trackers=[_tracker()],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert occ.ambient["LED Mask"] == 0x01E8
