"""Validate every entry-point example device config through a real `esphome config` run.

Bundled example-device*.yaml files are templates: GPIOXX/BOARDXX/VARIANTXX placeholders,
`!secret` wifi creds, and a `packages:` block pinned to a released rs485_frame-examples/esphome
tag. None of that is directly esphome-loadable, so nothing has ever mechanically checked that
these files are valid ESPHome config -- errors (bad YAML structure, schema violations, typos in
package paths) only ever surfaced when a user copied one and it failed to build. This script
closes that gap: for each entry-point config, it substitutes concrete placeholder values, points
`packages:`/`external_components:` at a local checkout instead of a released tag (so it tests the
change actually being made, not last release), enables every independent optional equipment
package, and runs `esphome config` against the result.

Requires the `esphome` package installed (e.g. `pip install esphome`, or `pip install -e` a local
esphome checkout) -- not a listed dependency of this repo, since only this script needs it.

Usage:
    python3 tools/validate_examples.py \\
        --esphome-path /path/to/esphome/checkout \\
        [--examples-ref <branch-or-sha>]

--esphome-path points `external_components:` at a local esphome checkout's `esphome/components`
directory (via `type: local`) instead of a released `github://b3nj1/esphome@vX.Y.Z` tag -- so this
validates a component change before it's tagged. Omit it to validate against the pinned released
tag instead (a real network fetch).

--examples-ref points the `packages:` block's `url:`/`ref:` at this repo's own working copy
(file://<repo root>) at the given ref (default: current HEAD commit) instead of its pinned
released tag -- so a package file change is validated before it's tagged too. Pass an explicit
tag to instead validate exactly what a user would pull today.
"""

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parent.parent

# Placeholder substitutions applied to every entry-point config. Values are arbitrary but valid
# for their type -- only schema/structure is under test here, not a real board.
PLACEHOLDER_SUBS = {
    "GPIOXX": ["GPIO16", "GPIO17", "GPIO18"],  # tx, rx, flow_control, filled in order
    "BOARDXX": "esp32-s3-devkitc-1",
    "VARIANTXX": "esp32s3",
}

# Entry-point configs to validate, and the exact commented-out lines (verbatim, minus the leading
# "# ") to uncomment for maximal coverage. These are the independent, non-conflicting optional
# equipment/diagnostic packages -- NOT the mutually-exclusive button/response_monitor variant
# snippets further down those same files, which are illustrative alternatives meant to be picked
# one at a time by a human, not all enabled together.
ENTRY_CONFIGS = {
    "hayward/aqualogic/example-device.yaml": [
        "- hayward/aqualogic/pump-vsp.yaml        # Variable-speed pump — Status: tested",
        "- hayward/aqualogic/heater.yaml          # Gas/heat-pump heater — Status: tested",
        "- hayward/aqualogic/diagnostics.yaml     # Diagnostic stats table + frame dump — Status: tested",
    ],
    "jandy/aqualink-rs/example-allbutton.yaml": [
        "- jandy/aqualink-rs/leds-display.yaml    # Panel LEDs + display — Status: UNTESTED",
        "- jandy/aqualink-rs/swg.yaml             # Salt chlorinator — Status: UNTESTED",
        "- jandy/aqualink-rs/epump.yaml           # Variable-speed ePump — Status: UNTESTED",
        "- jandy/aqualink-rs/heater.yaml          # Heater error — Status: UNTESTED",
    ],
    "jandy/aqualink-rs/example-passive.yaml": [
        "- jandy/aqualink-rs/leds-display.yaml    # Panel LEDs + display — Status: UNTESTED",
        "- jandy/aqualink-rs/swg.yaml             # Salt chlorinator — Status: UNTESTED",
        "- jandy/aqualink-rs/epump.yaml           # Variable-speed ePump — Status: UNTESTED",
        "- jandy/aqualink-rs/heater.yaml          # Heater error — Status: UNTESTED",
    ],
    "generic/discovery.yaml": [],
    "generic/sniffer.yaml": [],
    "generic/skeleton.yaml": [],
}

