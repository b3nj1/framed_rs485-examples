import pytest

from discovery_capture import Config, Matcher, TrackerDef, TriggerDef, analyze, filter_to_tracked, parse_log

from helpers import frame_hex, write_log

TRIG_HEX = "0083010001"
TRACKED_HEX = "040a830002e801"
CHATTER_HEX = "0c010064"
# A display-text confirmation frame -- doesn't match a bitmask tracker's byte pattern at all, but
# is plainly not noise: "Lights            On  " / "...Off " (equal length, like the real capture).
TEXT_ON_HEX = "0103" + "4c69676874732020202020202020204f6e2020"
TEXT_OFF_HEX = "0103" + "4c69676874732020202020202020204f666620"


def _report(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:14.000", "RX", frame_hex(CHATTER_HEX, "0000")),  # orphan chatter
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.100", "RX", frame_hex(TRACKED_HEX, "0000")),  # matches the tracker
        ("18:03:16.150", "RX", frame_hex(CHATTER_HEX, "1111")),  # in-window chatter
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        trackers=[TrackerDef("LED Mask", Matcher.from_hex("04 0a"), offset=5, width=2)],
    )
    return analyze(lines, config), config


def test_only_tracked_hides_orphan_and_in_window_chatter(tmp_path):
    report, config = _report(tmp_path)
    filtered = filter_to_tracked(report, config.trackers)
    assert filtered.orphan_groups == []
    occ = filtered.trigger_reports[0].occurrences[0]
    assert {g.payload for g in occ.groups} == {bytes.fromhex(TRACKED_HEX)}


def test_only_tracked_requires_at_least_one_tracker():
    with pytest.raises(ValueError):
        filter_to_tracked(analyze([], Config()), [])


def test_only_tracked_also_hides_response_diff_entries_for_untracked_shapes(tmp_path):
    # A response bit-diff/ascii-diff for a shape that isn't itself a tracked frame is exactly the
    # chatter --only-tracked exists to hide -- leaving the diff block behind while the group
    # listing it describes disappears would be inconsistent.
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.100", "RX", frame_hex(TRACKED_HEX, "0000")),
        ("18:03:16.150", "RX", frame_hex(CHATTER_HEX, "1111")),
        ("18:03:20.000", "TX", frame_hex(TRIG_HEX, "2222")),
        ("18:03:20.100", "RX", frame_hex("040a830002a801", "0000")),  # second tracked-shape sample
        ("18:03:20.150", "RX", frame_hex(CHATTER_HEX, "3333")),  # second chatter-shape sample
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        trackers=[TrackerDef("LED Mask", Matcher.from_hex("04 0a"), offset=5, width=2)],
        min_occurrences_for_signature=2,
    )
    report = analyze(lines, config)
    tr = report.trigger_reports[0]
    tracked_len = len(bytes.fromhex(TRACKED_HEX))
    chatter_len = len(bytes.fromhex(CHATTER_HEX))
    assert tracked_len in tr.bit_diffs and chatter_len in tr.bit_diffs  # both present before filtering

    filtered = filter_to_tracked(report, config.trackers)
    filtered_tr = filtered.trigger_reports[0]
    assert tracked_len in filtered_tr.bit_diffs
    assert chatter_len not in filtered_tr.bit_diffs


def test_only_tracked_hides_readable_text_that_does_not_match_the_tracker(tmp_path):
    # --only-tracked is strict tracker-byte-pattern match, full stop -- a display-text
    # confirmation frame ("Lights ... Turned On") is hidden right along with binary chatter if it
    # doesn't match the configured tracker's own pattern, same as anything else untracked. (An
    # earlier revision carved out an ascii-decodable exception; reverted on user request.)
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.100", "RX", frame_hex(TRACKED_HEX, "0000")),  # tracker-matched binary field
        ("18:03:16.150", "RX", frame_hex(CHATTER_HEX, "1111")),  # binary noise, hidden
        ("18:03:17.700", "RX", frame_hex(TEXT_ON_HEX, "0000")),  # readable text, also hidden
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        trackers=[TrackerDef("LED Mask", Matcher.from_hex("04 0a"), offset=5, width=2)],
    )
    report = analyze(lines, config)
    filtered = filter_to_tracked(report, config.trackers)
    occ = filtered.trigger_reports[0].occurrences[0]
    payloads = {g.payload for g in occ.groups}
    assert payloads == {bytes.fromhex(TRACKED_HEX)}


def test_only_tracked_hides_ascii_diff_entries_for_an_untracked_shape(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.100", "RX", frame_hex(TRACKED_HEX, "0000")),
        ("18:03:17.700", "RX", frame_hex(TEXT_ON_HEX, "0000")),
        ("18:03:20.000", "TX", frame_hex(TRIG_HEX, "1111")),
        ("18:03:20.100", "RX", frame_hex("040a830002a801", "0000")),
        ("18:03:21.700", "RX", frame_hex(TEXT_OFF_HEX, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        trackers=[TrackerDef("LED Mask", Matcher.from_hex("04 0a"), offset=5, width=2)],
        min_occurrences_for_signature=2,
    )
    report = analyze(lines, config)
    text_len = len(bytes.fromhex(TEXT_ON_HEX))
    assert text_len in report.trigger_reports[0].ascii_diffs  # sanity: it exists before filtering

    filtered = filter_to_tracked(report, config.trackers)
    assert text_len not in filtered.trigger_reports[0].ascii_diffs
