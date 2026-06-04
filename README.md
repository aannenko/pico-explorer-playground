# pico-explorer-playground

Test ideas with a [Raspberry Pi Pico](https://www.raspberrypi.com/products/raspberry-pi-pico/)
(RP2040) and the [Pimoroni Pico Explorer Base](https://shop.pimoroni.com/products/pico-explorer-base).

The on-device code is a MicroPython app that cycles between three
views (sensors, countdown timer, horizontal calendar timeline) driven
by the Explorer's X/Y buttons, with A/B forwarded to the active view.

## Layout

- `src/pico/` — the MicroPython app, uploaded verbatim to the Pico.
  - `main.py` — thin entry point.
  - `app.py` — composition: wires services + displays.
  - `displays/`, `services/`, `scheduling/`, `utilities/`, `hardware/`
    — feature modules.
  - `config_defaults.py` — committed schema and defaults; copy to
    `config.py` and override the keys you care about.  `config.py` is
    gitignored.
- `src/tests/` — host-side pytest suite; runs under CPython with
  MicroPython stubs from `src/tests/conftest.py`.

## Setup

1. Install a recent Pimoroni MicroPython build on the Pico
   (see [pimoroni-pico releases](https://github.com/pimoroni/pimoroni-pico/releases)).
2. `cp src/pico/config_defaults.py src/pico/config.py` and edit
   `WIFI_SSID` / `WIFI_PASSWORD`.
3. Open `src/solution.code-workspace` in VS Code with the
   [MicroPico](https://marketplace.visualstudio.com/items?itemName=paulober.pico-w-go)
   extension installed.  Right-click the workspace root and choose
   **Upload project to Pico** — the `"micropico.syncFolder": "pico"`
   setting restricts the upload to `src/pico/`.

## Tests

```sh
cd src
python -m pytest -q
```

No MicroPython runtime is required on the host; `src/tests/conftest.py`
provides shims for `machine`, `picographics`, `pimoroni`, etc.
