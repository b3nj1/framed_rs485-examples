"""Regression test against a real trimmed excerpt of an actual dump_frames capture
(tests/fixtures/lights_toggle_excerpt.log): the boot-time state-announcement block (originally
lines 15-265 of the source capture) spliced with the Lights on/off toggle sequence (originally
lines 940-1080). The splice is discontinuous -- everything between those two source ranges is
missing -- so the ambient LED-Mask tracker only reflects what this fixture itself contains, not
the fuller value a continuous capture would show (see the module docstring in
discovery_capture.py's design notes: a full-log run showed 0x01A8 immediately before the same
press, this trimmed fixture shows 0x0108, the last boot-time value still in scope). That
discontinuity is fine for a self-contained regression fixture; it is not fine to silently assume
the two numbers should match, so this is asserted explicitly rather than left implicit.

Values below were captured directly from a real run against this fixture, not hand-computed.
"""

from pathlib import Path

from discovery_capture import Config, Matcher, TrackerDef, TriggerDef, analyze, parse_log

FIXTURE = Path(__file__).parent / "fixtures" / "lights_toggle_excerpt.log"


def _analyze():
    lines = parse_log(FIXTURE, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef(
                "Lights",
                Matcher.from_hex("00 83 01 00 01"),
                until_next_trigger=True,
                window_ms=3000,
            )
        ],
        trackers=[TrackerDef("LED Mask", Matcher.from_hex("01 02"), offset=2, width=4, endian="little")],
        min_occurrences_for_signature=2,
    )
    return analyze(lines, config)


def test_two_lights_occurrences_found_with_distinct_ambient_snapshots():
    report = analyze(
        parse_log(FIXTURE, crc_len=2),
        Config(
            triggers=[
                TriggerDef(
                    "Lights", Matcher.from_hex("00 83 01 00 01"), until_next_trigger=True, window_ms=3000
                )
            ],
            trackers=[TrackerDef("LED Mask", Matcher.from_hex("01 02"), offset=2, width=4)],
        ),
    )
    tr = report.trigger_reports[0]
    assert len(tr.occurrences) == 2
    assert not tr.occurrences[0].silent
    assert not tr.occurrences[1].silent
    # Both occurrences are the same physical TX command (a stateless toggle) but the ambient
    # snapshot differs between them -- proof the tracker replays state per-occurrence, not once.
    assert tr.occurrences[0].ambient["LED Mask"] != tr.occurrences[1].ambient["LED Mask"]
    assert tr.occurrences[0].ambient["LED Mask"] == 0x0108
    assert tr.occurrences[1].ambient["LED Mask"] == 0x0168


def test_lights_on_and_off_responses_are_distinct_payloads_not_collapsed():
    report = _analyze()
    tr = report.trigger_reports[0]
    on_mask_payloads = {g.payload for g in tr.occurrences[0].groups if g.payload[:2] == bytes.fromhex("040a")}
    off_mask_payloads = {g.payload for g in tr.occurrences[1].groups if g.payload[:2] == bytes.fromhex("040a")}
    assert on_mask_payloads.isdisjoint(off_mask_payloads)


def test_bit_diff_surfaces_the_short_mask_only_response_shape():
    report = _analyze()
    tr = report.trigger_reports[0]
    # length 13 is the short mask-only "04 0a 83 00 02 <mask:2> 00 00 00 00 00 00" shape.
    bd = tr.bit_diffs[13]
    assert bd["n"] == 2
    varying = [i for i, b in enumerate(bd["varying_mask"]) if b != 0]
    assert varying == [5]
    # Only two samples exist in this fixture -- can't yet rule out an unrelated concurrent bit
    # riding along; min_occurrences_for_signature exists for exactly this reason. Recorded here
    # as ground truth, not claimed as a clean single-bit signature.
    assert bd["varying_mask"][5] == 0xC0


def test_ascii_diff_isolates_on_off_word_in_display_text_response():
    report = _analyze()
    tr = report.trigger_reports[0]
    # length 55 is the long "04 0a ... display text" shape carrying "...Turned On/Off..."
    ads = tr.ascii_diffs[55]
    assert len(ads) == 1
    assert set(ads[0]["values"]) == {"ff", "n "}


def test_coverage_completeness_against_real_fixture():
    report = _analyze()
    total_rx = report.total_rx
    accounted = sum(
        sum(g.count for g in occ.groups) for tr in report.trigger_reports for occ in tr.occurrences
    )
    accounted += sum(g.count for g in report.orphan_groups)
    assert accounted == total_rx
