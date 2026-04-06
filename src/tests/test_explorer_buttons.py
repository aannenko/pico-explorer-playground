from __future__ import annotations

from services.utilities.explorer_buttons import ExplorerButtons


class FakePin:
    """Simulates machine.Pin (active-low: value()==0 means pressed)."""

    def __init__(self) -> None:
        self._pressed = False

    def value(self) -> int:
        return 0 if self._pressed else 1


def test_only_fires_on_press_edge() -> None:
    """A held button should fire only once (on the False→True transition)."""
    scheduled: list[tuple[object, int]] = []

    def schedule(fn, arg):
        scheduled.append((fn, arg))

    eb = ExplorerButtons(schedule=schedule)
    btn = FakePin()
    callback = lambda _: None
    eb.add(btn, callback)

    # Simulate a single poll cycle while not pressed
    btn._pressed = False
    eb.poll_once()
    assert len(scheduled) == 0

    # Press the button — first edge fires
    btn._pressed = True
    eb.poll_once()
    assert len(scheduled) == 1

    # Still held — should NOT fire again
    eb.poll_once()
    assert len(scheduled) == 1

    # Still held
    eb.poll_once()
    assert len(scheduled) == 1

    # Release
    btn._pressed = False
    eb.poll_once()
    assert len(scheduled) == 1

    # Press again — new edge fires
    btn._pressed = True
    eb.poll_once()
    assert len(scheduled) == 2


def test_multiple_buttons_independent() -> None:
    scheduled: list[object] = []

    def schedule(fn, arg):
        scheduled.append(fn)

    eb = ExplorerButtons(schedule=schedule)
    btn_a = FakePin()
    btn_b = FakePin()
    cb_a = lambda _: "a"
    cb_b = lambda _: "b"
    eb.add(btn_a, cb_a)
    eb.add(btn_b, cb_b)

    # Only A pressed
    btn_a._pressed = True
    eb.poll_once()
    assert scheduled == [cb_a]

    # A held, B pressed
    btn_b._pressed = True
    eb.poll_once()
    assert scheduled == [cb_a, cb_b]

    # Both held — no new fires
    eb.poll_once()
    assert len(scheduled) == 2
