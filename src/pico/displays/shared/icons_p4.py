"""Blitter for the 4-bit palette-indexed icons in ``_icons_data``.

Icons are stored as packed 4-bit palette indices (see ``_icons_data``, generated
by ``src/tools/icons-to-p4.py``) and drawn one palette-coloured rectangle per
pixel.  They redraw only on view-entry / band-change, so the per-pixel Python
cost never touches a hot path.

A pen is its palette slot index (0-15); slot ``0`` (BLACK) is the transparent
index and is skipped.  Icons are always drawn on the black view background, so
black interior pixels render correctly even though they are skipped.
"""


def draw_icon(gfx, icon, x: int, y: int, scale: int = 1, transparent: int = 0) -> None:
    # gfx: PicoGraphics; icon: tuple[int, int, bytes] == (width, height, blob)
    """Blit ``icon`` at ``(x, y)``, each pixel scaled to a ``scale x scale`` rect.

    Pixels whose slot index equals ``transparent`` are skipped.
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
