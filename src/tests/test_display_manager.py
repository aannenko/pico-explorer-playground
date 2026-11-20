from __future__ import annotations

import pytest

from displays.base import Display, RefreshGate
from displays.manager import DisplayManager

# Scheduler period used throughout these tests.  1 ms keeps the math
# trivial: refresh_period_ms = N means "fire every N ticks".
_SCHED_MS = 1


class FakeDisplay(Display):
    """Display with no buttons, configurable refresh cadence."""

    def __init__(self, name: str, refresh_period_ms: int = 0) -> None:
        self.name = name
        # Instance attribute shadowing the class default is fine here.
        self.refresh_period_ms = refresh_period_ms
        self.calls: list[str] = []

    def initialize(self) -> None:
        self.calls.append("initialize")

    def deinitialize(self) -> None:
        self.calls.append("deinitialize")

    def render(self) -> None:
        self.calls.append("render")


class FakeDisplayWithButtons(FakeDisplay):
    def on_button_a(self) -> None:
        self.calls.append("on_button_a")

    def on_button_b(self) -> None:
        self.calls.append("on_button_b")


def _mgr(*displays, tick_period_ms: int = _SCHED_MS) -> DisplayManager:
    return DisplayManager(displays=list(displays), tick_period_ms=tick_period_ms)


# ── lifecycle ──────────────────────────────────────────────────────────


def test_initialize_current_calls_first_display() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = _mgr(d0, d1)
    mgr.initialize_current()

    assert d0.calls == ["initialize"]
    assert d1.calls == []


def test_next_leaves_the_current_view_and_enters_the_next_wrapping_around() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = _mgr(d0, d1)
    mgr.initialize_current()

    mgr.next()

    assert d0.calls == ["initialize", "deinitialize"]
    assert d1.calls == ["initialize"]

    mgr.next()

    assert d0.calls == ["initialize", "deinitialize", "initialize"]
    assert d1.calls == ["initialize", "deinitialize"]


def test_single_display_cycles_to_itself() -> None:
    d0 = FakeDisplay("d0")

    mgr = _mgr(d0)
    mgr.initialize_current()

    mgr.next()

    assert d0.calls == ["initialize", "deinitialize", "initialize"]


def test_previous_goes_backward() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")
    d2 = FakeDisplay("d2")

    mgr = _mgr(d0, d1, d2)
    mgr.initialize_current()

    mgr.previous()  # d0 -> d2 (wraps)

    assert "deinitialize" in d0.calls
    assert "initialize" in d2.calls
    assert d1.calls == []


# ── button forwarding ─────────────────────────────────────────────────


@pytest.mark.parametrize("button", ["a", "b"])
def test_button_press_forwards_to_current_display(button: str) -> None:
    d0 = FakeDisplayWithButtons("d0")
    d1 = FakeDisplay("d1")

    mgr = _mgr(d0, d1)
    mgr.initialize_current()

    getattr(mgr, "_do_on_button_" + button)(0)

    assert "on_button_" + button in d0.calls


@pytest.mark.parametrize("button", ["a", "b"])
def test_button_press_is_ignored_by_a_display_without_its_handler(button: str) -> None:
    d0 = FakeDisplay("d0")

    mgr = _mgr(d0)
    mgr.initialize_current()

    getattr(mgr, "_do_on_button_" + button)(0)

    assert "on_button_" + button not in d0.calls


def test_button_forwarding_follows_cycle() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplayWithButtons("d1")

    mgr = _mgr(d0, d1)
    mgr.initialize_current()

    mgr._do_on_button_a(0)  # d0 has no handler, should be no-op
    mgr.next()  # switch to d1
    mgr._do_on_button_a(0)

    assert "on_button_a" in d1.calls
    assert "on_button_a" not in d0.calls


@pytest.mark.parametrize("switch_ref", ["_do_next", "_do_previous"])
def test_view_switch_refs_take_the_schedule_arg(switch_ref: str) -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = _mgr(d0, d1)
    mgr.initialize_current()

    getattr(mgr, switch_ref)(0)

    assert "deinitialize" in d0.calls
    assert "initialize" in d1.calls


