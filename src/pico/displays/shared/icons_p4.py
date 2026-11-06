from picographics import PicoGraphics  # type: ignore


def draw_icon(
    gfx: PicoGraphics,
    icon: tuple[int, int, bytes],
    x: int,
    y: int,
    scale: int = 1,
    transparent: int = 0,
) -> None:
    """Draw ``icon`` with top-left ``(x, y)``, each pixel a ``scale``-px square.

    Transparent pixels are skipped, so callers must provide the intended background.
    Draws pixel by pixel in Python, so keep it off per-frame paths.
    """
    w, h, data = icon
    ni = 0
    for row in range(h):
        for col in range(w):
            byte = data[ni >> 1]
            idx = (byte >> 4) if (ni & 1) == 0 else (byte & 0x0F)
            ni += 1
            if idx == transparent:
                continue
            gfx.set_pen(idx)
            gfx.rectangle(x + col * scale, y + row * scale, scale, scale)
