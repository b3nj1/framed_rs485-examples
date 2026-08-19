"""Trigger precedence: when two or more configured triggers match the same line, exactly one
occurrence is created -- the longest-prefix (most specific) match wins, ties broken by config
list order. This is what makes it safe to mix named triggers with a broader wildcard/discover_bytes
trigger covering the same command family in one config, without every named button's presses also
being double-counted under the wildcard's bucket.
"""

from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log


def test_longer_prefix_wins_over_a_shorter_overlapping_one(tmp_path):
    p = write_log(tmp_path, ("18:03:16.000", "TX", frame_hex("0083018000", "0000")))
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef("wireless", Matcher.from_hex("00 83 01"), discover_bytes=2),
            TriggerDef("Filter", Matcher.from_hex("00 83 01 80")),
        ]
    )
    report = analyze(lines, config)
    labels = {tr.label for tr in report.trigger_reports}
    assert labels == {"Filter"}


def test_longer_prefix_wins_regardless_of_config_order(tmp_path):
    # Same as above but with the more-specific trigger listed *first* -- order must not matter,
    # only prefix length, or authors would have to remember to list specific triggers before
    # wildcards.
    p = write_log(tmp_path, ("18:03:16.000", "TX", frame_hex("0083018000", "0000")))
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef("Filter", Matcher.from_hex("00 83 01 80")),
            TriggerDef("wireless", Matcher.from_hex("00 83 01"), discover_bytes=2),
        ]
    )
    report = analyze(lines, config)
    labels = {tr.label for tr in report.trigger_reports}
    assert labels == {"Filter"}


def test_equal_length_prefixes_break_tie_by_config_list_order(tmp_path):
    p = write_log(tmp_path, ("18:03:16.000", "TX", frame_hex("00830180", "0000")))
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef("first-listed", Matcher.from_hex("00 83 01 80")),
            TriggerDef("second-listed", Matcher.from_hex("00 83 01 80")),
        ]
    )
    report = analyze(lines, config)
    labels = {tr.label for tr in report.trigger_reports}
    assert labels == {"first-listed"}


def test_no_line_ever_produces_two_occurrences_even_with_three_overlapping_triggers(tmp_path):
    p = write_log(tmp_path, ("18:03:16.000", "TX", frame_hex("0083018000", "0000")))
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef("all-wireless", Matcher.from_hex("00")),
            TriggerDef("wireless-family", Matcher.from_hex("00 83 01"), discover_bytes=2),
            TriggerDef("Filter", Matcher.from_hex("00 83 01 80")),
        ]
    )
    report = analyze(lines, config)
    total_occurrences = sum(len(tr.occurrences) for tr in report.trigger_reports)
    assert total_occurrences == 1
