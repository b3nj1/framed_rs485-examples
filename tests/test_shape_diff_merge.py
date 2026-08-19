"""_render_shape_diffs merges bit-diff and ascii-diff output per payload shape so the same byte
range isn't shown twice in two encodings (see its docstring). But "this byte's index falls inside
a run that happened to be printable in the *first example* payload" must not be treated as proof
the byte is actually text -- a numeric field (e.g. a bitmask byte) can coincidentally be printable
in one occurrence and not another. Real concern raised during review: the LED-Mask tracker byte
could, for some other capture, land inside a detected ascii run purely by coincidence of its byte
value, and folding it away would hide a genuinely non-textual field's diff.
"""

from discovery_capture import TriggerReport, _render_shape_diffs


def test_byte_position_inside_ascii_span_stays_in_bit_diff_if_ever_non_printable():
    tr = TriggerReport(
        label="test",
        occurrences=[],
        bit_diffs={
            10: {
                "example_hex": "00 41 42 43 44 45 46 47 48 00",
                "n": 2,
                "varying_mask": b"\x00\x00\x00\x00\x00\xff\x00\x00\x00\x00",
                # byte[5] is inside the detected ascii span (2:9 below) in the first example
                # (0x45 = 'E'), but the *second* occurrence shows a non-printable 0x01 there --
                # proof it's not actually a text character, just coincidentally printable once.
                "byte_values": {5: [0x45, 0x01]},
            }
        },
        ascii_diffs={
            10: [
                {
                    "example_hex": "00 41 42 43 44 45 46 47 48 00",
                    "span": (2, 9),
                    "values": ["BCDEFGH", "BCD\x01FGH"],
                }
            ]
        },
        tracker_diffs={},
    )
    lines = _render_shape_diffs(tr)
    text = "\n".join(lines)
    assert "chars[2:9]" in text
    assert "byte[5] in {0x45, 0x01}" in text


def test_byte_position_inside_ascii_span_is_folded_away_when_always_printable():
    tr = TriggerReport(
        label="test",
        occurrences=[],
        bit_diffs={
            10: {
                "example_hex": "00 41 42 43 44 45 46 47 48 00",
                "n": 2,
                "varying_mask": b"\x00\x00\x00\x00\x00\xff\x00\x00\x00\x00",
                "byte_values": {5: [0x45, 0x58]},  # 'E' and 'X' -- always printable, genuine text
            }
        },
        ascii_diffs={
            10: [
                {
                    "example_hex": "00 41 42 43 44 45 46 47 48 00",
                    "span": (2, 9),
                    "values": ["BCDEFGH", "BCDXFGH"],
                }
            ]
        },
        tracker_diffs={},
    )
    lines = _render_shape_diffs(tr)
    text = "\n".join(lines)
    assert "chars[2:9]" in text
    assert "byte[5]" not in text
