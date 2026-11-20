from __future__ import annotations

import time

import pytest

from _fakes import FakePicoGraphics
from displays.shared.header import format_header_time, header_date_x, header_fits

_DAY_SEC = 86400


class TestFormatHeaderTime:
    @pytest.mark.parametrize(
        "fields, header",
        [
            ((2026, 4, 10, 17, 56, 0, 0, 0), ("17:56", "Fri 10 Apr")),
            ((2026, 1, 1, 0, 0, 0, 0, 0), ("00:00", "Thu 1 Jan")),
        ],
    )
    def test_formats_a_zero_padded_24_hour_time_and_a_date_with_an_unpadded_day(self, fields, header):
        assert format_header_time(time.mktime(fields)) == header


class TestHeaderDateX:
    def test_date_starts_after_the_widest_time_and_a_space(self):
        gfx = FakePicoGraphics()

        assert header_date_x(gfx, "bitmap8", 3) == 75  # "00:00" 63 px + a space's 12 px advance

    def test_selects_the_font_before_measuring(self):
        gfx = FakePicoGraphics()
        gfx.set_font("some-other-font")

        header_date_x(gfx, "bitmap8", 3)

        fonts = [c[1][0] for c in gfx.calls if c[0] == "set_font"]
        assert fonts[-1] == "bitmap8"


class TestHeaderFits:
    def _widest_header_px(self, gfx: FakePicoGraphics, scale: int) -> int:
        """The widest header over two years of days, its date placed at ``header_date_x``."""
        start = time.mktime((2026, 1, 1, 0, 0, 0, 0, 0))
        date_x = header_date_x(gfx, "bitmap8", scale)
        return max(
            date_x + gfx.measure_text(format_header_time(start + day * _DAY_SEC)[1], scale=scale)
            for day in range(731)
        )

    @pytest.mark.parametrize("scale, fits", [(3, True), (4, False)])
    def test_the_header_fits_the_panel_at_the_shipped_scale_but_not_the_next(self, scale, fits):
        """bitmap8/scale 3 must clear the 240 px Explorer, or the Calendar view halts."""
        gfx = FakePicoGraphics()
        width, _height = gfx.get_bounds()

        assert header_fits(gfx, "bitmap8", scale, width) is fits

    def test_boundary_is_the_widest_real_header(self):
        """The check must bound every date the formatter emits, and no more: it fits exactly the widest one."""
        gfx = FakePicoGraphics()
        widest = self._widest_header_px(gfx, 3)

        assert widest == 222
        assert header_fits(gfx, "bitmap8", 3, widest)
        assert not header_fits(gfx, "bitmap8", 3, widest - 1)
