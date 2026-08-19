from discovery_capture import MalformedFrame, destuff, hex_to_bytes, parse_log

from helpers import frame_hex, write_log


def test_parses_rx_and_tx_lines_ignores_others(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.291", "TX", frame_hex("0083010001", "0098")),
        ("18:03:16.348", "RX", frame_hex("040a83000201", "018e")),
    )
    with open(p, "a") as f:
        f.write("[18:03:16.400][C][template.sensor:017]: Template Sensor 'Air Temperature'\n")
        f.write("[18:03:16.455][S][text_sensor]: 'LED Mask' >> '0x000001E8'\n")

    lines = parse_log(p, crc_len=2)
    assert len(lines) == 2
    assert lines[0].direction == "TX"
    assert lines[1].direction == "RX"


def test_timestamp_parsed_to_seconds_of_day(tmp_path):
    p = write_log(tmp_path, ("01:02:03.456", "RX", frame_hex("0101", "0014")))
    lines = parse_log(p, crc_len=2)
    assert lines[0].ts == 1 * 3600 + 2 * 60 + 3 + 0.456


def test_destuff_strips_framing():
    raw = bytes.fromhex(frame_hex("0083010001", "0098"))
    body = destuff(raw)
    assert body == hex_to_bytes("00830100010098")


def test_destuff_undoes_escaped_literal_dle_mid_payload():
    # A payload byte that happens to equal DLE (0x10) must round-trip through stuffing/destuffing.
    raw = bytes.fromhex(frame_hex("0083011000ff", "0000"))
    body = destuff(raw)
    assert body == hex_to_bytes("00830110 00ff 0000".replace(" ", ""))


def test_destuff_rejects_malformed_frame():
    import pytest

    with pytest.raises(MalformedFrame):
        destuff(hex_to_bytes("0002008301100003"))  # doesn't start with DLE STX


def test_crc_len_2_strips_two_trailing_bytes(tmp_path):
    p = write_log(tmp_path, ("18:03:16.291", "TX", frame_hex("0083010001", "0098")))
    lines = parse_log(p, crc_len=2)
    assert lines[0].payload == hex_to_bytes("0083010001")


def test_crc_len_1_strips_one_trailing_byte(tmp_path):
    p = write_log(tmp_path, ("18:03:16.291", "TX", frame_hex("008301000198", "12")))
    lines = parse_log(p, crc_len=1)
    assert lines[0].payload == hex_to_bytes("008301000198")


def test_parses_ansi_colorized_lines(tmp_path):
    # `esphome logs` run interactively (not through a plain pipe/redirect that disables color)
    # wraps the severity tag in an SGR escape and terminates each line with a reset code, e.g.
    # "[HH:MM:SS.mmm]\x1b[0;36m[D][rs485_frame:335]: RX <hex>\x1b[0m\r\n" -- a real capture seen
    # 2026-08-19 was entirely in this form and silently produced zero parsed lines (no error, no
    # warning) because _LOG_LINE_RE required "][D]" with nothing between the timestamp and tag.
    p = tmp_path / "capture.log"
    hexstr = frame_hex("0083010001", "0098")
    p.write_text(
        f"[18:03:16.291]\x1b[0;36m[D][rs485_frame:335]: TX {hexstr}\x1b[0m\r\n"
        f"[18:03:16.348]\x1b[0;35m[C][uart.idf:268]:   Wake on data RX: ENABLED\x1b[0m\r\n"
    )
    lines = parse_log(p, crc_len=2)
    assert len(lines) == 1
    assert lines[0].direction == "TX"
