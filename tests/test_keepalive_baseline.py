"""Regression test for a defect found while writing test_coverage.py: the first cut of
_auto_keepalive_baseline() picked "whichever payload(s) tie for the max RX count" as the ambient
baseline. In a sparse log where every response happens to appear exactly once, every distinct
payload ties at count 1 -- so *everything* was misclassified as baseline noise and silently
folded out of both the orphan-RX and in-window-response reports. Per project policy, any defect
gets a test proving the failure before the fix; this is that test, now passing against the fix
(a minimum-repeat-count floor before anything is treated as baseline).

Also covers rs485_frame-206.3.9: once a payload *does* cross that floor, the tool used to treat
it as pure noise -- excluded from every summary-level signal (silent count, response diff) with
no way to tell a baseline-only response apart from a truly silent trigger. A protocol whose ack is
a short, unvarying frame (unlike Hayward's own `04 0a` status, which happens to carry a mask that
changes) crosses the auto-keepalive threshold during any discovery session with many button
presses, and every one of those button's occurrences was then reported "(no response)" even though
the device acked every single press.
"""

from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log, render_report

from helpers import frame_hex, write_log

TRIG_HEX = "0083010001"
RESP_A_HEX = "040a830002e801"
RESP_B_HEX = "040a8300020803"

ACK_HEX = "9902"
ACK_VARIANT_HEX = "9982"  # same length as ACK_HEX, differs in the high bit of byte 1


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


def _build_repeated_ack_log(tmp_path, n=6):
    rows = []
    for i in range(n):
        rows.append((f"18:{3 + i:02d}:16.000", "TX", frame_hex(TRIG_HEX, "0000")))
        rows.append((f"18:{3 + i:02d}:16.100", "RX", frame_hex(ACK_HEX, "0000")))
    return write_log(tmp_path, *rows)


def test_constant_ack_repeated_ge_5_times_is_never_reported_silent(tmp_path):
    p = _build_repeated_ack_log(tmp_path, n=6)
    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)])
    report = analyze(lines, config)
    tr = report.trigger_reports[0]
    assert len(tr.occurrences) == 6

    # The ack recurred >=5 times, so it IS auto-classified as keepalive baseline...
    assert bytes.fromhex(ACK_HEX) in report.keepalive_baseline_counts
    assert report.keepalive_baseline_counts[bytes.fromhex(ACK_HEX)] == 6

    # ...but every occurrence got a real response, so none of them may be reported silent, and
    # each should be distinguishable as "baseline-only" rather than truly silent.
    for occ in tr.occurrences:
        assert not occ.silent, "a real, constant ack response must never be reported as silent"
        assert occ.baseline_only
        assert {g.payload for g in occ.groups} == {bytes.fromhex(ACK_HEX)}

    # And it must not be dropped from the response diff purely because it's baseline.
    assert len(ACK_HEX) // 2 in tr.bit_diffs

    rendered = render_report(report)
    assert "(no response)" not in rendered
    assert "AUTO-KEEPALIVE BASELINE (n=6): 99 02" in rendered


def test_occasionally_varying_baseline_payload_is_not_swallowed(tmp_path):
    # 5 occurrences ack with the constant ACK_HEX (crosses the auto-keepalive floor), the 6th
    # acks with a same-length variant that differs in one bit -- that variant is genuinely
    # informative and must survive in the response diff, not get folded away alongside the
    # constant majority once the majority payload is classified as baseline.
    rows = []
    for i in range(5):
        rows.append((f"18:{3 + i:02d}:16.000", "TX", frame_hex(TRIG_HEX, "0000")))
        rows.append((f"18:{3 + i:02d}:16.100", "RX", frame_hex(ACK_HEX, "0000")))
    rows.append(("18:09:16.000", "TX", frame_hex(TRIG_HEX, "0000")))
    rows.append(("18:09:16.100", "RX", frame_hex(ACK_VARIANT_HEX, "0000")))
    p = write_log(tmp_path, *rows)

    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)])
    report = analyze(lines, config)
    tr = report.trigger_reports[0]

    length = len(ACK_HEX) // 2
    assert length in tr.bit_diffs
    byte_values = tr.bit_diffs[length]["byte_values"]
    assert byte_values, "the occasional variant byte must show up as varying, not be swallowed"
    varying_values = {v for vals in byte_values.values() for v in vals}
    assert 0x82 in varying_values and 0x02 in varying_values
