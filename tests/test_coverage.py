from discovery_capture import Config, Matcher, TriggerDef, analyze, parse_log

from helpers import frame_hex, write_log

TRIG_HEX = "0083010001"
RESP_HEX = "040a830002e801"
BOOT_HEX = "040a83000208"


def test_orphan_rx_before_first_trigger_is_collected_not_dropped(tmp_path):
    p = write_log(
        tmp_path,
        ("18:02:45.877", "RX", frame_hex(BOOT_HEX, "0000")),  # boot-time announcement
        ("18:02:51.288", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:02:51.400", "RX", frame_hex(RESP_HEX, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)])
    report = analyze(lines, config)
    assert len(report.orphan_groups) == 1
    assert report.orphan_groups[0].payload == bytes.fromhex(BOOT_HEX)
    # and it must not also show up inside the trigger's own window
    occ = report.trigger_reports[0].occurrences[0]
    assert bytes.fromhex(BOOT_HEX) not in {g.payload for g in occ.groups}


def test_orphan_rx_in_a_capped_window_gap(tmp_path):
    # window_ms cap closes the first trigger's window well before the second trigger fires;
    # a response landing in that gap belongs to neither window and must be orphaned, not dropped.
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        ("18:03:16.100", "RX", frame_hex(RESP_HEX, "0000")),  # inside window
        ("18:03:17.000", "RX", frame_hex(BOOT_HEX, "0000")),  # in the gap: >300ms after trigger 1
        ("18:03:20.000", "TX", frame_hex(TRIG_HEX, "1111")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(
        triggers=[
            TriggerDef(
                "Lights", Matcher.from_hex("0083 01"), until_next_trigger=True, window_ms=300
            )
        ]
    )
    report = analyze(lines, config)
    assert len(report.orphan_groups) == 1
    assert report.orphan_groups[0].payload == bytes.fromhex(BOOT_HEX)


def test_silent_trigger_reported_not_omitted(tmp_path):
    p = write_log(
        tmp_path,
        ("18:03:16.000", "TX", frame_hex(TRIG_HEX, "0000")),
        # no RX at all follows before the next trigger
        ("18:03:20.000", "TX", frame_hex(TRIG_HEX, "1111")),
        ("18:03:20.200", "RX", frame_hex(RESP_HEX, "0000")),
    )
    lines = parse_log(p, crc_len=2)
    config = Config(triggers=[TriggerDef("Lights", Matcher.from_hex("0083 01"), window_ms=3000)])
    report = analyze(lines, config)
    occs = report.trigger_reports[0].occurrences
    assert len(occs) == 2  # both occurrences are still reported
    assert occs[0].silent
    assert occs[0].groups == []
    assert not occs[1].silent
