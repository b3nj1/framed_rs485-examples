"""Bundled example configs (tools/configs/*.yaml) must stay parseable and, since they're the
first thing a new user copies and edits, must stay useful against a real capture -- not just
syntactically valid YAML. As more buses get added to tools/configs/, add a case here rather than
trusting that a config someone edited still loads.
"""

import yaml
from pathlib import Path

from discovery_capture import Config, analyze, parse_log

CONFIGS_DIR = Path(__file__).parent.parent / "tools" / "configs"
REAL_FIXTURE = Path(__file__).parent / "fixtures" / "lights_toggle_excerpt.log"


def test_hayward_aqualogic_config_loads():
    with open(CONFIGS_DIR / "hayward_aqualogic.yaml") as f:
        d = yaml.safe_load(f)
    config = Config.from_dict(d)
    assert {t.label for t in config.triggers} == {
        "Filter",
        "Pool/Spa Mode",
        "Plus",
        "Minus",
        "Left",
        "System Off / Service",
        "Menu",
        "Right",
        "Lights",
        "Heater1",
        "wireless AUX-B (subcode)",
        "wireless (other/AUX, undecoded)",
        "wired-local (main panel)",
        "wired-remote",
    }
    assert [t.label for t in config.trackers] == [
        "LED Mask (01 02)",
        "LED Mask (04 0a)",
        "Display Text Flag",
        "LED Mask Flag",
        "Local Setting Index Flag",
    ]


def test_hayward_aqualogic_config_04_0a_led_mask_agrees_with_01_02_in_real_fixture():
    # The whole point of tracking both side by side: 04 0a is under active investigation as a
    # single-frame stand-in for the separate 01 02 (LED)/01 03 (display) frames. If they ever
    # disagreed, that would be a real finding about 04 0a's reliability as positive confirmation
    # -- here, on this fixture, they agree at every Lights occurrence.
    with open(CONFIGS_DIR / "hayward_aqualogic.yaml") as f:
        config = Config.from_dict(yaml.safe_load(f))
    lines = parse_log(REAL_FIXTURE, crc_len=config.crc_len)
    report = analyze(lines, config)
    lights = next(tr for tr in report.trigger_reports if tr.label == "Lights")
    assert len(lights.occurrences) == 2
    for occ in lights.occurrences:
        assert occ.ambient["LED Mask (01 02)"] == occ.ambient["LED Mask (04 0a)"]


def test_hayward_aqualogic_config_finds_lights_presses_in_real_fixture():
    with open(CONFIGS_DIR / "hayward_aqualogic.yaml") as f:
        config = Config.from_dict(yaml.safe_load(f))
    lines = parse_log(REAL_FIXTURE, crc_len=config.crc_len)
    report = analyze(lines, config)
    lights = next(tr for tr in report.trigger_reports if tr.label == "Lights")
    assert len(lights.occurrences) == 2
    assert not any(o.silent for o in lights.occurrences)


def test_named_buttons_take_precedence_over_the_bundled_wireless_wildcard():
    # This config deliberately mixes named triggers (4-byte prefixes) with a broader wildcard
    # ("wireless", 3-byte prefix, discover_bytes 2) covering the same command family -- a real
    # Filter press matches both. Longest-prefix precedence must resolve this to "Filter" only,
    # not double-report it under "wireless [8000]" too.
    with open(CONFIGS_DIR / "hayward_aqualogic.yaml") as f:
        config = Config.from_dict(yaml.safe_load(f))
    lines = parse_log(REAL_FIXTURE, crc_len=config.crc_len)
    report = analyze(lines, config)
    lights_line_nos = {
        o.occurrence.line.line_no
        for tr in report.trigger_reports
        for o in tr.occurrences
        if tr.label == "Lights"
    }
    wireless_line_nos = {
        o.occurrence.line.line_no
        for tr in report.trigger_reports
        for o in tr.occurrences
        if tr.label.startswith("wireless (other/AUX, undecoded) [")
    }
    assert lights_line_nos, "expected at least one Lights occurrence in the fixture"
    assert lights_line_nos.isdisjoint(wireless_line_nos)


def test_hayward_aqualogic_discovery_config_loads():
    with open(CONFIGS_DIR / "hayward_aqualogic_discovery.yaml") as f:
        config = Config.from_dict(yaml.safe_load(f))
    assert all(t.discover_bytes > 0 for t in config.triggers)


def test_hayward_aqualogic_discovery_config_finds_the_named_buttons_without_being_told_their_names():
    # The whole point of discover_bytes: this config knows nothing button-specific, yet it must
    # still separate Lights from Filter etc. into distinct buckets on a real capture.
    with open(CONFIGS_DIR / "hayward_aqualogic_discovery.yaml") as f:
        config = Config.from_dict(yaml.safe_load(f))
    lines = parse_log(REAL_FIXTURE, crc_len=config.crc_len)
    report = analyze(lines, config)
    labels = {tr.label for tr in report.trigger_reports}
    assert "wireless [0001]" in labels  # Lights
    assert "wireless [0002]" in labels  # the other 0x00xx-leading command in this fixture


def test_no_line_in_the_real_fixture_is_claimed_by_two_hayward_triggers():
    # The named buttons and the wildcard catch-alls are allowed to have overlapping prefixes by
    # design (longest-prefix precedence resolves it) -- what must never happen is any single log
    # line ending up counted as an occurrence of more than one trigger label.
    with open(CONFIGS_DIR / "hayward_aqualogic.yaml") as f:
        config = Config.from_dict(yaml.safe_load(f))
    lines = parse_log(REAL_FIXTURE, crc_len=config.crc_len)
    report = analyze(lines, config)
    seen_line_nos = set()
    for tr in report.trigger_reports:
        for orep in tr.occurrences:
            line_no = orep.occurrence.line.line_no
            assert line_no not in seen_line_nos, (tr.label, line_no)
            seen_line_nos.add(line_no)
