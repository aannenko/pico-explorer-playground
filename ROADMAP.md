# Roadmap

Non-binding goals and current feature state for `pico-explorer-playground`.
These are design intent, not requirements — they guide decisions when a task
leaves them ambiguous.

## Implemented

- **Multi-screen UI** — hardware buttons (X/Y) cycle between independent
  views via `ButtonPoller` (polled in main loop). Three views today:
  Sensors, Countdown, Calendar. Each view has `initialize()` /
  `deinitialize()` lifecycle methods; `DisplayManager` manages the active
  view index, switching, and forwards A/B button presses to the active
  display. Views that handle buttons implement `on_button_a()` /
  `on_button_b()`.

- **Countdown timer** — `CountdownTimer` service is a pure timer engine
  with `on_done` / `on_configure` callbacks. `configure(name, total_sec)`
  sets / resets presets; `start()` / `pause()` / `resume()` / `reset()` for
  state transitions. The display owns duration presets
  (`DURATIONS` / `LABELS`) and cycling logic and bootstraps the timer via
  `configure()` in its constructor. `ExplorerBuzzer.play_alert` is wired
  as `on_done`; `stop_alert` as `on_configure`. The countdown keeps
  ticking (and buzzer fires) even when the user switches to another
  display. `countdown.Display` is a rendering-only view. Ring rendering
  lives in `displays/ring.py` as a reusable module.

- **Calendar view** — horizontal timeline where time progresses
  left-to-right. 2-hour sliding window (30 min past + 90 min future) with
  a "now" marker at 25 % from the left. Up to 5 event streams rendered as
  horizontal bar rows with two alternating colors per stream. Labels use
  binary-search truncation to fit narrow bars (`bitmap6` x2 scale, 2 px
  margins). Right-aligned remaining-time labels (format `-HH:mm`) shown
  when an event's end extends beyond the visible window. 15-minute tick
  marks on the baseline, hour labels below. Static overlay (now-line
  segments, baseline) drawn once on init; rows and time axis redrawn each
  minute. `@micropython.native` on hot draw methods. The "now" line is
  drawn as short segments in the gaps between rows. Each stream is backed
  by an `EventWindow` (`scheduling/event_window.py`), constructed from a
  `Stream` (RGB tuples) by mapping RGB → pen via `gfx.create_pen`.
  Currently wired with one `work_week_loop` stream plus 4 demo streams
  from `demo_streams.py`. No A/B button interaction; purely
  auto-scrolling.

## Partially implemented

- **Sensor dashboard** — shows BME690 readings (temperature, pressure,
  humidity, gas resistance, heater status) and a header with local time
  (via `TimeService.now`). History graphs are planned but not yet
  implemented.

## Planned

- **Web configuration** — a tiny web server to define one-shot and
  repeated (daily / weekly / …) timers. One-shot timers map to a single
  event; repeated timers map to multiple events repeating in a circle
  (similar to the current ring timer behavior). Will replace
  `demo_streams.py` as the source of stream definitions (up to 5).

## Design implications

- Keep views modular (separate rendering + state per view); do not
  hard-code assumptions that there is only one screen.
- Due to the 240×240 display constraint, only the Sensors and Calendar
  views share a common header (time / date); other views may use the full
  screen.
- Header typography (Sensors / Calendar): `bitmap6` at x3 scale, single
  line, plus 6 px bottom margin.
- Prefer clean boundaries between data acquisition (sensors / network),
  scheduling, and rendering.
- Be mindful of MicroPython constraints: small memory footprint and
  minimal allocations in tight refresh / update loops.
