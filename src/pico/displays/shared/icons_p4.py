import micropython
from picographics import PicoGraphics  # type: ignore


def draw_icon(
    gfx: PicoGraphics,
    icon: tuple[int, int, bytes],
    x: int,
    y: int,
    scale: int = 1,
    transparent: int = 0,
    pen: int = -1,
) -> None:
    """Draw ``icon`` with top-left ``(x, y)``, each pixel a ``scale``-px square, in its own colour, or every one in
    ``pen`` unless that is negative.

    Transparent pixels are skipped, so callers must provide the intended background.
    Draws a rectangle per pixel (PicoGraphics' own ``sprite()`` draws nothing
    under ``PEN_P4``), so keep it off per-frame paths.
    """
    width, height, data = icon
    _blit(gfx, data, width, height, x, y, scale, transparent, pen)


@micropython.viper
def _blit(
    gfx,  # PicoGraphics
    data,  # bytes
    width: int,
    height: int,
    x: int,
    y: int,
    scale: int,
    transparent: int,
    pen: int,
):  # -> None
    current_pen = pen
    if pen >= 0:
        gfx.set_pen(pen)
    i = 0
    for row in range(height):
        for col in range(width):
            byte = int(data[i >> 1])
            # Two pixels a byte, the left one in the high nibble.
            slot = (byte >> 4) if (i & 1) == 0 else (byte & 0x0F)
            i += 1
            if slot != transparent:
                if pen < 0 and slot != current_pen:
                    gfx.set_pen(slot)
                    current_pen = slot
                gfx.rectangle(x + col * scale, y + row * scale, scale, scale)
