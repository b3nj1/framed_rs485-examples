from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log, render_report

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


def test_unrelated_trigger_truncates_a_slower_but_still_in_window_ack(tmp_path):
    """rs485_frame-206.3.10: until_next_trigger closes a window at the next occurrence of ANY
    configured trigger, not just another occurrence of the same trigger/label. In a busy capture,
    a genuinely slow-but-real ack for trigger A can be truncated out of A's own window because an
    unrelated trigger B fires in between -- even though the ack would have comfortably landed
    inside A's window_ms cap. The response then gets misattributed to B's window instead, and A is
    reported silent with no indication anything caused an early close.
    """
    trig_a_hex = frame_hex(TRIG_HEX, "0000")  # "Lights", payload_prefix "0083 01"
    trig_b_hex = frame_hex("00020000", "0000")  # unrelated trigger, different payload_prefix
    ack_hex = frame_hex(RESP_HEX, "0000")
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", trig_a_hex),  # trigger A fires
        ("18:03:16.050", "TX", trig_b_hex),  # unrelated trigger B fires 50ms later
        ("18:03:16.150", "RX", ack_hex),  # A's real ack, 150ms after A -- well inside A's window_ms
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef(
                "Lights", Matcher.from_hex("0083 01"), until_next_trigger=True, window_ms=3000
            ),
            TriggerDef("Wired", Matcher.from_hex("0002"), until_next_trigger=True, window_ms=3000),
        ]
    )
    report = analyze(lines, config)
    lights_report = next(tr for tr in report.trigger_reports if tr.label == "Lights")
    wired_report = next(tr for tr in report.trigger_reports if tr.label == "Wired")
    a_occ = lights_report.occurrences[0]
    b_occ = wired_report.occurrences[0]

    # The ack was misattributed to B's window instead of A's, and A reads as silent.
    assert a_occ.silent
    assert {g.payload for g in b_occ.groups} == {bytes.fromhex(RESP_HEX)}

    # A's window must be visibly flagged as having closed early because of B, not silently.
    assert a_occ.early_close_label == "Wired"
    assert a_occ.early_close_line_no == b_occ.occurrence.line.line_no

    rendered = render_report(report)
    assert "closed early" in rendered
    assert "Wired" in rendered
