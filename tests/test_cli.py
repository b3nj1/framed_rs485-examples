import json
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).parent.parent / "tools" / "discovery_capture.py"


def test_help_documents_the_config_schema():
    result = subprocess.run([sys.executable, str(TOOL), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    # someone reading --help cold should be able to write a config without opening the source
    for term in (
        "payload_prefix",
        "discover_bytes",
        "match_prefix",
        "crc_len",
        "min_occurrences_for_signature",
        "example:",
    ):
        assert term in result.stdout, term


def test_only_tracked_without_trackers_errors_cleanly(tmp_path):
    logfile = tmp_path / "empty.log"
    logfile.write_text("")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"triggers": [{"label": "x", "payload_prefix": "01"}]}))
    result = subprocess.run(
        [sys.executable, str(TOOL), str(logfile), "--config", str(config), "--only-tracked"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "tracker" in result.stderr.lower()


def test_escape_mode_escape_byte_requires_escape_byte_flag_or_config(tmp_path):
    logfile = tmp_path / "empty.log"
    logfile.write_text("")
    result = subprocess.run(
        [sys.executable, str(TOOL), str(logfile), "--escape-mode", "escape_byte"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "escape_byte" in result.stderr.lower()


def test_escape_mode_escape_byte_via_cli_flags_parses_real_minus_button_frame(tmp_path):
    logfile = tmp_path / "minus.log"
    logfile.write_text(
        "[18:03:05.033][D][rs485_frame:611]: TX 1002008301100000000010000000000000b61003\n"
    )
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"triggers": [{"label": "Minus", "payload_prefix": "00 83 01 10"}]}))
    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            str(logfile),
            "--config",
            str(config),
            "--escape-mode",
            "escape_byte",
            "--escape-byte",
            "0x00",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Minus" in result.stdout
    assert "SUMMARY: 1 triggers" in result.stdout


def test_runs_end_to_end_against_real_fixture_with_bundled_config():
    fixture = Path(__file__).parent / "fixtures" / "lights_toggle_excerpt.log"
    config = Path(__file__).parent.parent / "tools" / "configs" / "hayward_aqualogic.yaml"
    result = subprocess.run(
        [sys.executable, str(TOOL), str(fixture), "--config", str(config)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Lights" in result.stdout
    assert "SUMMARY" in result.stdout
