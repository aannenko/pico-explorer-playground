from __future__ import annotations

from displays.base import Display
from displays.manager import DisplayManager


class FakeDisplay(Display):
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []

    def initialize(self) -> None:
        self.calls.append("initialize")

    def deinitialize(self) -> None:
        self.calls.append("deinitialize")


def test_initialize_current_calls_first_display() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = DisplayManager(displays=[d0, d1])
    mgr.initialize_current()

    assert d0.calls == ["initialize"]
    assert d1.calls == []


def test_cycle_deinitializes_current_and_initializes_next() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = DisplayManager(displays=[d0, d1])
    mgr.initialize_current()
    d0.calls.clear()

    mgr.next()

    assert d0.calls == ["deinitialize"]
    assert d1.calls == ["initialize"]


def test_cycle_wraps_around() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = DisplayManager(displays=[d0, d1])
    mgr.initialize_current()

    mgr.next()  # d0 -> d1
    mgr.next()  # d1 -> d0

    assert d0.calls == ["initialize", "deinitialize", "initialize"]
    assert d1.calls == ["initialize", "deinitialize"]


def test_single_display_cycles_to_itself() -> None:
    d0 = FakeDisplay("d0")

    mgr = DisplayManager(displays=[d0])
    mgr.initialize_current()

    mgr.next()

    assert d0.calls == ["initialize", "deinitialize", "initialize"]


# ── button forwarding ─────────────────────────────────────────────────


class FakeDisplayWithButtons(Display):
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []

    def initialize(self) -> None:
        self.calls.append("initialize")

    def deinitialize(self) -> None:
        self.calls.append("deinitialize")

    def tick(self) -> None:
        self.calls.append("tick")

    def on_button_a(self) -> None:
        self.calls.append("on_button_a")

    def on_button_b(self) -> None:
        self.calls.append("on_button_b")


def test_on_button_a_forwards_to_current_display() -> None:
    d0 = FakeDisplayWithButtons("d0")
    d1 = FakeDisplay("d1")

    mgr = DisplayManager(displays=[d0, d1])
    mgr.initialize_current()

    mgr._do_on_button_a(0)

    assert "on_button_a" in d0.calls


def test_on_button_b_forwards_to_current_display() -> None:
    d0 = FakeDisplayWithButtons("d0")

    mgr = DisplayManager(displays=[d0])
    mgr.initialize_current()

    mgr._do_on_button_b(0)

    assert "on_button_b" in d0.calls


def test_on_button_a_ignored_for_display_without_handler() -> None:
    d0 = FakeDisplay("d0")  # No on_button_a override — base no-op

    mgr = DisplayManager(displays=[d0])
    mgr.initialize_current()

    # Should not raise
    mgr._do_on_button_a(0)

    assert "on_button_a" not in d0.calls


def test_on_button_b_ignored_for_display_without_handler() -> None:
    d0 = FakeDisplay("d0")  # No on_button_b override — base no-op

    mgr = DisplayManager(displays=[d0])
    mgr.initialize_current()

    # Should not raise
    mgr._do_on_button_b(0)

    assert "on_button_b" not in d0.calls


def test_button_forwarding_follows_cycle() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplayWithButtons("d1")

    mgr = DisplayManager(displays=[d0, d1])
    mgr.initialize_current()

    mgr._do_on_button_a(0)  # d0 has no handler, should be no-op
    mgr.next()  # switch to d1
    mgr._do_on_button_a(0)

    assert "on_button_a" in d1.calls
    assert "on_button_a" not in d0.calls


def test_do_next_ref_works_with_schedule_signature() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = DisplayManager(displays=[d0, d1])
    mgr.initialize_current()

    mgr._do_next(0)  # Called with int arg like micropython.schedule

    assert "deinitialize" in d0.calls
    assert "initialize" in d1.calls


def test_previous_goes_backward() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")
    d2 = FakeDisplay("d2")

    mgr = DisplayManager(displays=[d0, d1, d2])
    mgr.initialize_current()

    mgr.previous()  # d0 -> d2 (wraps)

    assert "deinitialize" in d0.calls
    assert "initialize" in d2.calls
    assert d1.calls == []


def test_do_previous_ref_works_with_schedule_signature() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = DisplayManager(displays=[d0, d1])
    mgr.initialize_current()

    mgr._do_previous(0)  # Called with int arg like micropython.schedule

    assert "deinitialize" in d0.calls
    assert "initialize" in d1.calls  # wraps to last


# ── tick delegation ───────────────────────────────────────────────────


def test_tick_delegates_to_current_display_with_tick() -> None:
    d0 = FakeDisplayWithButtons("d0")

    mgr = DisplayManager(displays=[d0])
    mgr.initialize_current()

    mgr.tick()

    assert "tick" in d0.calls


def test_tick_ignored_for_display_without_tick() -> None:
    d0 = FakeDisplay("d0")  # No tick override — base no-op

    mgr = DisplayManager(displays=[d0])
    mgr.initialize_current()

    # Should not raise
    mgr.tick()

    assert "tick" not in d0.calls


def test_tick_follows_cycle() -> None:
    d0 = FakeDisplay("d0")  # No tick override
    d1 = FakeDisplayWithButtons("d1")  # Has tick

    mgr = DisplayManager(displays=[d0, d1])
    mgr.initialize_current()

    mgr.tick()  # d0 has no tick override — base no-op
    assert "tick" not in d0.calls

    mgr.next()  # switch to d1
    d1.calls.clear()

    mgr.tick()
    assert "tick" in d1.calls
