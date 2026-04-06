from displays.events import Colors


def test_colors_stores_values() -> None:
    c = Colors(background=1, ring=2, primary_text=3, secondary_text=4)
    assert c.background == 1
    assert c.ring == 2
    assert c.primary_text == 3
    assert c.secondary_text == 4
