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
  gas resistance) with a local-time header. Each row pairs the current value
  with a 24-hour history graph coloured by per-metric bands from
  `config.SENSOR_*_BANDS`. The gas row hides its graph while the heater warms
  up. No persistence across reboots.

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

- **Electricity tariff windows** (deferred) — static weekly tariff
  schedule (peak / mid / low).  Structurally distinct from waste
  (dense partition vs. sparse events) so likely a separate
  `TARIFF_SCHEDULE` shape.  Possible future variant: day-ahead spot
  prices from ENTSO-E / OTE.

## Design implications

- Keep views modular (separate rendering + state per view); do not assume
  there is only one screen.
- On the 240×240 display, only the Sensors and Calendar views share a
  common header (time / date); other views may use the full screen.
- Prefer clean boundaries between data acquisition (sensors / network),
  scheduling, and rendering.
- Be mindful of MicroPython constraints: small memory footprint and
  minimal allocations in tight refresh / update loops.
