# Copilot instructions (pico-explorer-playground)

## Project summary
This is a MicroPython app for the Pimoroni Pico Explorer (RP2040) using PicoGraphics.
Main behavior: show a ring-style timer UI and cycle through scheduled events.

## Hardware / runtime constraints
- Target runtime: MicroPython on RP2040.
- Display API: PicoGraphics (Pimoroni), using `PicoGraphics(display=DISPLAY_PICO_EXPLORER)`.
- Performance/memory: avoid unnecessary allocations in hot paths (especially timer callbacks).
- Interrupt/timer callbacks: keep callbacks tiny; prefer `micropython.schedule(...)` to run logic outside IRQ context.
- Prefer `const(...)` for constants; keep math integer where possible.

## Code structure (entry points and key modules)
- Entry point: `pico/main.py`
  - Initializes PicoGraphics + timer display
  - Connects WiFi, syncs NTP time, schedules periodic resync
  - Starts the event loop via `eventfactory.work_week_loop(...)`
- Timer UI: `pico/displays/timer.py`
  - `Geometry`: precomputes ring/text geometry, vertex arrays
  - `Renderer`: draws ring + text with minimal redraw
  - `Display`: schedules per-second text updates and ring segment updates, chains events
- Scheduling: `pico/scheduling/*`
  - Event model + factories for iterators of events
- Utilities: `pico/utilities/*`
  - WiFi connect and NTP time sync helpers

## Testing expectations
- Host-side tests exist under `tests/` (pytest).
- Keep logic testable via dependency injection (e.g., `get_time`, `schedule`, `timer_factory` patterns already used).
- Don’t add heavy new dependencies unless necessary.

## Coding conventions for changes
- Make minimal, targeted edits; keep the public behavior stable unless explicitly requested.
- Keep MicroPython compatibility (avoid CPython-only modules unless guarded).
- Prefer small functions and clear names over cleverness.
- If changing rendering/timing, ensure ring/text updates remain incremental and efficient.

## Config / secrets
- WiFi credentials/timezone are provided via a local `config.py`.
- Do not commit real credentials; use a sample file if needed.

## Planned direction (non-binding)
These are goals/intent to guide design choices. They are not requirements unless explicitly requested in a task.

- Multi-screen UI: use hardware buttons around the Pico Explorer display to switch between multiple independent screens/views (like virtual desktops). Views may have entirely different layouts and data sources.
- Sensor dashboard view: show readings from a small in-house weather station, including Pimoroni BME690 metrics (temperature, pressure, humidity, CO₂). Display a small history graph near each value. Show current time/date at the top.
- Calendar view: an Outlook-like calendar in horizontal mode where time progresses left-to-right. Show current time/date at the top.
- Web configuration: add a tiny web server to define one-shot and repeated (daily/weekly/…) timers. One-shot timers map to a single event; repeated timers map to multiple events repeating in a circle (similar to the current ring timer behavior).

Design implications:
- Keep views modular (separate rendering + state per view) and avoid hard-coding assumptions that there is only one screen.
- Due to the 240×240 display constraint, only the Sensors and Calendar views should share a common header (time/date); other views may use the full screen.
- Header typography (Sensors/Calendar): use `bitmap6` at x3 scale, single line, plus ~3px bottom margin.
- Prefer clean boundaries between data acquisition (sensors/network), scheduling, and rendering.
- Be mindful of MicroPython constraints: small memory footprint and minimal allocations in tight refresh/update loops.