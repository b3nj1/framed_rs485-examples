"""Coverage-completeness invariant: every parsed RX line is accounted for exactly once across
{trigger lines themselves, in-window response groups, orphan RX} -- and every TX line is either a
trigger occurrence or simply not counted (TX lines are never "responses"). A refactor that starts
silently dropping or double-counting a line should fail this test regardless of which specific
scenario test happens to cover that line.
"""

from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log

TRIG_HEX = "0083010001"
RESP_A = "040a830002e801"
RESP_B = "040a8300020803"
RESP_C = "010203"


def _count_all_rx_accounted_for(report, total_rx: int) -> int:
    accounted = 0
    for tr in report.trigger_reports:
        for occ in tr.occurrences:
            accounted += sum(g.count for g in occ.groups)
    accounted += sum(g.count for g in report.orphan_groups)
    return accounted


def test_every_rx_line_counted_exactly_once_synthetic(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:15.000", "RX", frame_hex(RESP_C, "0000")),  # orphan, before any trigger
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.100", "RX", frame_hex(RESP_A, "0000")),
        ("18:03:16.100", "RX", frame_hex(RESP_A, "1111")),  # repeated payload
        ("18:03:20.000", "TX", frame_hex(TRIG_HEX, "1111")),
        ("18:03:20.100", "RX", frame_hex(RESP_B, "0000")),
        ("18:03:25.000", "RX", frame_hex(RESP_C, "2222")),  # orphan, after last window
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef("Lights", Matcher.from_hex("0083 01"), until_next_trigger=True, window_ms=3000)
        ]
    )
    report = analyze(lines, config)
    total_rx = sum(1 for l in lines if l.direction == "RX")
    assert _count_all_rx_accounted_for(report, total_rx) == total_rx == report.total_rx


def test_every_rx_line_counted_exactly_once_against_real_capture_excerpt():
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "lights_toggle_excerpt.log"
    lines = parse_log(fixture, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef(
                "Lights",
                Matcher.from_hex("00 83 01 00 01"),
                until_next_trigger=True,
                window_ms=3000,
            )
        ],
        trackers=[],
    )
    report = analyze(lines, config)
    total_rx = sum(1 for l in lines if l.direction == "RX" and l.payload is not None)
    assert _count_all_rx_accounted_for(report, total_rx) == total_rx
