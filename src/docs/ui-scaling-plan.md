# Plan: integer UI scaling

**Status:** planned, not started (2026-10-10). The inventory below was
re-checked on 2026-11-13 against the code after the Sensors quadrants and
their optimisation, and against the Pimoroni v1.29.0-2 firmware; re-check
it before implementing.

## Goal

Drive a larger panel (the planned e-ink screen) by changing one integer,
with bitmap8 text and pixel-art icons staying crisp, and no layout element
able to overflow its space silently.

## Why an integer

bitmap8 glyphs and the P4 icons render cleanly only at whole-number scales
(each source pixel becomes an N×N block), and `icons_p4.draw_icon` takes an
int scale (its viper `_blit` raises `TypeError` on a float). So the system is
one integer `S`, with today's Explorer layout defined as `S = 1`.

## What already scales

- **Measured text.** Width is exactly `scale × (Σ glyph widths + n − 1)`
  (device-verified, 90/90 cases at scales 1, 2, 3, 4 and 6), so everything derived
  from `measure_text` follows the text scale: the Sensors value, range and
  badge cells and the badge radius, Calendar label fitting, and the Calendar
  header guard.
- **Space fillers.** Sensors quadrant spans, graph widths and heights, and
  `ticks_per_commit`, Calendar row heights and bar positions, ring thickness
  (`min(W, H) // _RING_THICKNESS_DIVISOR`, 30), and centred Ring / Status
  text. Graph height enters a 32-bit product in the viper
  `_Quadrant._replace_graph` (span × graph height < 2³¹; see its comment).
- **Text-derived heights.** Text height, and the Sensors stack offsets
  (margins are measured to ink: text height less its descender row).

## What does not: hand-written pixel values

Values are at `S = 1`. All of these would be multiplied by `S` unless noted.

| Where | Value | Role |
|---|---|---|
| `app.py` | `TEXT_SCALE` 3 (config) | primary text: Status, Ring, Calendar header, Sensors values and badge time |
| `app.py` | `_SECONDARY_TEXT_SCALE` 2 | Calendar bar labels and time axis; Sensors ranges, units, badge weekday and date |
| `sensors.py` | `_ICON_SCALE` 2 | band icons; replaced by the box budget (design §2) |
| `sensors.py` | `_GUTTER_PX` 3, `_MARGIN_PX` 4 | quadrant gutters; gaps between stacked elements and to the edges |
| `sensors.py` | `_UNIT_DROP_PX` 2 | unit drop: unit ink sits high in its cell |
| `sensors.py` | `_BADGE_LINE_GAP_PX` 4, `_BADGE_PADDING_PX` 2, `_BADGE_RING_PX` 2, `_BADGE_BORDER_PX` 2 | badge line gaps; black space inside the ring; the ring; black border outside it |
| `calendar.py` | `_HEADER_MARGIN_PX` 6, `_AXIS_MARGIN_PX` 3 | header→rows, rows→axis |
| `calendar.py` | `_BAR_TEXT_MARGIN_PX` 2, `_MIN_LABEL_PX` 14 | label inset, minimum bar width for a label |
| `calendar.py` | `_TICK_MARK_HEIGHT_PX` 4, `_STATUS_GLYPH_PX` 4 | axis ticks, stale-data square |
| `calendar.py` | `max(3, …)` | minimum row gap |
| `calendar.py` | inline `+ 2` in bar `text_y` | label lift: the same bitmap8 ink offset |
| `ring.py` | `_RING_OUTER_MARGIN_PX` 2 | ring→edge |
| `status.py` | `h // 2 + 5` | subtext offset |

**1-px elements, which need a policy rather than a multiply (open question 2):**

- Calendar bar seams (`_BAR_SEAM_PX` 1), the `label_right + 1` separation,
  and the now-line, baseline and quarter-hour ticks (`gfx.line`, always
  1 px).
- Sensors graph columns (1 px wide, one history sample each) and the 1-px
  graph line.
