from __future__ import annotations

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


def test_show_sets_font_clears_and_draws_centered_text() -> None:
    display, gfx = _mk_display()
    display.show("wifi")

    call_names = [c[0] for c in gfx.calls]
    assert call_names == ["set_font", "set_pen", "clear", "set_pen", "text", "update"]

    # Verify font
    assert gfx.calls[0] == ("set_font", ("bitmap6",), {})
    # Background pen then clear
    assert gfx.calls[1] == ("set_pen", (0,), {})
    # Foreground pen
    assert gfx.calls[3] == ("set_pen", (1,), {})
    # Text is drawn
    text_call = gfx.calls[4]
    assert text_call[1][0] == "wifi"
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


def test_show_without_subtext_does_not_draw_subtext() -> None:
    display, gfx = _mk_display()
    display.show("sync time")

    text_calls = [c for c in gfx.calls if c[0] == "text"]
    assert len(text_calls) == 1
    assert text_calls[0][1][0] == "sync time"


def test_show_empty_subtext_does_not_draw_subtext() -> None:
    display, gfx = _mk_display()
    display.show("wifi", "")

    text_calls = [c for c in gfx.calls if c[0] == "text"]
    assert len(text_calls) == 1


def test_precomputed_y_positions() -> None:
    display, _ = _mk_display(width=240, height=240)
    # text_y = (240 // 2) - (6 * 3) = 120 - 18 = 102
    assert display._text_y == 102
    # subtext_y = (240 // 2) + 5 = 125
    assert display._subtext_y == 125


def test_text_is_horizontally_centered() -> None:
    display, gfx = _mk_display(width=240, height=240)
    display.show("hi")

    text_call = [c for c in gfx.calls if c[0] == "text"][0]
    text_width = gfx.measure_text("hi", scale=3)
    expected_x = (240 - text_width) // 2
    assert text_call[1][1] == expected_x
