"""rs485_frame-206.3.8: auto-split a trigger bucket whose own trigger-frame bytes are
heterogeneous, instead of silently reporting one homogeneous-looking group that's actually
several distinct buttons sharing a prefix. Fixtures here are shaped like the two real collapsed
buckets that motivated this feature: the wireless AUX-B family (one level of collapse, subcode
byte 5) and the wired-local main panel's "00 02 00 00" bucket (two levels -- the top-level 2-byte
discover_bytes subcode collapses three buttons that only diverge 2 bytes deeper still).
"""

from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log


def test_auto_split_disabled_reproduces_the_wireless_aux_b_collapse(tmp_path):
    # payload_prefix "00 83 01", discover_bytes=2 -- Valve3/Valve4/Heater1 all share subcode
    # "00 00" at this 2-byte discovery depth, so every occurrence lands in one "[0000]" bucket;
    # the real per-button code is one byte deeper still (payload[5]), invisible to discover_bytes
    # here (this is exactly what the deeper, hand-authored "wireless AUX-B (subcode)" wildcard in
    # the bundled config exists to catch today).
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex("00830100" "0001")),  # Valve3
        ("18:03:17.000", "TX", frame_hex("00830100" "0001")),  # Valve3 again
        ("18:03:18.000", "TX", frame_hex("00830100" "0002")),  # Valve4/Heater2
        ("18:03:19.000", "TX", frame_hex("00830100" "0004")),  # Heater1
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("wireless", Matcher.from_hex("00 83 01"), discover_bytes=2)],
        auto_split=False,
    )
    report = analyze(lines, config)
    labels = {tr.label: len(tr.occurrences) for tr in report.trigger_reports}
    assert labels == {"wireless [0000]": 4}  # collapsed: looks like one ambiguous bucket


def test_auto_split_default_recovers_the_three_real_aux_b_buttons(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex("00830100" "0001")),  # Valve3
        ("18:03:17.000", "TX", frame_hex("00830100" "0001")),  # Valve3 again
        ("18:03:18.000", "TX", frame_hex("00830100" "0002")),  # Valve4/Heater2
        ("18:03:19.000", "TX", frame_hex("00830100" "0004")),  # Heater1
    )
    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("wireless", Matcher.from_hex("00 83 01"), discover_bytes=2)])
    report = analyze(lines, config)
    labels = {tr.label: len(tr.occurrences) for tr in report.trigger_reports}
    assert "wireless [0000]" not in labels
    assert labels == {
        "wireless [0000] [01]": 2,
        "wireless [0000] [02]": 1,
        "wireless [0000] [04]": 1,
    }


def test_auto_split_disabled_reproduces_the_wired_local_00_00_two_level_collapse(tmp_path):
    # payload_prefix "00 02", discover_bytes=2 -- three real buttons (Valve3/Valve4/Heater1) all
    # share subcode "00 00" at the top level and only diverge 2 bytes deeper still (payload[4:6]).
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex("0002" "0000" "0100")),  # Valve3
        ("18:03:17.000", "TX", frame_hex("0002" "0000" "0100")),  # Valve3 again
        ("18:03:18.000", "TX", frame_hex("0002" "0000" "0200")),  # Valve4/Heater2
        ("18:03:19.000", "TX", frame_hex("0002" "0000" "0400")),  # Heater1
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("wired-local", Matcher.from_hex("00 02"), discover_bytes=2)],
        auto_split=False,
    )
    report = analyze(lines, config)
    labels = {tr.label: len(tr.occurrences) for tr in report.trigger_reports}
    assert labels == {"wired-local [0000]": 4}  # collapsed: still looks like one bucket


def test_auto_split_default_recurses_two_levels_to_recover_the_wired_local_buttons(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex("0002" "0000" "0100")),  # Valve3
        ("18:03:17.000", "TX", frame_hex("0002" "0000" "0100")),  # Valve3 again
        ("18:03:18.000", "TX", frame_hex("0002" "0000" "0200")),  # Valve4/Heater2
        ("18:03:19.000", "TX", frame_hex("0002" "0000" "0400")),  # Heater1
    )
    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("wired-local", Matcher.from_hex("00 02"), discover_bytes=2)])
    report = analyze(lines, config)
    labels = {tr.label: len(tr.occurrences) for tr in report.trigger_reports}
    # Only reachable, pre-this-bead, by hand-adding a second discover_bytes trigger 2 bytes
    # deeper -- here the tool alone, with only the top-level wildcard configured, finds it.
    assert "wired-local [0000]" not in labels
    assert labels == {
        "wired-local [0000] [01]": 2,
        "wired-local [0000] [02]": 1,
        "wired-local [0000] [04]": 1,
    }


def test_auto_split_leaves_a_genuinely_homogeneous_bucket_alone(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex("00830180", "0000")),
        ("18:03:17.000", "TX", frame_hex("00830180", "1111")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("Filter", Matcher.from_hex("00 83 01 80"))])
    report = analyze(lines, config)
    labels = {tr.label: len(tr.occurrences) for tr in report.trigger_reports}
    assert labels == {"Filter": 2}
