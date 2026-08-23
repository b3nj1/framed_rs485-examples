# switch.yaml / switch_secondary.yaml config-validation harness

Not a user-facing example. `common.yaml` pulls in `bus.yaml`, `heater.yaml` (whose own fused
"Heater Mode" switch is exercised for free), and one `switch.yaml` / `switch_secondary.yaml`
include each (a plain LED-mask-bit toggle, and the secondary wired-local wire format), so a
schema regression in any of the three surfaces here.

`test.<platform>.yaml` supplies the platform block (`esp32`/`esp8266`/`rp2040`), `uart:` pins, and
`external_components:` per target. Run via `tools/validate_switch_standalone.py` from the repo root
(see that script's docstring) — it patches `external_components:` to a local `esphome` checkout the
same way `tools/validate_examples.py` does for the entry-point configs, and runs `esphome config`
against all four.
