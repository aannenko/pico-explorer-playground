from __future__ import annotations

import time

from _fakes import FakePicoGraphics
from displays.shared.header import WIDEST_HEADER, format_header_time, header_fits


class TestFormatHeaderTime:
    def test_typical_timestamp(self):
        # 2026-04-10 17:56 UTC
        epoch = time.mktime((2026, 4, 10, 17, 56, 0, 0, 0))

        assert format_header_time(epoch) == "2026-04-10 17:56"

    def test_midnight(self):
        epoch = time.mktime((2026, 1, 1, 0, 0, 0, 0, 0))

        assert format_header_time(epoch) == "2026-01-01 00:00"


class TestWidestHeader:
    def test_matches_the_formatter_shape(self):
        """WIDEST_HEADER must be a string format_header_time could actually
        emit, or it bounds the wrong thing."""
        epoch = time.mktime((2044, 8, 8, 4, 44, 0, 0, 0))

        assert format_header_time(epoch) == WIDEST_HEADER

    def test_is_the_widest_the_formatter_can_emit(self):
        """bitmap8 draws '1' narrower than other digits, so an all-'1's date is
        the narrowest and WIDEST_HEADER must beat it.  Guards the choice of
        sample the boot checks depend on."""
        gfx = FakePicoGraphics()
        narrowest = format_header_time(time.mktime((2111, 11, 11, 11, 11, 0, 0, 0)))

        assert gfx.measure_text(WIDEST_HEADER, scale=3) == 219  # device-measured
        assert gfx.measure_text(narrowest, scale=3) == 186
        assert gfx.measure_text(WIDEST_HEADER, scale=3) > gfx.measure_text(narrowest, scale=3)


class TestHeaderFits:
    def test_shipped_font_and_scale_fit_the_panel(self):
        """bitmap8/scale 3 must clear the 240 px Explorer, or the Calendar view halts."""
        gfx = FakePicoGraphics()
        width, _height = gfx.get_bounds()

        assert header_fits(gfx, "bitmap8", 3, width)

    def test_rejects_a_scale_that_overflows(self):
        """Scale 4 is 292 px on a 240 px panel — the case that used to clip the
        date off the right edge silently."""
        gfx = FakePicoGraphics()

        assert not header_fits(gfx, "bitmap8", 4, 240)

    def test_selects_the_font_before_measuring(self):
        """measure_text reports against whatever font is currently set, so the
        helper must select its own — another view may have left a different one."""
        gfx = FakePicoGraphics()
        gfx.set_font("some-other-font")

        header_fits(gfx, "bitmap8", 3, 240)

        fonts = [c[1][0] for c in gfx.calls if c[0] == "set_font"]
        assert fonts[-1] == "bitmap8"

    def test_boundary_is_inclusive(self):
        """A header exactly as wide as the panel still fits — it occupies
        columns 0..width-1."""
        gfx = FakePicoGraphics()
        exact = gfx.measure_text(WIDEST_HEADER, scale=3)

        assert header_fits(gfx, "bitmap8", 3, exact)
        assert not header_fits(gfx, "bitmap8", 3, exact - 1)

