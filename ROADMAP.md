# Roadmap

Non-binding goals and current feature state for `pico-explorer-playground`.
These are design intent, not requirements — they guide decisions when a task
leaves them ambiguous.

## Implemented

- **Multi-screen UI** — hardware buttons (X/Y) cycle between independent
  views (Sensors, Countdown, Calendar). Each view owns its rendering and
  state with an `initialize` / `deinitialize` lifecycle; A/B presses are
  forwarded to the active view.

- **Countdown timer** — preset durations cycled via A/B. The buzzer fires
  on completion and is silenced by any preset change. The timer keeps
  ticking (and the buzzer keeps firing) while the user is on a different
  view.

- **Calendar view** — horizontal timeline (time flows left-to-right) with a
  2-hour sliding window (30 min past, 90 min future) and a "now" marker.
  Shows up to 5 event-stream rows as colored bars; per-event color encodes
  meaning (e.g. precipitation intensity, UV / air-quality severity) rather
  than mere row striping. Bar labels and right-aligned remaining-time markers
  adapt to bar width. Auto-scrolling, no button interaction.

- **Calendar streams** — built-in rows that work out of the box, each a
  long-lived data source the calendar reads passively:
  - **Work week** and **waste collection** — local generators driven by
    `config`.
  - **Weather** (precipitation + UV) and **air quality** (European AQI +
    pollen) — fetched from Open-Meteo; disabled until coordinates are set in
    `config.py`.
  Rows left over are filled by temporary demo streams until bus departures
  and web configuration land.

- **Sensor dashboard** — BME690 readings (temperature, pressure, humidity,
  gas resistance) in four colour quadrants around a date and time badge.
  Each quadrant shows the current value, a band icon picked by
  `config.SENSOR_*_BANDS`, the 24-hour range and an auto-scaled 24-hour
  history graph (gas on a log scale). The gas quadrant hides its graph while
  the heater warms up. No persistence across reboots.

## Partially implemented

- **Bus departures** (calendar stream) — Prague Integrated Transport
  realtime via Golemio: one configured stop plus an optional destination
  filter. Blocked on transport — the API is HTTPS-only and on-device TLS
  exhausts the RP2040 heap, so it needs a local HTTPS proxy (which can also
  hold the API token) or an offline GTFS-static fallback. A demo stream
  holds its row until then.

## Planned

- **Web configuration** — a tiny web server to define one-shot and
  repeated (daily / weekly / …) timers. One-shot timers map to a single
  event; repeated timers map to multiple events repeating in a circle
  (similar to the current ring timer behavior). Will replace
  `demo_streams.py` as the source of stream definitions (up to 5).

- **Integer UI scaling** — one integer scale factor so the same views can
  drive a larger panel (e.g. a planned e-ink screen) with crisp bitmap text
  and pixel-art icons, each view asserting its fit at boot. Plan, inventory
  and open questions in `src/docs/ui-scaling-plan.md`.

- **Log screen** (debugging aid) — a view listing the latest log entries in
  native-scale (scale-1) text, so recent errors can be read on the device
  without a serial console. A `LogService` keeps the last few entries in
  fixed memory, fed by `utilities.log.log_exception`. `micropython.RingIO` is
  the candidate store, but its `write()` drops bytes once full and reads
  consume them, so the service must evict the oldest line before writing and
  the view needs a non-draining copy. Capturing every `print()` would need
  `os.dupterm` with a write-only stream: dupterm also feeds the stream's
  contents back to the REPL as input.

- **Electricity tariff windows** (deferred) — static weekly tariff
  schedule (peak / mid / low).  Structurally distinct from waste
  (dense partition vs. sparse events) so likely a separate
  `TARIFF_SCHEDULE` shape.  Possible future variant: day-ahead spot
  prices from ENTSO-E / OTE.

## Design implications

- Keep views modular (separate rendering + state per view); do not assume
  there is only one screen.
- On the 240×240 display, only the Calendar view has a full-width time / date
  header; the Sensors view shows them in its central badge, and other views
  may use the full screen.
- Prefer clean boundaries between data acquisition (sensors / network),
  scheduling, and rendering.
- Be mindful of MicroPython constraints: small memory footprint and
  minimal allocations in tight refresh / update loops.
