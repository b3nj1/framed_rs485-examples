import pytest

from discovery_capture import Config, MalformedFrame, destuff, hex_to_bytes, parse_log

from helpers import frame_hex, write_log


def test_destuff_escape_byte_mode_undoes_literal_dle():
    # A payload byte equal to DLE (0x10) is wire-stuffed as DLE + escape_byte, not DLE DLE.
    raw = bytes.fromhex(frame_hex("0083011000ff", "0000", escape_mode="escape_byte", escape_byte=0x00))
    body = destuff(raw, escape_mode="escape_byte", escape_byte=0x00)
    assert body == hex_to_bytes("00830110 00ff 0000".replace(" ", ""))


def test_destuff_escape_byte_mode_rejects_dle_doubling():
    # DLE DLE is not a valid escape_byte-mode encoding (unless escape_byte itself is DLE).
    raw = bytes.fromhex(frame_hex("0083011000ff", "0000", escape_mode="double"))
    with pytest.raises(MalformedFrame):
        destuff(raw, escape_mode="escape_byte", escape_byte=0x00)


def test_destuff_escape_byte_mode_requires_escape_byte():
    raw = bytes.fromhex(frame_hex("0083010001", "0098"))
    with pytest.raises(ValueError):
        destuff(raw, escape_mode="escape_byte")


def test_destuff_rejects_unknown_escape_mode():
    raw = bytes.fromhex(frame_hex("0083010001", "0098"))
    with pytest.raises(ValueError):
        destuff(raw, escape_mode="triple")


def test_destuff_double_mode_is_unaffected_default():
    # Regression guard: default behavior (no escape_mode passed) is unchanged.
    raw = bytes.fromhex(frame_hex("0083011000ff", "0000"))
    body = destuff(raw)
    assert body == hex_to_bytes("00830110 00ff 0000".replace(" ", ""))


def test_config_from_dict_rejects_escape_byte_mode_without_escape_byte():
    with pytest.raises(ValueError):
        Config.from_dict({"escape_mode": "escape_byte", "triggers": []})


def test_config_from_dict_rejects_unknown_escape_mode():
    with pytest.raises(ValueError):
        Config.from_dict({"escape_mode": "nope", "triggers": []})


def test_config_from_dict_accepts_escape_byte_mode():
    config = Config.from_dict({"escape_mode": "escape_byte", "escape_byte": 0x00, "triggers": []})
    assert config.escape_mode == "escape_byte"
    assert config.escape_byte == 0x00


def test_parse_log_real_minus_button_frame_now_parses_under_escape_byte_mode(tmp_path):
    # A real Hayward wireless "Minus" TX frame whose command byte (0x10) collides with DLE. On
    # the wire (escape_byte/0x00, Hayward's actual scheme) this shows up as two literal "10 00"
    # sequences mid-payload -- previously misread by double-mode-only destuff() as an unescaped
    # DLE and dropped as unparseable.
    p = write_log(
        tmp_path,
        ("18:03:05.033", "TX", "1002008301100000000010000000000000b61003"),
    )
    lines = parse_log(p, crc_len=2, escape_mode="escape_byte", escape_byte=0x00)
    assert lines[0].payload is not None
    assert lines[0].payload == hex_to_bytes("00 83 01 10 00 00 00 10 00 00 00 00".replace(" ", ""))


def test_parse_log_real_minus_button_frame_fails_under_default_double_mode(tmp_path):
    # Same real frame, confirming the pre-fix false negative under the (still-default) double mode.
    p = write_log(
        tmp_path,
        ("18:03:05.033", "TX", "1002008301100000000010000000000000b61003"),
    )
    lines = parse_log(p, crc_len=2)
    assert lines[0].payload is None
