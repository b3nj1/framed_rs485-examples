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


def test_response_that_also_matches_a_trigger_prefix_is_claimed_by_that_trigger_not_windowed(
    tmp_path,
):
    """rs485_frame-206.3.11 (documentation-only resolution -- see tools/README.md's trigger-
    precedence section and this bead's design/close notes for the rationale): a line gets at most
    one role. If a genuine ack for TriggerA's window also matches TriggerB's own matcher, it
    becomes ITS OWN TriggerB occurrence instead of a response inside TriggerA's window --
    `occ_by_line_no` exclusion in `analyze()` deliberately treats "is a trigger occurrence" and
    "is a window response" as mutually exclusive per line. This is a latent trap for a bus/config
    where an ack can share a command's prefix family (not the case for any bundled Hayward config
    today -- acks use frame_type `04 0a`, disjoint from the wireless/wired-local/wired-remote
    wildcard prefixes), and was judged not worth a structural fix relative to that risk. This test
    pins down the resulting, documented behavior so it doesn't silently change: TriggerA reads
    silent even though a real response for it existed, and that response surfaces as TriggerB's
    own occurrence instead.
    """
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex("0083010001", "0000")),  # TriggerA ("wireless") fires
        # The "ack" happens to itself match TriggerB's ("wired-remote") own matcher.
        ("18:03:16.100", "RX", frame_hex("000301020304", "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef("wireless", Matcher.from_hex("00 83 01"), discover_bytes=2, window_ms=3000),
            TriggerDef("wired-remote", Matcher.from_hex("00 03"), direction="any", window_ms=3000),
        ]
    )
    report = analyze(lines, config)

    wireless = next(tr for tr in report.trigger_reports if tr.label.startswith("wireless"))
    wired_remote = next(tr for tr in report.trigger_reports if tr.label == "wired-remote")

    # The real response never shows up inside TriggerA's window...
    assert wireless.occurrences[0].silent
    assert wireless.occurrences[0].groups == []

    # ...it instead becomes its own, unrelated-looking TriggerB occurrence.
    assert len(wired_remote.occurrences) == 1
    assert wired_remote.occurrences[0].occurrence.line.raw_hex == frame_hex("000301020304", "0000")
