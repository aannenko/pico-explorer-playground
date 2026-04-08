# Copilot instructions (pico-explorer-playground)

## Project summary
This is a MicroPython app for the Pimoroni Pico Explorer (RP2040) using PicoGraphics.
Main behavior: show a ring-style timer UI, cycle through scheduled events, and provide a configurable countdown timer with buzzer notification.

## Hardware / runtime constraints
- Target runtime: MicroPython 1.27.0 on RP2040 (Pimoroni build from https://github.com/pimoroni/pimoroni-pico).
- Display API: PicoGraphics (Pimoroni), using `PicoGraphics(display=DISPLAY_PICO_EXPLORER)`.
- Performance/memory: avoid unnecessary allocations in hot paths (especially timer callbacks).
- Interrupt/timer callbacks: keep callbacks tiny; prefer `micropython.schedule(...)` to run logic outside IRQ context.
- Prefer `const(...)` for constants; keep math integer where possible.

## Code structure (entry points and key modules)
- `pico/` is deployed directly to the Pico board (copied as-is via MicroPico).
- `tests/` runs locally on the host machine using a standard CPython interpreter and pytest.
- Entry point: `pico/main.py`
  - Initializes PicoGraphics, creates display views and wires them together
  - Delegates WiFi/NTP to `NetworkService`, view switching to `DisplayManager`
  - Creates a `TickScheduler` (single 100ms PERIODIC timer) and registers all service/display `tick()` methods as subscribers
  - Uses `ExplorerButtons` in the main loop to poll hardware buttons with edge detection and dispatch via `micropython.schedule()`
  - Buttons X/Y cycle views via `DisplayManager.cycle()`; buttons A/B forwarded to the active view via `DisplayManager` button handlers
- Display views: `pico/displays/`
  - `status.py` — `StatusDisplay`: simple centered text screen (e.g. "wifi", "sync time")
  - `events.py` — `Geometry`, `Renderer`, `Display`: ring-style event UI. `Display` polls `EventService` for current event state, calculates ring progress from elapsed time, detects event changes by identity. Has a `tick()` method (1s self-gated via `ticks_diff`) registered with the TickScheduler. Reuses `Geometry`/`Renderer`/`Colors` (shared with countdown display).
  - `countdown.py` — `Display`: rendering-only countdown display that reads state from `CountdownTimer`. Has a `tick()` method (1s self-gated) for periodic UI updates, plus calculation-driven ring segment clearing. Owns duration presets (`DURATIONS`/`LABELS`) and cycling logic. Bootstraps the timer with a default preset via `configure()`. `initialize()`/`deinitialize()` control rendering lifecycle without affecting the countdown engine. Reuses `events.Geometry`/`Renderer`/`Colors`.
  - `sensors.py` — `Geometry`, `Renderer`, `Display`: BME690 sensor dashboard. Has a `tick()` method (1s self-gated) for periodic UI updates.
  - `manager.py` — `DisplayManager`: manages active view index, initialize/deinitialize cycling, button A/B forwarding to the active display, and automatic register/unregister of the active display's `tick()` with the TickScheduler. All displays use no-arg `initialize()`.
- Scheduling: `pico/scheduling/*`
  - Event model + factories for iterators of events
- Services: `pico/services/` — long-lived stateful objects created at startup, independent of display lifecycle. Explorer/Pimoroni-specific services use naming convention (`Explorer*`, `Pimoroni*`) instead of folder convention.
  - `countdown_timer.py` — `CountdownTimer`: pure countdown engine (state machine: INITIAL/RUNNING/PAUSED/DONE). Accepts `on_done`/`on_configure` callbacks. Exposes `configure(name, total_sec)`, `start()`, `pause()`, `resume()`, `reset()`. Properties: `state`, `name`, `total_sec`, `elapsed_sec`, `remaining_sec`. Has a `tick()` method that checks if `time >= end_timestamp` and transitions to DONE. No timers, no buzzer, no UI logic — lives forever; the display reads its state.
  - `event_service.py` — `EventService`: wraps a `work_week_loop` iterator, auto-advances between events. Exposes `current_event`, `name`, `elapsed_sec`, `remaining_sec`, `total_sec`. Has a `tick()` method that checks if the current event has expired or a pending future event has started. Created after NTP sync. Lives forever; the events display reads its state.
  - `network_service.py` — `NetworkService`: encapsulates WiFi + NTP orchestration. Blocking startup via `connect_and_sync_initial()` (throws on failure). Non-blocking background reconnect/resync via TickScheduler `_tick()` using phase-based polling (`_IDLE` → `_WIFI` → `_NTP` → `_IDLE`), exception-safe and silent.
  - `sensors/pimoroni_bme690.py` — `PimoroniBME690`: reads temperature, pressure, humidity, gas resistance from the BME690 sensor via Pimoroni I2C. Has a `tick()` method that re-reads the sensor when `sensor_read_delay_ms` elapses.
  - `utilities/explorer_buzzer.py` — `ExplorerBuzzer`: PWM-based buzzer driver for the Pico Explorer piezo on GP0. Public API: `play_alert(count, freq, interval_ms)` for toggle-based beep patterns and `stop_alert()` to cancel. Internal `_beep()`/`_off()` are private. Owns its own periodic timer for alert patterns (150ms precision requires dedicated timer). Note: pin must be bridged to the AUDIO header on Pico Explorer.
  - `utilities/explorer_buttons.py` — `ExplorerButtons`: polls `machine.Pin` instances (raw GPIO, active-low with pull-up) with edge detection in the main loop and dispatches presses via `micropython.schedule()`
- Utilities: `pico/utilities/`
  - `wifi.py` — WiFi connectivity module. Public API: `start_connect(ssid, password)` (non-blocking, uses own `machine.Timer`), `connect(ssid, password, timeout_ms)` (blocking, returns final state), `is_connected()` (checks WLAN hardware), `reset()`. Public `state` variable: `IDLE`/`CONNECTING`/`CONNECTED`/`FAILED`. `FAILED` is terminal (e.g. wrong password); transient failures trigger internal retry. Module-level state (singleton WLAN interface).
  - `ntp.py` — Blocking NTP time sync. Public API: `sync_time(attempts=1)` (returns `SYNCED` or `FAILED`). Each attempt blocks ~1-3s. Public `state` variable: `IDLE`/`SYNCED`/`FAILED`. Module-level state.
  - `tick_scheduler.py` — `TickScheduler`: single PERIODIC timer (100ms default) that drives all periodic work. Subscribers register/unregister callable `tick()` methods. Uses `micropython.schedule()` to run callbacks outside IRQ context. Only 1 alarm pool slot for ALL periodic work (except ExplorerBuzzer which keeps its own timer for audio precision, and wifi.py which uses a temporary timer during non-blocking connection attempts).

## Testing expectations
- Host-side tests exist under `tests/` (pytest).
- `tests/conftest.py` provides shims/stubs for MicroPython-only modules (`micropython`, `machine`, `picographics`, `pimoroni`, `pimoroni_i2c`, `breakout_bme69x`, `ntptime`, `network`) and the `const()` builtin so that `pico/` code can be imported under CPython. The `machine` stub includes `Timer`, `Pin`, and `PWM`; the `pimoroni` stub includes `Button`. Also stubs `time.ticks_ms`, `time.ticks_diff`, `time.ticks_add`, and `time.sleep_ms` for CPython compatibility. Explorer-specific code lives under `pico/services/` with naming convention (`Explorer*`, `Pimoroni*`) to avoid shadowing the built-in `pimoroni` module on MicroPython.
- Individual tests use fakes (e.g., `FakeRenderer`, `FakeBME69X`, `FakeScheduler`) to isolate logic from hardware.
- Keep logic testable via dependency injection (e.g., `get_time`, `pwm_factory`, `pin_factory` patterns already used).
- Services and displays expose `tick()` methods tested directly — no timer/schedule mocking needed.
- Don’t add heavy new dependencies unless necessary.

## Coding conventions for changes
- Make minimal, targeted edits; keep the public behavior stable unless explicitly requested.
- Keep MicroPython compatibility (avoid CPython-only modules unless guarded).
- Type hints: use where practical, but keep them honest. MicroPython lacks `typing` (`Callable`, `Optional`, etc.), so if a proper hint would require `object` as a stand-in for an unavailable type, simplify the hint instead (e.g. `list[tuple]` rather than `list[tuple[Button, object, bool]]` where `object` is a stand-in for `Callable[[int], None]`). Comments with the full intended signature are fine.
- Prefer small functions and clear names over cleverness.
- If changing rendering/timing, ensure ring/text updates remain incremental and efficient.

## Config / secrets
- WiFi credentials/timezone are provided via a local `config.py`.
- Do not commit real credentials; use a sample file if needed.

## Planned direction (non-binding)
These are goals/intent to guide design choices. They are not requirements unless explicitly requested in a task.

- Multi-screen UI (**implemented, evolving**): hardware buttons (X/Y) cycle between independent display views via `ExplorerButtons` (polled in main loop). Currently three views exist: Sensors, Events, and Countdown. Each view has `initialize()` / `deinitialize()` lifecycle methods; `DisplayManager` manages the active view index, switching, and forwarding A/B button presses to the active display. Views that handle buttons implement `on_button_a()` / `on_button_b()` methods.
- Countdown timer (**implemented**): `CountdownTimer` service is a pure timer engine with `on_done`/`on_configure` callbacks. Accepts `configure(name, total_sec)` to set/reset presets, `start()`/`pause()`/`resume()`/`reset()` for state transitions. The display owns duration presets (`DURATIONS`/`LABELS`) and cycling logic, and bootstraps the timer via `configure()` in its constructor. `ExplorerBuzzer.play_alert` is wired as `on_done`; `stop_alert` as `on_configure`. The countdown keeps ticking (and buzzer fires) even when the user switches to another display. `countdown.Display` is a rendering-only view that reads engine state on `initialize()` and renders accordingly.
- Sensor dashboard view (**partially implemented**): shows BME690 readings (temperature, pressure, humidity, gas resistance, heater status) and a header with local time. `PimoroniBME690` service runs independently, continuously reading sensor data. History graphs are planned but not yet implemented. Show current time/date at the top.
- Calendar view: an Outlook-like calendar in horizontal mode where time progresses left-to-right. Show current time/date at the top.
- Web configuration: add a tiny web server to define one-shot and repeated (daily/weekly/…) timers. One-shot timers map to a single event; repeated timers map to multiple events repeating in a circle (similar to the current ring timer behavior).

Design implications:
- Keep views modular (separate rendering + state per view) and avoid hard-coding assumptions that there is only one screen.
- Due to the 240×240 display constraint, only the Sensors and Calendar views should share a common header (time/date); other views may use the full screen.
- Header typography (Sensors/Calendar): use `bitmap6` at x3 scale, single line, plus ~3px bottom margin.
- Prefer clean boundaries between data acquisition (sensors/network), scheduling, and rendering.
- Be mindful of MicroPython constraints: small memory footprint and minimal allocations in tight refresh/update loops.

## Maintaining this file
This file (`copilot-instructions.md`) should be maintained by Copilot. When making changes to the codebase that affect architecture, conventions, module structure, or project direction, Copilot should propose updates to this file to keep it accurate and in sync with the actual state of the code. This includes:
- Adding or removing modules, entry points, or display views.
- Changes to coding conventions, testing patterns, or dependency injection approaches.
- New hardware integrations or sensor support.
- Progress on planned features (moving items from "planned" to documented reality).
- Updates to build/test tooling or project configuration.

Copilot should treat this file as a living document and update it proactively as part of completing tasks, rather than letting it drift out of date.