SECRETS_YAML = 'wifi_ssid: "test"\nwifi_password: "testtest"\n'

EXTERNAL_COMPONENTS_RE = re.compile(
    r"- source: github://b3nj1/esphome@v[0-9][^\n]*\n(\s*)components: \[rs485_frame\]"
)
PACKAGES_URL_RE = re.compile(
    r"url: https://github\.com/b3nj1/rs485_frame-examples\n(\s*)ref: v[0-9][^\n]*"
)


def patch_placeholders(text: str) -> str:
    gpio_values = iter(PLACEHOLDER_SUBS["GPIOXX"])
    text = re.sub("GPIOXX", lambda _: next(gpio_values), text)
    text = text.replace("BOARDXX", PLACEHOLDER_SUBS["BOARDXX"])
    text = text.replace("VARIANTXX", PLACEHOLDER_SUBS["VARIANTXX"])
    return text


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


def patch_local_packages(text: str, examples_ref: str) -> str:
    def repl(m: re.Match) -> str:
        indent = m.group(1)
        return f"url: file://{REPO_ROOT}\n{indent}ref: {examples_ref}"

    new_text, n = PACKAGES_URL_RE.subn(repl, text)
    if n == 0:
        # Standalone configs (generic/discovery.yaml, generic/sniffer.yaml, generic/skeleton.yaml)
        # have no packages: block at all -- nothing to patch.
        return text
    return new_text


def enable_optional_lines(text: str, lines_to_enable: list[str]) -> str:
    for line in lines_to_enable:
        commented = f"# {line}"
        if commented not in text:
            raise RuntimeError(f"expected commented line not found: {commented!r}")
        text = text.replace(commented, line, 1)
    return text


def validate_one(
    rel_path: str,
    lines_to_enable: list[str],
    esphome_path: Path | None,
    examples_ref: str,
    workdir: Path,
) -> tuple[bool, str]:
    src = REPO_ROOT / rel_path
    text = src.read_text()
    text = patch_placeholders(text)
    if esphome_path is not None:
        text = patch_local_component(text, esphome_path)
    text = patch_local_packages(text, examples_ref)
    text = enable_optional_lines(text, lines_to_enable)

    case_dir = workdir / rel_path.replace("/", "_")
    case_dir.mkdir(parents=True)
    (case_dir / "secrets.yaml").write_text(SECRETS_YAML)
    config_path = case_dir / "device.yaml"
    config_path.write_text(text)

    result = subprocess.run(
        ["esphome", "config", str(config_path)],
        cwd=case_dir,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stdout + result.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--esphome-path",
        type=Path,
        default=None,
        help="Local esphome checkout to validate external_components against (default: pinned released tag).",
    )
    parser.add_argument(
        "--examples-ref",
        default=None,
        help="git ref of this repo to validate packages: against (default: current HEAD commit).",
    )
    args = parser.parse_args()

    if shutil.which("esphome") is None:
        print("error: `esphome` not found on PATH -- pip install esphome first.", file=sys.stderr)
        return 2

    examples_ref = args.examples_ref
    if examples_ref is None:
        examples_ref = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    failures = []
    with tempfile.TemporaryDirectory(prefix="rs485_frame_validate_") as tmp:
        workdir = Path(tmp)
        for rel_path, lines_to_enable in ENTRY_CONFIGS.items():
            ok, output = validate_one(rel_path, lines_to_enable, args.esphome_path, examples_ref, workdir)
            status = "OK" if ok else "FAIL"
            print(f"[{status}] {rel_path}")
            if not ok:
                failures.append(rel_path)
                print(output)

    if failures:
        print(f"\n{len(failures)} config(s) failed validation:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"\nAll {len(ENTRY_CONFIGS)} entry-point configs validated OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
