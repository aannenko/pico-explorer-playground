from __future__ import annotations

import pytest

from displays.status import StatusDisplay


class FakePicoGraphics:
    def __init__(self, width: int = 240, height: int = 240) -> None:
        self._width = width
        self._height = height
        self.calls: list[tuple[str, tuple, dict]] = []

    def get_bounds(self) -> tuple[int, int]:
        return self._width, self._height

    def set_font(self, font: str) -> None:
        self.calls.append(("set_font", (font,), {}))

    def set_pen(self, pen: int) -> None:
        self.calls.append(("set_pen", (pen,), {}))

    def clear(self) -> None:
        self.calls.append(("clear", (), {}))

    def measure_text(self, text: str, scale: int = 1) -> int:
        return len(text) * 6 * scale

    def text(self, text: str, x: int, y: int, scale: int = 1) -> None:
        self.calls.append(("text", (text, x, y), {"scale": scale}))

    def update(self) -> None:
        self.calls.append(("update", (), {}))


def _mk_display(width: int = 240, height: int = 240) -> tuple[StatusDisplay, FakePicoGraphics]:
    gfx = FakePicoGraphics(width, height)
    display = StatusDisplay(
        pico_graphics=gfx,
        font="bitmap6",
        font_height=6,
        text_scale=3,
        background=0,
        foreground=1,
        subtext_color=2,
    )
    gfx.calls.clear()
    return display, gfx


@pytest.mark.parametrize("subtext_args", [pytest.param((), id="no subtext"), pytest.param(("",), id="empty subtext")])
def test_show_without_subtext_sets_font_clears_and_draws_centered_text(subtext_args: tuple[str, ...]) -> None:
    display, gfx = _mk_display()
    display.show("wifi", *subtext_args)

    call_names = [c[0] for c in gfx.calls]
    assert call_names == ["set_font", "set_pen", "clear", "set_pen", "text", "update"]

    assert gfx.calls[0] == ("set_font", ("bitmap6",), {})
    assert gfx.calls[1] == ("set_pen", (0,), {})
    assert gfx.calls[3] == ("set_pen", (1,), {})
    text_call = gfx.calls[4]
    assert text_call[1][0] == "wifi"
    assert text_call[1][1] == (240 - gfx.measure_text("wifi", scale=3)) // 2
    assert text_call[2] == {"scale": 3}


def test_show_with_subtext_draws_both_lines() -> None:
    display, gfx = _mk_display()
    display.show("wifi", "at 13:05")

    call_names = [c[0] for c in gfx.calls]
    assert call_names == [
        "set_font", "set_pen", "clear",
        "set_pen", "text",
        "set_pen", "text",
        "update",
    ]

    # Subtext pen color
    assert gfx.calls[5] == ("set_pen", (2,), {})
    # Subtext content
    assert gfx.calls[6][1][0] == "at 13:05"


def test_precomputed_y_positions() -> None:
    display, _ = _mk_display(width=240, height=240)
    # text_y = (240 // 2) - (6 * 3) = 120 - 18 = 102
    assert display._text_y == 102
    # subtext_y = (240 // 2) + 5 = 125
    assert display._subtext_y == 125
