from __future__ import annotations

from displays.shared import icons_symbols


class FakeGfx:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def load_spritesheet(self, path: str) -> None:
        self.calls.append(("load_spritesheet", path))

    def sprite(self, sx, sy, x, y, scale=1, transparent=-1) -> None:
        self.calls.append(("sprite", sx, sy, x, y, scale, transparent))


def test_load_uses_fixed_path() -> None:
    gfx = FakeGfx()

    icons_symbols.load(gfx)

    assert gfx.calls == [("load_spritesheet", icons_symbols.SPRITESHEET_PATH)]


def test_draw_icon_emits_four_sprite_calls_with_transparent_black() -> None:
    gfx = FakeGfx()

    icons_symbols.draw_icon(gfx, (4, 0), x=10, y=20, scale=2)

    # step = 8 * 2 = 16
    assert gfx.calls == [
        ("sprite", 4, 0, 10, 20, 2, 0),
        ("sprite", 5, 0, 26, 20, 2, 0),
        ("sprite", 4, 1, 10, 36, 2, 0),
        ("sprite", 5, 1, 26, 36, 2, 0),
    ]


def test_draw_icon_respects_scale() -> None:
    gfx = FakeGfx()

    icons_symbols.draw_icon(gfx, (0, 0), x=0, y=0, scale=3)

    # step = 8 * 3 = 24 → second-column cell lands at x=24, second-row at y=24
    assert ("sprite", 1, 0, 24, 0, 3, 0) in gfx.calls
    assert ("sprite", 0, 1, 0, 24, 3, 0) in gfx.calls
    assert ("sprite", 1, 1, 24, 24, 3, 0) in gfx.calls


def test_draw_sprite_emits_single_sprite_call() -> None:
    gfx = FakeGfx()

    icons_symbols.draw_sprite(gfx, (2, 15), x=40, y=32, scale=3)

    assert gfx.calls == [("sprite", 2, 15, 40, 32, 3, 0)]


def test_unit_and_icon_constants_are_within_16x16_grid() -> None:
    icons = (
        # Row 0: thermometers.
        icons_symbols.ICON_THERMO_BLUE,
        icons_symbols.ICON_THERMO_GREEN,
        icons_symbols.ICON_THERMO_YELLOW,
        icons_symbols.ICON_THERMO_RED,
        # Row 1: water drops.
        icons_symbols.ICON_DROP_LOW,
        icons_symbols.ICON_DROP_MID_LOW,
        icons_symbols.ICON_DROP_MID_HIGH,
        icons_symbols.ICON_DROP_HIGH,
        # Row 2: pressure gauges.
        icons_symbols.ICON_GAUGE_LOW,
        icons_symbols.ICON_GAUGE_MID_LOW,
        icons_symbols.ICON_GAUGE_MID_HIGH,
        icons_symbols.ICON_GAUGE_HIGH,
        # Row 3: gas masks.
        icons_symbols.ICON_GAS_LOW,
        icons_symbols.ICON_GAS_MID_LOW,
        icons_symbols.ICON_GAS_MID_HIGH,
        icons_symbols.ICON_GAS_HIGH,
    )
    units = (
        icons_symbols.UNIT_KOHM,
        icons_symbols.UNIT_MB,
        icons_symbols.UNIT_DEG_C,
        icons_symbols.UNIT_PCT,
    )

    # Icons are 2x2, so top-left must fit inside 15x15 (leave 1 cell for the
    # bottom-right quadrant).
    for sx, sy in icons:
        assert 0 <= sx <= 14
        assert 0 <= sy <= 14
    # Units are single cells.
    for sx, sy in units:
        assert 0 <= sx <= 15
        assert 0 <= sy <= 15


def test_metric_icon_rows_are_distinct_and_ordered() -> None:
    """Each 4-icon metric row should occupy a single sy and step sx by 2."""
    for row in (
        (icons_symbols.ICON_THERMO_BLUE,
         icons_symbols.ICON_THERMO_GREEN,
         icons_symbols.ICON_THERMO_YELLOW,
         icons_symbols.ICON_THERMO_RED),
        (icons_symbols.ICON_DROP_LOW,
         icons_symbols.ICON_DROP_MID_LOW,
         icons_symbols.ICON_DROP_MID_HIGH,
         icons_symbols.ICON_DROP_HIGH),
        (icons_symbols.ICON_GAUGE_LOW,
         icons_symbols.ICON_GAUGE_MID_LOW,
         icons_symbols.ICON_GAUGE_MID_HIGH,
         icons_symbols.ICON_GAUGE_HIGH),
        (icons_symbols.ICON_GAS_LOW,
         icons_symbols.ICON_GAS_MID_LOW,
         icons_symbols.ICON_GAS_MID_HIGH,
         icons_symbols.ICON_GAS_HIGH),
    ):
        sys = {sy for _, sy in row}
        assert len(sys) == 1, f"row {row} spans multiple sy values"
        sxs = [sx for sx, _ in row]
        assert sxs == [0, 2, 4, 6], f"row {row} not in expected sx order"
