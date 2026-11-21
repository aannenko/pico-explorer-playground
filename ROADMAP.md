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

- **Calendar view** — an agenda of every stream's events in start order, from
  those in progress to those starting within a week, under the time and date;
  redrawn as each minute starts, no button interaction. Each event is a field
  coloured by its type (waste gray, rain blue, UV pink, air quality sky,
  pollen green) beside its stream's glyph on a rail (a bin, a rain cloud, a
  sun, air or a flower); the glyph shows the warning's level, or the pickup's
  colour for waste. Its start time is on the left; events in
  progress come first, each with the time left and a progress bar under its
  field, today's later events say how soon they start, and a header names
  each later day. Every row is the same height, so events beyond the last
  row are just not shown. A stream that fails to list its events is left out
  of that minute's redraw, which still shows the other streams under a red
  date with a red "!" badge after it; the same mark shows while a network
  source's latest refresh has failed or WiFi is down when one is due.

- **Calendar streams** — built-in streams that work out of the box, each a
  long-lived data source the calendar reads passively:
  - **Waste collection** — local wall-clock pickups from `config`, computed on-device.
  - **Precipitation**, **UV**, **air quality** (European AQI) and **pollen**
    (a stream per species) — warning levels for the past day and the week
    ahead from Open-Meteo's forecast and air-quality APIs, fetched together
    every hour, adjacent hours of one warning joined at their highest level;
    each keeps only as many warnings as the calendar has rows. If either
    request fails, all of them keep their last warnings until a retry succeeds.
    Disabled until coordinates are set in `config.py`.

- **Sensor dashboard** — BME690 readings (temperature, pressure, humidity,
  gas resistance) in four colour quadrants around a date and time badge.
  Each quadrant shows the current value, a band icon picked by
  `config.SENSOR_*_BANDS`, the 24-hour range and an auto-scaled 24-hour
  history graph (gas on a log scale). The gas quadrant hides its graph while
  the heater warms up. No persistence across reboots.

## Partially implemented

- **Bus departures** (calendar stream) — Prague Integrated Transport
  realtime via Golemio: one configured stop plus an optional destination
  filter. The calendar has no bus stream yet. The goal is direct HTTPS from
  the Pico; an offline GTFS timetable remains a fallback for scheduled
  departures, not realtime updates.
  - **TLS memory:** Reproduce the allocation failure on official Pico W
    firmware, then submit the MicroPython feature request for reserving
    reusable TLS record buffers at startup. The local draft and reproduction
    instructions are in `src/docs/micropython-rfc-tls-buffer-reservation.md`.
    If the firmware gains support, verify repeated HTTPS connections with
    the display and weather streams running, not just the first connection.
  - **API token:** Verify Golemio's certificate and hostname before sending
    the token, and reject redirects without making a second request. The
    bundled `requests` disables certificate verification, forwards request
    headers on redirect and drops the socket timeout.
  - **Response size:** Parse departures in bounded pieces and keep only as
    many as the calendar can show. If the transport changes, bound status and
    header lines, close the socket on parse failures, and preserve chunked
    decoding and detection of truncated `Content-Length` bodies.

## Planned

- **Web configuration** — a tiny web server to define one-shot and
  repeated (daily / weekly / …) timers. One-shot timers map to a single
  event; repeated timers map to multiple events repeating in a circle
  (similar to the current ring timer behavior). Will add user-defined
  calendar streams, such as a work schedule.

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
