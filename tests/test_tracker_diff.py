from pathlib import Path

from discovery_capture import Config, Matcher, TrackerDef, TriggerDef, analyze, parse_log

FIXTURE = Path(__file__).parent / "fixtures" / "lights_toggle_excerpt.log"


def test_tracker_diff_against_real_fixture_includes_discontinuity_noise():
    # This fixture is a discontinuous splice (see test_golden_real_capture.py's module docstring):
    # the ambient value just before the first Lights press here is a stale boot-time value
    # (0x0108), not the true immediate predecessor a continuous capture would show (0x01a8, per a
    # full-log run). So the aggregated varying_bits picks up extra bits from that gap, not just
    # the button's own bit -- 0x108^0x1e8=0xe0 and 0x168^0x128=0x40, OR'd together is 0xe0 (0x40 is
    # already a subset of 0xe0's bits). Ground truth from an actual run, not hand-computed; the
    # clean single-bit case is exercised separately in test_tracker_diff_isolates_a_clean_signal
    # against a synthetic log with no such gap.
    lines = parse_log(FIXTURE, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef("Lights", Matcher.from_hex("00 83 01 00 01"), until_next_trigger=True, window_ms=3000)
        ],
        trackers=[TrackerDef("LED Mask", Matcher.from_hex("01 02"), offset=2, width=4, endian="little")],
    )
    report = analyze(lines, config)
    tr = report.trigger_reports[0]
    td = tr.tracker_diffs["LED Mask"]
    assert len(td["pairs"]) == 2
    assert td["pairs"] == [(0x108, 0x1E8), (0x168, 0x128)]
    assert td["varying_bits"] == 0xE0


def test_tracker_diff_isolates_a_clean_signal(tmp_path):
    from helpers import frame_hex, write_log

    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex("040a830002a801", "0000")),  # ambient 0x01a8
        ("18:03:16.000", "TX", frame_hex("0083010001", "0000")),
        ("18:03:16.100", "RX", frame_hex("040a830002e801", "0000")),  # after: 0x01e8
        ("18:03:19.000", "RX", frame_hex("040a830002 68 01", "0000")),  # ambient 0x0168
        ("18:03:20.000", "TX", frame_hex("0083010001", "1111")),
        ("18:03:20.100", "RX", frame_hex("040a830002 28 01", "0000")),  # after: 0x0128
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        trackers=[TrackerDef("LED Mask", Matcher.from_hex("04 0a"), offset=5, width=2)],
    )
    report = analyze(lines, config)
    td = report.trigger_reports[0].tracker_diffs["LED Mask"]
    assert td["pairs"] == [(0x01A8, 0x01E8), (0x0168, 0x0128)]
    assert td["varying_bits"] == 0x40


def test_tracker_diff_absent_without_enough_pairs(tmp_path):
    from helpers import frame_hex, write_log

    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex("040a830002e801", "0000")),
        ("18:03:16.000", "TX", frame_hex("0083010001", "0000")),
        ("18:03:16.100", "RX", frame_hex("040a830002a801", "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        trackers=[TrackerDef("LED Mask", Matcher.from_hex("04 0a"), offset=5, width=2)],
        min_occurrences_for_signature=2,
    )
    report = analyze(lines, config)
    assert report.trigger_reports[0].tracker_diffs == {}
