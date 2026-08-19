from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log


def test_matcher_prefix_and_mask():
    # mask's last byte 0x00 means "ignore this byte" -- a per-request sequence byte, say.
    m = Matcher.from_hex("008301ff", "ffffff00")
    assert m.matches(bytes.fromhex("008301ff"))
    assert m.matches(bytes.fromhex("00830199"))
    assert not m.matches(bytes.fromhex("00830299"))


def test_direction_any_unifies_tx_and_rx_originated_same_command(tmp_path):
    # HA presses a button (TX), an OEM wireless panel presses the same logical button (RX).
    # Same payload_prefix, direction: any -- both must land in the same trigger's occurrence list.
    p = write_log(
        tmp_path,
        ("18:03:16.291", "TX", frame_hex("0083010001", "0098")),
        ("18:03:17.000", "RX", frame_hex("0083010001", "0098")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01 00 01"), direction="any")]
    )
    report = analyze(lines, config)
    tr = report.trigger_reports[0]
    assert len(tr.occurrences) == 2
    origins = {o.occurrence.line.direction for o in tr.occurrences}
    assert origins == {"TX", "RX"}


def test_direction_tx_only_filters_out_rx_occurrence(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.291", "TX", frame_hex("0083010001", "0098")),
        ("18:03:17.000", "RX", frame_hex("0083010001", "0098")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01 00 01"), direction="tx")]
    )
    report = analyze(lines, config)
    tr = report.trigger_reports[0]
    assert len(tr.occurrences) == 1
    assert tr.occurrences[0].occurrence.line.direction == "TX"
