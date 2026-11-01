# Plan: integer UI scaling

**Status:** planned, not started (2026-10-10). The inventory below reflects
the code on that date; re-check it before implementing.

## Goal

Drive a larger panel (the planned e-ink screen) by changing one integer,
with bitmap8 text and pixel-art icons staying crisp, and no layout element
able to overflow its space silently.

## Why an integer

bitmap8 glyphs and the P4 icons render cleanly only at whole-number scales
(each source pixel becomes an N×N block), and `icons_p4.draw_icon` takes an
int scale. So the system is one integer `S`, with today's Explorer layout
defined as `S = 1`.

## What already scales

- **Measured text.** Width is exactly `scale × (Σ glyph widths + n − 1)`
  (device-verified, 90/90 cases at scales 1, 2, 3, 4 and 6), so everything derived
  from `measure_text` follows the text scale: the Sensors graph position,
  Calendar label fitting, and both header guards.
- **Space fillers.** Sensors graph width and `ticks_per_commit`, Calendar
  row heights and bar positions, ring thickness (`min(W, H) // 30`), and
  centred Ring / Status text.
- **Text-derived heights.** Text height, and the Sensors row pitch
  (text height × 1.5).

## What does not: hand-written pixel values

Values are at `S = 1`. All of these would be multiplied by `S` unless noted.

| Where | Value | Role |
|---|---|---|
| `app.py` | `TEXT_SCALE` 3 (config) | primary text: Status, Ring, Calendar header, Sensors values + unit glyphs |
| `app.py` | `bar_text_scale` 2 | Calendar bar labels and time axis |
| `sensors.py` | `_ICON_SCALE` 2 | band icons; replaced by the cell budget (design §2) |
| `sensors.py` | `_L_GAP` 3, `_R_MARGIN` 0 | value→graph gap, graph→edge |
| `sensors.py` | inline `+ 4`, `+ 6` | icon→unit and unit→value gaps |
| `sensors.py` | inline `+ 2` | icon lift: bitmap8 ink sits high in its cell |
| `calendar.py` | `_HEADER_MARGIN` 6, `_AXIS_MARGIN` 3 | header→rows, rows→axis |
| `calendar.py` | `_BAR_TEXT_MARGIN` 2, `_MIN_LABEL_PX` 14 | label inset, minimum bar width for a label |
| `calendar.py` | `_TICK_MARK_HEIGHT` 4, `_STATUS_GLYPH_PX` 4 | axis ticks, stale-data square |
| `calendar.py` | `max(3, …)` | minimum row gap |
| `calendar.py` | inline `+ 2` in bar `text_y` | label lift: the same bitmap8 ink offset |
| `ring.py` | `_RING_OUTER_MARGIN` 2 | ring→edge |
| `status.py` | `h // 2 + 5` | subtext offset |

**1-px elements, which need a policy rather than a multiply (open question 2):**

- Calendar bar seams (`x0 - 1`, `x1 - 1`), the `label_right + 1` separation,
  the baseline, and quarter-hour tick lines (`gfx.line`, always 1 px).
- Sensors graph columns (1 px wide, one history sample each) and the value
  marker (`gfx.pixel`).
- Ring polygon overdraw (`outer_poly_r + 2`, `inner_poly_r - 1`). This
  compensates for integer rasterization, not layout, and probably stays fixed.

## Design

### 1. One integer scale

- `S` comes from a config key `UI_SCALE` (int ≥ 1, default 1); see open
  question 1.
- Each view keeps its constants as `S = 1` base values and multiplies them
  once, in its `Geometry`, at boot. That has no hot-path cost, and `S = 1`
  stays pixel-identical to today.
- Text scales are derived at the composition root (`app.py`), as values
  shared by several views: primary text `3 × S`, Calendar bars `2 × S`.
- `TEXT_SCALE` retires as a config key. A leftover override then only warns
  as unknown; the current `config.py` has none.

### 2. The layout owns the icon cell

Today the Sensors left column is as wide as the widest icon in
`Display.ROWS` (`left_column_native_px()`), with no upper bound. One
oversized blob therefore reflows every row, and nothing checks vertical fit
at all. The rows are 36 px apart, so at scale 2 an 18 px icon touches the
next row and a 20 px one overlaps it. Today the only guard is
`test_sensors_display.py`, which pins every icon at exactly 16×16 and every
unit glyph at 8×8.

Two contracts, each enforced where it belongs:

- **Layout contract, checked at boot.** A square cell `_ICON_CELL = 32 × S`,
  with `icon_scale = cell // native`. Raise if the scale comes out as 0 (art
  too large for its cell), and raise if the cell is taller than the row
  pitch. Unit glyphs keep the text scale, since they sit inline with the
  text, and get the same row-pitch check.
- **Art contract, checked by a test.** Every icon in a column shares one
  square native size, and so do the unit glyphs. Mixed sizes would get
  different scales and so render at different visual sizes. Generalise the
  existing `== (16, 16)` / `== (8, 8)` assertions to "all equal".

Effect: 16 px art draws at scale 2 when `S = 1` and at 4 when `S = 2`.
32 px art for a larger panel draws at scale 2: sharper, with the same
footprint and no code change. `left_column_native_px()` stays, as the
`native` input.

