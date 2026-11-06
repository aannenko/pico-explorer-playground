import time

from picographics import PicoGraphics  # type: ignore


# bitmap8 draws '1' narrower than every other digit, so a date free of '1's is
# the widest (219 px at scale 3 on the 240 px panel).
WIDEST_HEADER = "2044-08-08 04:44"


def format_header_time(local_epoch: int) -> str:
    """Format ``local_epoch`` as ``YYYY-MM-DD HH:MM`` header text."""
    year, month, mday, hour, minute = time.gmtime(local_epoch)[0:5]
    return f"{year:04}-{month:02}-{mday:02} {hour:02}:{minute:02}"


def header_fits(pico_graphics: PicoGraphics, font: str, text_scale: int, width: int) -> bool:
    """Return whether the widest ``format_header_time`` output fits ``width`` px.

    ``PicoGraphics.text()`` clips silently, so check the fit before drawing.
    Sets ``font`` first because ``measure_text`` uses the currently selected font.
    """
    pico_graphics.set_font(font)
    return pico_graphics.measure_text(WIDEST_HEADER, scale=text_scale) <= width
