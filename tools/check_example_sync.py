"""Check that hayward/aqualogic/example-device.yaml and example-device-switches.yaml stay in
sync on their shared boilerplate.

The two files are siblings: same substitutions:/esphome:/esp32:/logger: blocks, same required
bus.yaml, same "LED indicators: status" / "Buttons: status-navigation" sections, same
diagnostics/response-monitor documentation -- but example-device.yaml's "switch-like" LED/Buttons
entries are replaced in example-device-switches.yaml by a "Switch outputs" section built on
switch.yaml/switch_secondary.yaml instead. Nothing has ever mechanically checked that the shared
parts don't quietly drift apart when one file gets edited and the other doesn't -- this script
closes that gap.

Two-bucket model, no per-entry markers:
  - UNTAGGED sections (`# --- Title ---`) and the four top-level YAML keys (substitutions,
    esphome, esp32, logger) are shared boilerplate: they must be present in both files, with
    byte-identical content, in either file. This is the real drift-risk category.
  - FLAVOR-TAGGED sections (`# --- Title [tag] ---`, e.g. `[buttons]`/`[switches]`) are allowed to
    exist in only one file, or to differ completely, with zero content comparison -- they're the
    section that's *supposed* to differ between the two files.

Section headers are single comment lines of the form `# --- Title ---` (any leading indent, an
optional flavor tag `[tag]` at the end of Title, and optional free text after the closing `---`).
A decorative full-dash divider line (`# -------...-------`, no title text) is not a header. A line
that starts like a header (`# ---`) but has no matching closing `---` is a parse error, not a
silent misparse.

Usage:
    python3 tools/check_example_sync.py
    python3 tools/check_example_sync.py path/to/a.yaml path/to/b.yaml
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import difflib
from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PATH_A = REPO_ROOT / "hayward" / "aqualogic" / "example-device.yaml"
DEFAULT_PATH_B = REPO_ROOT / "hayward" / "aqualogic" / "example-device-switches.yaml"

TOP_LEVEL_SHARED_KEYS = ["substitutions", "esphome", "esp32", "logger"]

# A decorative divider line: "#", optional space, 5+ dashes, nothing else -- not a header.
_DIVIDER_RE = re.compile(r"^[ \t]*#[ \t]*-{5,}[ \t]*$")
# A real section header: "# --- Title [tag] --- optional trailing text".
_HEADER_RE = re.compile(r"^[ \t]*#[ \t]*---[ \t]*(?P<title>.+?)[ \t]*---(?P<rest>.*)$")
# Anything that *looks* like the start of a header, for detecting a malformed one.
_HEADER_START_RE = re.compile(r"^[ \t]*#[ \t]*---")
# A flavor tag at the end of a header title, e.g. "Buttons: switch-like [buttons]".
_TAG_RE = re.compile(r"\[(?P<tag>[^\[\]]+)\][ \t]*$")
# A top-level (column-0) YAML key.
_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):")


class SyncCheckError(Exception):
    """A structural parse problem -- distinct from a sync mismatch."""


@dataclass
class Section:
    title: str
    tag: str | None
    text: str  # full block text, header line included, up to (not including) the next header


def parse_sections(text: str, label: str) -> list[Section]:
    """Split `text` into sections at each section-header line.

    Raises SyncCheckError on a malformed header (starts like one, doesn't close). Content before
    the first header, and decorative divider lines, are folded into whichever section they fall
    inside (or dropped if before the first header).
    """
    sections: list[Section] = []
    current_title: str | None = None
    current_tag: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_title is not None:
            sections.append(Section(current_title, current_tag, "".join(current_lines)))

    for lineno, line in enumerate(text.splitlines(keepends=True), start=1):
        if _DIVIDER_RE.match(line):
            current_lines.append(line)
            continue

        m = _HEADER_RE.match(line)
        if m:
            flush()
            title = m.group("title")
            tag_m = _TAG_RE.search(title)
            current_title = title
            current_tag = tag_m.group("tag") if tag_m else None
            current_lines = [line]
            continue

        if _HEADER_START_RE.match(line):
            raise SyncCheckError(
                f"{label}:{lineno}: malformed section header (starts with '# ---' but has no "
                f"matching closing '---'): {line!r}"
            )

        current_lines.append(line)

    flush()
    return sections


def parse_top_level_blocks(text: str) -> dict[str, str]:
    """Map each top-level YAML key to its full block text (key line through the line before the
    next top-level key, or EOF)."""
    blocks: dict[str, list[str]] = {}
    current_key: str | None = None
    for line in text.splitlines(keepends=True):
        m = _TOP_LEVEL_KEY_RE.match(line)
        if m:
            current_key = m.group(1)
            blocks.setdefault(current_key, [])
        if current_key is not None:
            blocks[current_key].append(line)
    return {key: "".join(lines) for key, lines in blocks.items()}


def _diff(text_a: str, text_b: str, label_a: str, label_b: str) -> str:
    return "".join(
        difflib.unified_diff(
            text_a.splitlines(keepends=True),
            text_b.splitlines(keepends=True),
            fromfile=label_a,
            tofile=label_b,
        )
    )


def check_sync(path_a: Path, path_b: Path) -> list[str]:
    """Return a list of human-readable mismatch descriptions; empty means in sync."""
    text_a = path_a.read_text()
    text_b = path_b.read_text()
    name_a, name_b = path_a.name, path_b.name

    errors: list[str] = []

    blocks_a = parse_top_level_blocks(text_a)
    blocks_b = parse_top_level_blocks(text_b)
    for key in TOP_LEVEL_SHARED_KEYS:
        block_a = blocks_a.get(key)
        block_b = blocks_b.get(key)
        if block_a is None:
            errors.append(f"top-level key '{key}:' missing from {name_a}")
            continue
        if block_b is None:
            errors.append(f"top-level key '{key}:' missing from {name_b}")
            continue
        if block_a != block_b:
            errors.append(
                f"top-level key '{key}:' differs between {name_a} and {name_b}:\n"
                + _diff(block_a, block_b, name_a, name_b)
            )

    sections_a = parse_sections(text_a, name_a)
    sections_b = parse_sections(text_b, name_b)
    untagged_a = {s.title: s for s in sections_a if s.tag is None}
    untagged_b = {s.title: s for s in sections_b if s.tag is None}

    for title, sec_a in untagged_a.items():
        sec_b = untagged_b.get(title)
        if sec_b is None:
            errors.append(f"untagged section '{title}' present in {name_a} but missing from {name_b}")
            continue
        if sec_a.text != sec_b.text:
            errors.append(
                f"untagged section '{title}' differs between {name_a} and {name_b}:\n"
                + _diff(sec_a.text, sec_b.text, name_a, name_b)
            )
    for title in untagged_b:
        if title not in untagged_a:
            errors.append(f"untagged section '{title}' present in {name_b} but missing from {name_a}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path_a", nargs="?", type=Path, default=DEFAULT_PATH_A)
    parser.add_argument("path_b", nargs="?", type=Path, default=DEFAULT_PATH_B)
    args = parser.parse_args()

    try:
        errors = check_sync(args.path_a, args.path_b)
    except SyncCheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if errors:
        print(f"{args.path_a.name} / {args.path_b.name} are out of sync:\n", file=sys.stderr)
        for err in errors:
            print(err, file=sys.stderr)
            print(file=sys.stderr)
        return 1

    print(f"{args.path_a.name} / {args.path_b.name} are in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
