"""render_report must decode printable-ASCII runs inline next to the raw hex in every group
listing (orphan and in-window alike), not just in the ascii-diff section -- a defect found from
real usage: the report was showing "42 6c 6f 77 65 72" and making the reader manually decode it
to "Blower" by hand instead of just showing "Blower".
"""

from discovery_capture import (
    Config,
    Matcher,
    TriggerDef,
    _ascii_annotation,
    analyze,
    parse_log,
    render_report,
)

from helpers import frame_hex, write_log

TRIG_HEX = "0083010002"
BLOWER_ON_HEX = "040a83000320202020202020426c6f7765722020202020202020202020205475726e6564204f6e202020202020"


def test_ascii_annotation_decodes_a_printable_run():
    payload = bytes.fromhex(BLOWER_ON_HEX)
    text = _ascii_annotation(payload, min_run=8)
    assert text is not None
    assert "Blower" in text
    assert "Turned On" in text


def test_ascii_annotation_none_below_min_run():
    assert _ascii_annotation(bytes.fromhex("040a83000102"), min_run=8) is None


def test_render_report_shows_decoded_ascii_next_to_hex_for_in_window_group(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.170", "RX", frame_hex(BLOWER_ON_HEX, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("wireless [0002]", Matcher.from_hex("0083 01 00 02"), window_ms=3000)])
    report = analyze(lines, config)
    text = render_report(report, ascii_min_run=config.ascii_min_run)
    assert 'ascii="' in text
    assert "Blower" in text
    assert "Turned On" in text


def test_render_report_shows_decoded_ascii_for_orphan_group(tmp_path):
    p = write_log(tmp_path, ("18:03:16.000", "RX", frame_hex(BLOWER_ON_HEX, "0000")))
    lines = parse_log(p, crc_len=2)
    report = analyze(lines, Config())
    text = render_report(report, ascii_min_run=8)
    assert "ORPHAN RX" in text
    assert "Blower" in text
