"""Validate the switch.yaml / switch_secondary.yaml standalone test harness through a real
`esphome config` run, across the four target platforms in
hayward/aqualogic/tests/switch/test.*.yaml.

These packages aren't wired into any example-device*.yaml yet (that's separate follow-up work), so
tools/validate_examples.py's entry-point sweep doesn't exercise them. This script is the analogous
check for that standalone harness: same local-patching approach as validate_examples.py
(external_components: pointed at a local esphome checkout instead of a released tag), but against
hayward/aqualogic/tests/switch/test.*.yaml instead of the example-device*.yaml entry points.

Usage:
    python3 tools/validate_switch_standalone.py --esphome-path /path/to/esphome/checkout
"""

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS_DIR = REPO_ROOT / "hayward" / "aqualogic" / "tests" / "switch"
# The harness's test.*.yaml files !include ../../{switch,switch_secondary,bus}.yaml (relative to
# hayward/aqualogic/tests/switch/), so each per-platform run needs the whole family directory
# alongside it, not just the harness subdirectory in isolation.
FAMILY_DIR = REPO_ROOT / "hayward" / "aqualogic"

EXTERNAL_COMPONENTS_RE = re.compile(
    r"- source: github://b3nj1/esphome@v[0-9][^\n]*\n(\s*)components: \[rs485_frame\]"
)


def patch_local_component(text: str, esphome_path: Path) -> str:
    def repl(m: re.Match) -> str:
        indent = m.group(1)
        return (
            "- source:\n"
            f"{indent}    type: local\n"
            f"{indent}    path: {esphome_path / 'esphome' / 'components'}\n"
            f"{indent}components: [rs485_frame]"
        )

    new_text, n = EXTERNAL_COMPONENTS_RE.subn(repl, text)
    if n == 0:
        raise RuntimeError("could not find external_components: block to patch")
    return new_text


def validate_one(test_file: Path, esphome_path: Path, workdir: Path) -> tuple[bool, str]:
    case_dir = workdir / test_file.stem / "hayward" / "aqualogic"
    shutil.copytree(FAMILY_DIR, case_dir)
    run_dir = case_dir / "tests" / "switch"
    patched = patch_local_component((run_dir / test_file.name).read_text(), esphome_path)
    (run_dir / test_file.name).write_text(patched)

    result = subprocess.run(
        ["esphome", "config", test_file.name],
        cwd=run_dir,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stdout + result.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--esphome-path",
        type=Path,
        required=True,
        help="Local esphome checkout to validate external_components against.",
    )
    args = parser.parse_args()

    if shutil.which("esphome") is None:
        print("error: `esphome` not found on PATH -- pip install esphome first.", file=sys.stderr)
        return 2

    test_files = sorted(HARNESS_DIR.glob("test.*.yaml"))
    if not test_files:
        print(f"error: no test.*.yaml files found under {HARNESS_DIR}", file=sys.stderr)
        return 2

    failures = []
    with tempfile.TemporaryDirectory(prefix="rs485_frame_validate_switch_") as tmp:
        workdir = Path(tmp)
        for test_file in test_files:
            ok, output = validate_one(test_file, args.esphome_path, workdir)
            status = "OK" if ok else "FAIL"
            print(f"[{status}] {test_file.name}")
            if not ok:
                failures.append(test_file.name)
                print(output)

    if failures:
        print(f"\n{len(failures)} platform(s) failed validation:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"\nAll {len(test_files)} platform configs validated OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
