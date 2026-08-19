from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log

TRIG_HEX = "0083010001"
KEEPALIVE_HEX = "0101"
MASK_RESP_HEX = "040a830002e801"
TEXT_RESP_HEX = "040a83000320202020204c6967687473"


def test_distinct_payloads_grouped_separately_same_frame_type(tmp_path):
    # Same frame_type (04 0a) produces two unrelated payload shapes in one window -- must not collapse.
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.100", "RX", frame_hex(MASK_RESP_HEX, "0000")),
        ("18:03:17.700", "RX", frame_hex(TEXT_RESP_HEX, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)])
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert len(occ.groups) == 2
    payloads = {g.payload for g in occ.groups}
    assert payloads == {bytes.fromhex(MASK_RESP_HEX), bytes.fromhex(TEXT_RESP_HEX)}


def test_repeated_identical_payload_folds_to_one_row_with_count(tmp_path):
    rows = [("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000"))]
    for i in range(8):
        rows.append((f"18:03:16.{100+i*10}", "RX", frame_hex(KEEPALIVE_HEX, "0000")))
    p = write_log(tmp_path, *rows)
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)],
        keepalive_payloads=[],
    )
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert len(occ.groups) == 1
    assert occ.groups[0].payload == bytes.fromhex(KEEPALIVE_HEX)
    assert occ.groups[0].count == 8
    # keepalive is the sole/most-frequent RX payload -> auto-classified as baseline -> the
    # occurrence is baseline-only, not silent (rs485_frame-206.3.9: a real, constant response must
    # never be reported as "no response" purely because it recurred often enough to be classified
    # as ambient noise).
    assert not occ.silent
    assert occ.baseline_only