# ── tick → render delegation + gate ───────────────────────────────────


def test_tick_renders_every_tick_when_period_zero() -> None:
    d0 = FakeDisplay("d0", refresh_period_ms=0)

    mgr = _mgr(d0)
    mgr.initialize_current()
    d0.calls.clear()

    mgr.tick()
    mgr.tick()
    mgr.tick()

    assert d0.calls == ["render", "render", "render"]


def test_tick_throttles_render_by_period_ticks() -> None:
    # tick_period_ms=10, refresh_period_ms=30 → render every 3 ticks.
    d0 = FakeDisplay("d0", refresh_period_ms=30)

    mgr = _mgr(d0, tick_period_ms=10)
    mgr.initialize_current()
    d0.calls.clear()

    for _ in range(7):
        mgr.tick()

    # Fires at ticks 3 and 6.
    assert d0.calls == ["render", "render"]


def test_tick_gate_resets_on_view_switch() -> None:
    d0 = FakeDisplay("d0", refresh_period_ms=30)
    d1 = FakeDisplay("d1", refresh_period_ms=30)

    mgr = _mgr(d0, d1, tick_period_ms=10)
    mgr.initialize_current()
    d0.calls.clear()

    mgr.tick()
    mgr.tick()  # gate at 2/3 for d0

    mgr.next()  # switches to d1; d1's gate starts fresh at 0
    d1.calls.clear()

    mgr.tick()
    mgr.tick()
    # Only 2 ticks on d1 — still below its 3-tick period.
    assert "render" not in d1.calls

    mgr.tick()
    assert d1.calls == ["render"]


@pytest.mark.parametrize("button", ["a", "b"])
def test_button_press_restarts_the_redraw_cadence_of_a_display_with_its_handler(button: str) -> None:
    d0 = FakeDisplayWithButtons("d0", refresh_period_ms=30)

    mgr = _mgr(d0, tick_period_ms=10)
    mgr.initialize_current()
    d0.calls.clear()

    mgr.tick()
    mgr.tick()  # gate at 2/3

    getattr(mgr, "_do_on_button_" + button)(0)
    mgr.tick()
    mgr.tick()
    assert "render" not in d0.calls

    mgr.tick()
    assert "render" in d0.calls


def test_noop_button_press_does_not_reset_gate() -> None:
    # FakeDisplay inherits the base no-op on_button_a/on_button_b; the
    # manager should leave the cadence alone so stray presses don't
    # delay the next redraw on views that don't handle buttons.
    d0 = FakeDisplay("d0", refresh_period_ms=30)

    mgr = _mgr(d0, tick_period_ms=10)
    mgr.initialize_current()
    d0.calls.clear()

    mgr.tick()
    mgr.tick()  # gate at 2/3

    mgr._do_on_button_a(0)
    mgr._do_on_button_b(0)

    mgr.tick()  # gate was not reset → this tick fires
    assert d0.calls == ["render"]


# ── RefreshGate unit tests ────────────────────────────────────────────


def test_refresh_gate_fires_every_period_ticks() -> None:
    gate = RefreshGate(3)

    fires = [gate.admit_tick() for _ in range(7)]

    # Pattern: F F T F F T F
    assert fires == [False, False, True, False, False, True, False]


@pytest.mark.parametrize("period_ticks", [1, 0])
def test_refresh_gate_of_period_one_or_less_fires_every_call(period_ticks: int) -> None:
    gate = RefreshGate(period_ticks)

    assert [gate.admit_tick() for _ in range(3)] == [True, True, True]


def test_refresh_gate_reset_restarts_count() -> None:
    gate = RefreshGate(3)
    gate.admit_tick()
    gate.admit_tick()  # count = 2/3

    gate.reset()

    # After reset, need 3 more calls to fire again.
    assert [gate.admit_tick() for _ in range(3)] == [False, False, True]
