# Roadmap

Non-binding goals and current feature state for `pico-explorer-playground`.
These are design intent, not requirements — they guide decisions when a task
leaves them ambiguous.

## Implemented

- **Multi-screen UI** — hardware buttons (X/Y) cycle between independent
  views. Three views today: Sensors, Countdown, Calendar. Each has a
  lifecycle (`initialize` / `deinitialize`); A/B button presses are
  forwarded to the active view (Countdown is the only consumer today).

- **Countdown timer** — preset durations cycled via A/B. The buzzer fires
  on completion and is silenced by any preset change. The timer keeps
  ticking (and the buzzer keeps firing) while the user is on a different
  view.

- **Calendar view** — horizontal timeline where time progresses
  left-to-right. 2-hour sliding window (30 min past + 90 min future) with
  a "now" marker at 25 % from the left. Up to 5 event-stream rows rendered
  as horizontal bar rows with two alternating colors per stream. Labels
  truncate to fit narrow bars; right-aligned remaining-time labels
  (`-HH:mm`) appear when an event extends beyond the visible window.
  15-minute tick marks on the baseline, hour labels below. Auto-scrolling;
  no button interaction. Currently fed by one `work_week_loop` stream plus
  4 demo streams (slated for replacement — see _Planned_).

- **Sensor dashboard** — BME690 readings (temperature, pressure, humidity,
  gas resistance) with a header showing local time. Each row carries a
  **24-hour history graph** to the right of the value: 1-px columns
  spaced ~14 min apart, filled with a pastel band-color spanning the row
  height. A bright pixel inside each column marks the value's Y position
  when in-range; out-of-range columns show the band fill alone; NaN
  columns are skipped. Per-row cap range and band thresholds both come
  from `config.SENSOR_*_BANDS` (one 5-tuple per metric). The gas row's
  graph is hidden while the heater is warming; on the Warming→Stable
  transition the full row repaints from the captured history. Value text
  is auto-sized to leave room for the graph. No persistence across
  reboots.

## Partially implemented

_(none currently)_

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
- Header typography (Sensors / Calendar): `bitmap8` at x3 scale, single
  line, plus 6 px bottom margin.
- Prefer clean boundaries between data acquisition (sensors / network),
  scheduling, and rendering.
- Be mindful of MicroPython constraints: small memory footprint and
  minimal allocations in tight refresh / update loops.
