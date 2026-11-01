import time

from picographics import PicoGraphics  # type: ignore


# Widest string ``format_header_time`` can emit: bitmap8 draws '1' narrower than
# every other digit, so a date free of '1's is the worst case (219 px at
# bitmap8/scale 3 on the 240 px Explorer, device-measured; "2111-11-11 11:11" is
# only 186).
WIDEST_HEADER = "2044-08-08 04:44"


def format_header_time(local_epoch: int) -> str:
    """Format a local-epoch timestamp as `YYYY-MM-DD HH:MM` for display headers."""
    year, month, mday, hour, minute = time.gmtime(local_epoch)[0:5]
    return f"{year:04}-{month:02}-{mday:02} {hour:02}:{minute:02}"


def header_fits(pico_graphics: PicoGraphics, font: str, text_scale: int, width: int) -> bool:
    """Whether the widest ``format_header_time`` output fits ``width`` px.

    Headers are drawn at x=0 against a full-width clear and are never measured
    at render time, so the fit is an invariant each view must assert at boot —
    ``PicoGraphics.text()`` clips silently at the panel edge rather than
    complaining.  Callers raise their own error so it names the view.

    Selects ``font`` first: ``measure_text`` reports against whatever font is
    currently set, and the header views needn't share one.
    """
    pico_graphics.set_font(font)
    return pico_graphics.measure_text(WIDEST_HEADER, scale=text_scale) <= width