### 3. Every view asserts its fit at boot

Each view raises a `RuntimeError` naming itself, like today's header and
graph guards. There are no silent clips. Missing today:

- **Sensors:** the header plus all rows fit the panel height. The last row
  currently ends near y = 170.
- **Calendar:** the derived bar height is ≥ 1.
- **Ring:** the text lines fit inside the inner circle. Today a panel that
  is too small fails with a cryptic `math domain error` from `sqrt`.
- **Sensors icon cell:** the cell fits the row pitch (§2).

### 4. Leftover space

Panels are rarely an exact multiple of 240×240 (800×480 at `S = 2` leaves a
320 px strip, for example). Width already flows into the space fillers
(Sensors graph, Calendar bars); Ring and Status centre. Whether to centre
the Sensors block vertically or keep it top-aligned is open question 3.

## Open questions (settle in the plan review)

1. **Source of `S`.** An explicit `UI_SCALE` key (lean: predictable, and the
   boot guards validate it), auto-derived as
   `max(1, min(W // 240, H // 240))`, or both (`UI_SCALE = 0` meaning auto).
2. **1-px elements.** Do seams, ticks, the baseline and the label separation
   scale to `S` px, or stay hairlines? For the Sensors graph, 1-px columns
   give `S×` more history resolution (and `S×` the `RingHistory` capacity),
   while `S`-px columns keep today's resolution and visual weight.
3. **Leftover space.** Top-align or centre Sensors? Does the Calendar
   window stay at 2 h on a wider panel? Widening it cascades into the
   network forecast horizons, which `app.py` derives from the calendar
   windows.
4. **Art for larger panels.** Upscale the 16 px set, or ship a native
   higher-resolution set? Today's 20 icons pack to 2,176 bytes, so a 32 px
   set costs about 4× that in flash.
5. **The duplicated bitmap8 ink offset.** The `+ 2` appears in both
   `sensors.py` and `calendar.py`. Lean: one shared constant, since it's a
   font property.

## Steps (one commit each)

0. **Plan review.** This is a cross-cutting refactor, so: plan-stage review
   panel before any code, then an implementation review and design duck.
1. **Snapshot tests.** Pin the draw-call log of each view's first frame at
   today's config, with fixed time and inputs. This is the pixel-identity
   safety net for everything after it. `FakePicoGraphics` records `clear`,
   `rectangle`, `text` and `pixel`, but not `line` (Calendar ticks and
   baseline) or `circle` / `polygon` (Ring), so extend it first.
2. **Thread `S` through.** Add `UI_SCALE`, pass `ui_scale` into each
   `Geometry`, and multiply its constants: one commit per view. The
   snapshots must not change at `S = 1`.
3. **Derive text scales from `S`** and retire `TEXT_SCALE`.
4. **Sensors icon cell** (§2): cell budget, art-uniformity test, and the
   cell ≤ row-pitch guard.
5. **Vertical fit guards** (§3).
6. **1-px policy**, once decided.

## Verification

- **`S = 1`:** snapshots unchanged. On the device, the Sensors geometry
  must be unchanged too (add `ui_scale=1` once it exists):

  ```python
  from picographics import PicoGraphics, DISPLAY_PICO_EXPLORER
  from displays.sensors import Geometry
  gfx = PicoGraphics(display=DISPLAY_PICO_EXPLORER)
  g = Geometry(pico_graphics=gfx, font="bitmap8", font_height=8,
               text_scale=3, tick_period_ms=500)
  print((g.icon_size_px, g.unit_size_px, g.icon_y_offset, g.unit_x,
         g.value_x, g.graph_x, g.graph_width, g.ticks_per_commit))
  # expect (32, 24, 6, 36, 66, 132, 108, 1600)
  ```
- **`S = 2`:** on a 480×480 fake, every fixed layout value exactly doubles.
  `_fakes.bitmap8_width` is exact at any scale, so text-derived values are
  exact too. Any exception (floor-division rounding, 1-px elements, ring
  rasterization) gets listed and justified in the test.
- **Each new guard:** one test where it raises, and one where it passes at
  the shipped config.

## Out of scope, but these gate the choice of panel

- **Framebuffer memory.** A `PEN_P4` framebuffer is `W × H / 2` bytes,
  against a measured heap of about 192 KB (196,800 B). Today, 240×240 needs
  28.8 KB. 480×480 would need 115 KB, and 800×480 would need 192 KB,
  nearly the entire heap. On the RP2040 a larger panel is only viable at a lower bit
  depth (typical for e-ink) or on a board with more RAM.
- **E-ink refresh.** A full refresh takes seconds and flashes the panel. The
  1 s Sensors cadence and the continuous Calendar scroll need a slower,
  change-driven update strategy (`refresh_period_ms`, `RefreshGate`), not
  just new geometry.
- **Colour language.** The 16-colour palette, the `LABEL_FOR_SLOT` contrast
  table and the CVD verification all assume a colour panel. A mono or
  three-colour panel needs its own palette.
- **Hardware module.** The display constant (`DISPLAY_PICO_EXPLORER`) and the
  pins in `hardware/explorer.py` are Explorer-specific.

**After the work outlined in this plan is completed, the plan should be removed.**