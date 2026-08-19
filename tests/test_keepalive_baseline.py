"""Regression test for a defect found while writing test_coverage.py: the first cut of
_auto_keepalive_baseline() picked "whichever payload(s) tie for the max RX count" as the ambient
baseline. In a sparse log where every response happens to appear exactly once, every distinct
payload ties at count 1 -- so *everything* was misclassified as baseline noise and silently
folded out of both the orphan-RX and in-window-response reports. Per project policy, any defect
gets a test proving the failure before the fix; this is that test, now passing against the fix
(a minimum-repeat-count floor before anything is treated as baseline).
"""

from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log

TRIG_HEX = "0083010001"
RESP_A_HEX = "040a830002e801"
RESP_B_HEX = "040a8300020803"


def test_sparse_log_with_no_repeated_payload_does_not_treat_every_response_as_baseline(tmp_path):
    # Two distinct, each-seen-once RX payloads following a trigger -- neither is a keepalive, but
    # a naive "ties for max count" heuristic would call both baseline since they tie at count 1.
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.100", "RX", frame_hex(RESP_A_HEX, "0000")),
        ("18:03:16.200", "RX", frame_hex(RESP_B_HEX, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)])
    report = analyze(lines, config)
    occ = report.trigger_reports[0].occurrences[0]
    assert not occ.silent
    assert {g.payload for g in occ.groups} == {
        bytes.fromhex(RESP_A_HEX),
        bytes.fromhex(RESP_B_HEX),
    }
