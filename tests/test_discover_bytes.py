from pathlib import Path

from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log

FIXTURE = Path(__file__).parent / "fixtures" / "lights_toggle_excerpt.log"


def test_discover_bytes_splits_a_wildcard_into_distinct_labeled_buckets(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex("00830180", "0000")),  # Filter
        ("18:03:17.000", "TX", frame_hex("00830140", "0000")),  # Pool/Spa Mode
        ("18:03:18.000", "TX", frame_hex("00830180", "1111")),  # Filter again
    )
    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("button", Matcher.from_hex("00 83 01"), discover_bytes=1)])
    report = analyze(lines, config)
    labels = {tr.label: len(tr.occurrences) for tr in report.trigger_reports}
    assert labels == {"button [80]": 2, "button [40]": 1}


def test_one_discriminator_byte_can_collapse_distinct_commands_real_fixture_with_auto_split_off():
    # Real-world finding: Lights (word 0x00010000) and a different AUX-family command (word
    # 0x00020000) share the same first data byte (0x00) -- a 1-byte discriminator merges them
    # into one bucket, undercounting. This used to be undetectable by the tool itself (only a
    # suspiciously merged-looking occurrence count hinted at it) -- with auto_split at its new
    # default, the merge no longer happens at all (see the next test); this one pins the
    # explicitly-disabled ("old flat grouping") behavior, which --no-auto-split exists to
    # preserve exactly.
    lines = parse_log(FIXTURE, crc_len=2)
    config = Config(
        triggers=[TriggerDef("wireless", Matcher.from_hex("00 83 01"), discover_bytes=1)],
        auto_split=False,
    )
    report = analyze(lines, config)
    bucket_00 = next(tr for tr in report.trigger_reports if tr.label == "wireless [00]")
    assert len(bucket_00.occurrences) == 4  # 2x Lights + 2x the other 0x00xx-leading command


def test_auto_split_default_separates_the_same_merged_bucket_without_widening_discover_bytes():
    # Same fixture/config as above, but with auto_split at its new default (on): the tool alone
    # notices the "wireless [00]" bucket's own trigger-frame bytes disagree beyond the 1
    # discover_bytes already consumed, and splits it -- no hand-widened discover_bytes needed.
    lines = parse_log(FIXTURE, crc_len=2)
    config = Config(triggers=[TriggerDef("wireless", Matcher.from_hex("00 83 01"), discover_bytes=1)])
    report = analyze(lines, config)
    labels = {tr.label: len(tr.occurrences) for tr in report.trigger_reports}
    assert "wireless [00]" not in labels
    assert labels["wireless [00] [01]"] == 2  # Lights on + off
    assert labels["wireless [00] [02]"] == 1  # the other 0x00xx-leading command


def test_two_discriminator_bytes_disambiguates_the_same_family():
    lines = parse_log(FIXTURE, crc_len=2)
    config = Config(triggers=[TriggerDef("wireless", Matcher.from_hex("00 83 01"), discover_bytes=2)])
    report = analyze(lines, config)
    labels = {tr.label: len(tr.occurrences) for tr in report.trigger_reports}
    assert labels["wireless [0001]"] == 2  # Lights on + off
    assert labels["wireless [0002]"] == 1  # the other command, no longer merged in


def test_discover_bucket_boundaries_still_close_windows_for_each_other(tmp_path):
    # A window for one discovered bucket must still be closed by the *next* occurrence of any
    # bucket under the same wildcard def -- discover_bytes buckets are still one trigger family
    # for windowing purposes, only split apart for reporting/diffing.
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex("00830180", "0000")),
        ("18:03:16.100", "RX", frame_hex("0101", "2222")),
        ("18:03:16.500", "TX", frame_hex("00830140", "1111")),
        ("18:03:16.600", "RX", frame_hex("0303", "3333")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef(
                "button", Matcher.from_hex("00 83 01"), discover_bytes=1, until_next_trigger=True, window_ms=3000
            )
        ]
    )
    report = analyze(lines, config)
    filter_report = next(tr for tr in report.trigger_reports if tr.label == "button [80]")
    occ = filter_report.occurrences[0]
    assert {g.payload for g in occ.groups} == {bytes.fromhex("0101")}
