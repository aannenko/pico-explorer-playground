from __future__ import annotations

from displays.manager import DisplayManager


class FakeDisplay:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, tuple]] = []

    def initialize(self, *args) -> None:
        self.calls.append(("initialize", args))

    def deinitialize(self) -> None:
        self.calls.append(("deinitialize", ()))


def test_initialize_current_calls_first_display() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = DisplayManager(
        displays=[d0, d1],
        initializers=[lambda: (), lambda: ("arg1",)],
    )
    mgr.initialize_current()

    assert d0.calls == [("initialize", ())]
    assert d1.calls == []


def test_cycle_deinitializes_current_and_initializes_next() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = DisplayManager(
        displays=[d0, d1],
        initializers=[lambda: (), lambda: ("arg1",)],
    )
    mgr.initialize_current()
    d0.calls.clear()

    mgr.cycle()

    assert d0.calls == [("deinitialize", ())]
    assert d1.calls == [("initialize", ("arg1",))]


def test_cycle_wraps_around() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = DisplayManager(
        displays=[d0, d1],
        initializers=[lambda: (), lambda: ("x",)],
    )
    mgr.initialize_current()

    mgr.cycle()  # d0 -> d1
    mgr.cycle()  # d1 -> d0

    # d0 should have: initialize, deinitialize, initialize
    assert d0.calls == [
        ("initialize", ()),
        ("deinitialize", ()),
        ("initialize", ()),
    ]
    # d1 should have: initialize, deinitialize
    assert d1.calls == [
        ("initialize", ("x",)),
        ("deinitialize", ()),
    ]


def test_initializer_args_are_passed_through() -> None:
    d0 = FakeDisplay("d0")

    mgr = DisplayManager(
        displays=[d0],
        initializers=[lambda: ("a", "b", "c")],
    )
    mgr.initialize_current()

    assert d0.calls == [("initialize", ("a", "b", "c"))]


def test_single_display_cycles_to_itself() -> None:
    d0 = FakeDisplay("d0")

    mgr = DisplayManager(
        displays=[d0],
        initializers=[lambda: ()],
    )
    mgr.initialize_current()

    mgr.cycle()

    assert d0.calls == [
        ("initialize", ()),
        ("deinitialize", ()),
        ("initialize", ()),
    ]
