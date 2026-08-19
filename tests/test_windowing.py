from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log

TRIG_HEX = "0083010001"
RESP_HEX = "040a830002e801"


def test_until_next_trigger_captures_response_arbitrarily_far_before_next_trigger(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:17.700", "RX", frame_hex(RESP_HEX, "0000")),  # 1.7s later, still before next trigger
        ("18:03:20.000", "TX", frame_hex(TRIG_HEX, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef(
                "Lights", Matcher.from_hex("0083 01"), until_next_trigger=True, window_ms=100000
            )
        ]
    )
    report = analyze(lines, config)
    first_occ = report.trigger_reports[0].occurrences[0]
    assert len(first_occ.groups) == 1


def test_fixed_window_ms_alone_misses_a_late_response(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:17.700", "RX", frame_hex(RESP_HEX, "0000")),  # arrives after a 300ms cap
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef(
                "Lights", Matcher.from_hex("0083 01"), until_next_trigger=False, window_ms=300
            )
        ]
    )
    report = analyze(lines, config)
    first_occ = report.trigger_reports[0].occurrences[0]
    assert first_occ.groups == []
    assert first_occ.silent


def test_both_forms_together_whichever_closes_first(tmp_path):
    # until_next_trigger + a window_ms cap that is *tighter* than the next trigger's arrival.
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.150", "RX", frame_hex(RESP_HEX, "0000")),  # inside the 200ms cap
        ("18:03:16.900", "RX", frame_hex(RESP_HEX, "1111")),  # after the 200ms cap closes it
        ("18:03:20.000", "TX", frame_hex(TRIG_HEX, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef(
                "Lights", Matcher.from_hex("0083 01"), until_next_trigger=True, window_ms=200
            )
        ]
    )
    report = analyze(lines, config)
    first_occ = report.trigger_reports[0].occurrences[0]
    assert len(first_occ.groups) == 1
    assert first_occ.groups[0].payload == bytes.fromhex(RESP_HEX)


def test_overlapping_triggers_second_fires_before_first_windowms_cap_elapses(tmp_path):
    # Trigger B fires 500ms after trigger A, but A's window_ms cap alone would be 3000ms --
    # until_next_trigger must still close A's window at B, not run past it.
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.200", "RX", frame_hex(RESP_HEX, "0000")),
        ("18:03:16.500", "TX", frame_hex(TRIG_HEX, "1111")),
        ("18:03:16.700", "RX", frame_hex(RESP_HEX, "2222")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef(
                "Lights", Matcher.from_hex("0083 01"), until_next_trigger=True, window_ms=3000
            )
        ]
    )
    report = analyze(lines, config)
    occs = report.trigger_reports[0].occurrences
    assert len(occs) == 2
    assert len(occs[0].groups) == 1  # only the 16.200 response, not the one after 16.500
    assert len(occs[1].groups) == 1