- Ring polygon overdraw (`outer_poly_r = outer_circle_r + 2`,
  `inner_poly_r = inner_circle_r - 1`). This compensates for integer
  rasterization, not layout, and probably stays fixed.

## Design

### 1. One integer scale

- `S` comes from a config key `UI_SCALE` (int ≥ 1, default 1); see open
  question 1.
- Each view keeps its constants as `S = 1` base values and multiplies them
  once, in its `Geometry`, at boot. That has no hot-path cost, and `S = 1`
  stays pixel-identical to today.
- Text scales are derived at the composition root (`app.py`), as values
  shared by several views: primary text `3 × S`, secondary text (Calendar
  bars, Sensors labels) `2 × S`.
- `TEXT_SCALE` retires as a config key. A leftover override then only warns
  as unknown; the current `config.py` has none.
- Every new name costs a qstr slot for good, and a full boot already fills
  about 1,180 of the 1,260 slots that fit before the next pool, which needs a
  7.7 KB block a booted heap doesn't have (see the Qstr pool note in
  `.github/copilot-instructions.md`).

### 2. The layout owns the icon box

The Sensors band icons draw at the fixed `_ICON_SCALE` 2 from 16 px art
(`_ICON_ART_PX`), so a larger blob would overflow its box rather than shrink
to fit. `_check_layout` rejects a box that meets its neighbours, the badge or
the quadrant edge, and `test_p4_wiring.py` pins every icon at 16×16, inked
in rows 1–14 (`_ICON_INK_INSET_ROWS`), and every unit glyph at 8×8.

Two contracts, each enforced where it belongs:

- **Layout contract, checked at boot.** A square box `32 × S`, with
  `icon_scale = box // native`. Raise if the scale comes out as 0 (art too
  large for its box). Unit glyphs keep the secondary text scale, since they
  sit beside the text.
- **Art contract, checked by a test.** Every band icon shares one square
  native size, and so do the unit glyphs. Mixed sizes would get different
  scales and so render at different visual sizes. Generalise the existing
  `== (16, 16)` / `== (8, 8)` assertions to "all equal".

Effect: 16 px art draws at scale 2 when `S = 1` and at 4 when `S = 2`.
32 px art for a larger panel draws at scale 2: sharper, with the same
footprint and no code change.

### 3. Every view asserts its fit at boot

Each view raises a `RuntimeError` naming itself, like today's header and
Sensors layout guards. There are no silent clips. Missing today:

- **Calendar:** the derived bar height is ≥ 1.
- **Ring:** the text lines fit inside the inner circle. Today a panel that
  is too small fails with a cryptic `math domain error` from `sqrt`.

### 4. Leftover space

Panels are rarely an exact multiple of 240×240 (800×480 at `S = 2` leaves a
320 px strip, for example). Width already flows into the space fillers
(Sensors quadrants and graphs, Calendar bars); Ring, Status and the Sensors
badge centre.

## Open questions (settle in the plan review)

1. **Source of `S`.** An explicit `UI_SCALE` key (lean: predictable, and the
   boot guards validate it), auto-derived as
   `max(1, min(W // 240, H // 240))`, or both (`UI_SCALE = 0` meaning auto).
2. **1-px elements.** Do seams, ticks, the now-line, the baseline, the label
   separation and the Sensors graph line scale to `S` px, or stay hairlines?
   For the Sensors graphs, 1-px columns give `S×` more history resolution
   (and `S×` the `SampleHistory` capacity at 16 B per column, and `S×` the
   commit's in-place shift, about 6 ms at today's 119 columns), while `S`-px
   columns keep today's resolution and visual weight.
3. **Leftover space.** Does the Calendar window stay at 2 h on a wider
   panel? Widening it cascades into the network forecast horizons, which
   `app.py` derives from the calendar windows.
4. **Art for larger panels.** Upscale the 16 px set, or ship a native
   higher-resolution set? Today's 20 icons pack to 2,176 bytes, so a 32 px
   set costs about 4× that in flash.
