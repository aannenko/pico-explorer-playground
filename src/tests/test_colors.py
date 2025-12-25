from graphics.colors import Colors


def test_colors_stores_values() -> None:
    c = Colors(background=1, ring_color=2, primary_text_color=3, secondary_text_color=4)
    assert c.background == 1
    assert c.ring_color == 2
    assert c.primary_text_color == 3
    assert c.secondary_text_color == 4
