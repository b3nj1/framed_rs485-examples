"""Unit tests for tools/check_example_sync.py -- see that module's docstring for the two-bucket
model (untagged/shared vs flavor-tagged/exempt) these tests pin down."""

from pathlib import Path

import pytest

from check_example_sync import DEFAULT_PATH_A, DEFAULT_PATH_B, SyncCheckError, check_sync


FIXTURE_HEADER = """\
substitutions:
  name: example

esphome:
  name: ${name}

esp32:
  board: BOARDXX

logger:

api:
"""


def write_pair(tmp_path: Path, body_a: str, body_b: str) -> tuple[Path, Path]:
    path_a = tmp_path / "a.yaml"
    path_b = tmp_path / "b.yaml"
    path_a.write_text(FIXTURE_HEADER + body_a)
    path_b.write_text(FIXTURE_HEADER + body_b)
    return path_a, path_b


def test_identical_untagged_sections_pass(tmp_path: Path) -> None:
    body = """
      # --- Shared section ---
      - path: hayward/aqualogic/bus.yaml
"""
    path_a, path_b = write_pair(tmp_path, body, body)
    assert check_sync(path_a, path_b) == []


def test_divergence_in_untagged_section_is_caught_with_diff(tmp_path: Path) -> None:
    body_a = """
      # --- Shared section ---
      - path: hayward/aqualogic/bus.yaml
"""
    body_b = """
      # --- Shared section ---
      - path: hayward/aqualogic/OTHER.yaml
"""
    path_a, path_b = write_pair(tmp_path, body_a, body_b)
    errors = check_sync(path_a, path_b)
    assert len(errors) == 1
    assert "Shared section" in errors[0]
    assert "bus.yaml" in errors[0]
    assert "OTHER.yaml" in errors[0]


def test_untagged_section_missing_from_one_file_is_an_error(tmp_path: Path) -> None:
    body_a = """
      # --- Only in A ---
      - path: hayward/aqualogic/bus.yaml
"""
    body_b = """
      # --- Something else ---
      - path: hayward/aqualogic/bus.yaml
"""
    path_a, path_b = write_pair(tmp_path, body_a, body_b)
    errors = check_sync(path_a, path_b)
    assert len(errors) == 2
    joined = "\n".join(errors)
    assert "'Only in A' present in a.yaml but missing from b.yaml" in joined
    assert "'Something else' present in b.yaml but missing from a.yaml" in joined


def test_flavor_tagged_sections_differing_completely_do_not_fail(tmp_path: Path) -> None:
    body_a = """
      # --- Buttons: switch-like [buttons] ---
      - path: hayward/aqualogic/button.yaml
        vars: { button_name: "Filter" }
"""
    body_b = """
      # --- Switch outputs [switches] ---
      - path: hayward/aqualogic/switch.yaml
        vars: { switch_name: "Filter" }
"""
    path_a, path_b = write_pair(tmp_path, body_a, body_b)
    assert check_sync(path_a, path_b) == []


def test_flavor_tagged_section_present_in_only_one_file_does_not_fail(tmp_path: Path) -> None:
    body_a = """
      # --- Buttons: switch-like [buttons] ---
      - path: hayward/aqualogic/button.yaml
"""
    body_b = ""
    path_a, path_b = write_pair(tmp_path, body_a, body_b)
    assert check_sync(path_a, path_b) == []


def test_dangling_header_marker_is_a_parse_error(tmp_path: Path) -> None:
    body_a = """
      # --- Unclosed header with no closing dashes
      - path: hayward/aqualogic/bus.yaml
"""
    path_a, path_b = write_pair(tmp_path, body_a, "")
    with pytest.raises(SyncCheckError):
        check_sync(path_a, path_b)


def test_decorative_divider_line_is_not_treated_as_a_header(tmp_path: Path) -> None:
    body = """
      # --- Shared section ---
      # -----------------------------------------------------------------------------
      - path: hayward/aqualogic/bus.yaml
"""
    path_a, path_b = write_pair(tmp_path, body, body)
    assert check_sync(path_a, path_b) == []


def test_top_level_shared_key_divergence_is_caught(tmp_path: Path) -> None:
    body_a = FIXTURE_HEADER
    body_b = FIXTURE_HEADER.replace("board: BOARDXX", "board: some-other-board")
    path_a = tmp_path / "a.yaml"
    path_b = tmp_path / "b.yaml"
    path_a.write_text(body_a)
    path_b.write_text(body_b)
    errors = check_sync(path_a, path_b)
    assert any("esp32" in err for err in errors)


def test_real_example_device_pair_is_in_sync() -> None:
    assert check_sync(DEFAULT_PATH_A, DEFAULT_PATH_B) == []