5. **The duplicated bitmap8 ink offset.** Calendar's inline `+ 2` and
   Sensors' `_UNIT_DROP_PX` both make up for ink sitting high in its cell.
   Lean: one shared constant, since it's a font property.

## Steps (one commit each)

0. **Plan review.** This is a cross-cutting refactor, so: plan-stage review
   panel before any code, then an implementation review and design duck.
1. **Snapshot tests.** Pin the draw-call log of each view's first frame at
   today's config, with fixed time and inputs. This is the pixel-identity
   safety net for everything after it. `FakePicoGraphics` records `clear`,
   `rectangle`, `text`, `pixel` and `circle`, but not `line` (Calendar ticks
   and baseline) or `polygon` (Ring), so extend it first.
2. **Thread `S` through.** Add `UI_SCALE`, pass `ui_scale` into each
   `Geometry`, and multiply its constants: one commit per view. The
   snapshots must not change at `S = 1`.
3. **Derive text scales from `S`** and retire `TEXT_SCALE`.
4. **Sensors icon box** (§2): box budget and the art-uniformity test.
5. **Vertical fit guards** (§3).
6. **1-px policy**, once decided.

## Verification

- **`S = 1`:** snapshots unchanged. On the device, the Sensors geometry
  must be unchanged too (add `ui_scale=1` once it exists). Run this at the
  REPL after Ctrl-C, reusing `main.py`'s `PICO_GRAPHICS`: a second
  `PicoGraphics` would allocate a 57.6 KB RGB332 framebuffer, more than a
  booted heap has free.

  ```python
  from displays.sensors import Geometry
  g = Geometry(pico_graphics=PICO_GRAPHICS, font="bitmap8", font_height=8,
               value_text_scale=3, label_text_scale=2, tick_period_ms=500)
  print((g.value_offset, g.range_offset, g.graph_offset, g.graph_height,
         g.graph_columns, g.ticks_per_commit, g.badge_rects, g.badge_r))
  # expect (36, 61, 79, 39, 119, 1465,
  #         ((105, 91, 30, 14), (89, 109, 63, 21), (91, 134, 58, 16)), 48)
  ```
- **`S = 2`:** on a 480×480 fake, every fixed layout value exactly doubles.
  `_fakes.bitmap8_width` is exact at any scale, so text-derived values are
  exact too. Any exception (floor-division rounding, 1-px elements, ring
  rasterization) gets listed and justified in the test.
- **Each new guard:** one test where it raises, and one where it passes at
  the shipped config.

## Out of scope, but these gate the choice of panel

- **Framebuffer memory.** A `PEN_P4` framebuffer is `W × H / 2` bytes, on a
  GC heap of 178,112 B on Pimoroni v1.29.0-2 (196,800 B on the earlier
  1.27-based build), about 32 KB of it free once the app has booted. Today,
  240×240 needs 28.8 KB. 480×480 would need 115 KB, and 800×480 would need
  192 KB, more than the entire heap; even a 1-bit 800×480 framebuffer would
  need 48 KB, 19.2 KB more than today's. On the RP2040 a larger panel is only
  viable at a lower bit depth (typical for e-ink) or on a board with more
  RAM.
- **E-ink refresh.** A full refresh takes seconds and flashes the panel.
  Sensors renders every second and already pushes a frame only when
  something changed, but a BME690 reading can change a value every 5 s;
  Calendar scrolls every minute. Both need a slower update strategy
  (`refresh_period_ms`, `RefreshGate`), not just new geometry.
- **Colour language.** The 16-colour palette, the `LABEL_FOR_SLOT` contrast
  table and the CVD verification all assume a colour panel. A mono or
  three-colour panel needs its own palette.
- **Hardware module.** The display constant (`DISPLAY_PICO_EXPLORER`) and the
  pins in `hardware/explorer.py` are Explorer-specific.

**After the work outlined in this plan is completed, the plan should be removed.**