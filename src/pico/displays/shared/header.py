import time

from picographics import PicoGraphics  # type: ignore


# Three characters per name, sliced out rather than kept as 19 short literals that would each take a qstr slot.
WEEKDAY_NAMES = "MonTueWedThuFriSatSun"
MONTH_NAMES = "JanFebMarAprMayJunJulAugSepOctNovDec"

# bitmap8 draws '1' narrower than every other digit.
WIDEST_TIME_TEXT = "00:00"
WIDEST_MDAY_TEXT = "20"


def format_header_time(local_epoch: int) -> tuple[str, str]:
    """Return the header's time and date for ``local_epoch``, e.g. ``("13:08", "Mon 2 Nov")``."""
    fields = time.gmtime(local_epoch)
    month, mday, hour, minute = fields[1:5]
    weekday_start = 3 * fields[6]
    month_start = 3 * (month - 1)
    weekday = WEEKDAY_NAMES[weekday_start:weekday_start + 3]
    return f"{hour:02}:{minute:02}", weekday + " " + str(mday) + " " + MONTH_NAMES[month_start:month_start + 3]


def header_date_x(pico_graphics: PicoGraphics, font: str, text_scale: int) -> int:
    """Return where the header's date starts: after the widest time and a space, so it never moves.

    Sets ``font`` first because ``measure_text`` uses the currently selected font.
    """
    pico_graphics.set_font(font)
    # A space's advance is its width plus one glyph spacing, which is text_scale px.
    return (
        pico_graphics.measure_text(WIDEST_TIME_TEXT, scale=text_scale)
        + pico_graphics.measure_text(" ", scale=text_scale)
        + text_scale
    )


def header_fits(pico_graphics: PicoGraphics, font: str, text_scale: int, width: int) -> bool:
    """Return whether every header ``format_header_time`` can produce fits ``width`` px with its date at
    ``header_date_x``.

    ``PicoGraphics.text()`` clips silently, so check the fit before drawing.  Selects ``font``, as
    ``header_date_x`` does.
    """
    date_x = header_date_x(pico_graphics, font, text_scale)
    widest_date = (
        widest_name(pico_graphics, WEEKDAY_NAMES, text_scale)
        + " " + WIDEST_MDAY_TEXT + " "
        + widest_name(pico_graphics, MONTH_NAMES, text_scale)
    )
    return date_x + pico_graphics.measure_text(widest_date, scale=text_scale) <= width


def widest_name(pico_graphics: PicoGraphics, names: str, text_scale: int) -> str:
    """Return the widest of the three-character names packed in ``names``."""
    widest = ""
    widest_px = -1
    for i in range(0, len(names), 3):
        name = names[i:i + 3]
        name_px = pico_graphics.measure_text(name, scale=text_scale)
        if name_px > widest_px:
            widest = name
            widest_px = name_px
    return widest
