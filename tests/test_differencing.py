from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log

TRIG_HEX = "0083010001"
MASK_ON_1 = "040a830002e801"  # bytes[5:7] = e8 01 = 0x01e8
MASK_OFF_1 = "040a830002a801"  # bytes[5:7] = a8 01 = 0x01a8, differs only in bit 0x40 of byte5
TEXT_ON = "040a830003" + "4c69676874732020202020202020204f6e2020"  # "Lights            On  "
TEXT_OFF = "040a830003" + "4c69676874732020202020202020204f666620"  # "Lights            Off "


def test_bit_diff_isolates_the_single_varying_byte_across_occurrences(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.100", "RX", frame_hex(MASK_ON_1, "0000")),
        ("18:03:20.000", "TX", frame_hex(TRIG_HEX, "1111")),
        ("18:03:20.100", "RX", frame_hex(MASK_OFF_1, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        min_occurrences_for_signature=2,
    )
    report = analyze(lines, config)
    tr = report.trigger_reports[0]
    length = len(bytes.fromhex(MASK_ON_1))
    bd = tr.bit_diffs[length]
    assert bd["n"] == 2
    varying_byte_indices = [i for i, b in enumerate(bd["varying_mask"]) if b != 0]
    assert varying_byte_indices == [5]
    assert bd["varying_mask"][5] == 0x40  # e8 ^ a8 == 0x40


def test_bit_diff_scoped_per_payload_shape_does_not_mix_mask_and_text_frames(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.100", "RX", frame_hex(MASK_ON_1, "0000")),
        ("18:03:17.700", "RX", frame_hex(TEXT_ON, "0000")),
        ("18:03:20.000", "TX", frame_hex(TRIG_HEX, "1111")),
        ("18:03:20.100", "RX", frame_hex(MASK_OFF_1, "0000")),
        ("18:03:21.700", "RX", frame_hex(TEXT_OFF, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        min_occurrences_for_signature=2,
        ascii_min_run=8,
    )
    report = analyze(lines, config)
    tr = report.trigger_reports[0]
    mask_len = len(bytes.fromhex(MASK_ON_1))
    text_len = len(bytes.fromhex(TEXT_ON))
    assert mask_len != text_len
    assert set(tr.bit_diffs.keys()) == {mask_len, text_len}


def test_ascii_diff_isolates_the_differing_substring(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:17.700", "RX", frame_hex(TEXT_ON, "0000")),
        ("18:03:20.000", "TX", frame_hex(TRIG_HEX, "1111")),
        ("18:03:21.700", "RX", frame_hex(TEXT_OFF, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        min_occurrences_for_signature=2,
        ascii_min_run=8,
    )
    report = analyze(lines, config)
    tr = report.trigger_reports[0]
    text_len = len(bytes.fromhex(TEXT_ON))
    ads = tr.ascii_diffs[text_len]
    assert len(ads) == 1
    # payload is a 5-byte header + "Lights" + 10 spaces + "On  " / "Off " -- the shared
    # header+"Lights"+spaces+leading "O" prefix must not appear in the diff, only the differing tail.
    assert ads[0]["span"] == (21, 23)
    assert set(ads[0]["values"]) == {"n ", "ff"}
