from __future__ import annotations

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


def _mgr(*displays, scheduler_period_ms: int = _SCHED_MS) -> DisplayManager:
    return DisplayManager(displays=list(displays), scheduler_period_ms=scheduler_period_ms)


# ── lifecycle ──────────────────────────────────────────────────────────


def test_initialize_current_calls_first_display() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = _mgr(d0, d1)
    mgr.initialize_current()

    assert d0.calls == ["initialize"]
    assert d1.calls == []


def test_cycle_deinitializes_current_and_initializes_next() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = _mgr(d0, d1)
    mgr.initialize_current()
    d0.calls.clear()

    mgr.next()

    assert d0.calls == ["deinitialize"]
    assert d1.calls == ["initialize"]


def test_cycle_wraps_around() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = _mgr(d0, d1)
    mgr.initialize_current()

    mgr.next()  # d0 -> d1
    mgr.next()  # d1 -> d0

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


def test_on_button_a_forwards_to_current_display() -> None:
    d0 = FakeDisplayWithButtons("d0")
    d1 = FakeDisplay("d1")

    mgr = _mgr(d0, d1)
    mgr.initialize_current()

    mgr._do_on_button_a(0)

    assert "on_button_a" in d0.calls


def test_on_button_b_forwards_to_current_display() -> None:
    d0 = FakeDisplayWithButtons("d0")

    mgr = _mgr(d0)
    mgr.initialize_current()

    mgr._do_on_button_b(0)

    assert "on_button_b" in d0.calls


def test_on_button_a_ignored_for_display_without_handler() -> None:
    d0 = FakeDisplay("d0")  # No on_button_a override — base no-op

    mgr = _mgr(d0)
    mgr.initialize_current()

    # Should not raise
    mgr._do_on_button_a(0)

    assert "on_button_a" not in d0.calls


def test_on_button_b_ignored_for_display_without_handler() -> None:
    d0 = FakeDisplay("d0")  # No on_button_b override — base no-op

    mgr = _mgr(d0)
    mgr.initialize_current()

    # Should not raise
    mgr._do_on_button_b(0)

    assert "on_button_b" not in d0.calls


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


def test_do_next_ref_works_with_schedule_signature() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = _mgr(d0, d1)
    mgr.initialize_current()

    mgr._do_next(0)  # Called with int arg like micropython.schedule

    assert "deinitialize" in d0.calls
    assert "initialize" in d1.calls


def test_do_previous_ref_works_with_schedule_signature() -> None:
    d0 = FakeDisplay("d0")
    d1 = FakeDisplay("d1")

    mgr = _mgr(d0, d1)
    mgr.initialize_current()

    mgr._do_previous(0)  # Called with int arg like micropython.schedule

    assert "deinitialize" in d0.calls
    assert "initialize" in d1.calls  # wraps to last


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
    # scheduler_period_ms=10, refresh_period_ms=30 → render every 3 ticks.
    d0 = FakeDisplay("d0", refresh_period_ms=30)

    mgr = _mgr(d0, scheduler_period_ms=10)
    mgr.initialize_current()
    d0.calls.clear()

    for _ in range(7):
        mgr.tick()

    # Fires at ticks 3 and 6.
    assert d0.calls == ["render", "render"]


def test_tick_gate_resets_on_view_switch() -> None:
    d0 = FakeDisplay("d0", refresh_period_ms=30)
    d1 = FakeDisplay("d1", refresh_period_ms=30)

    mgr = _mgr(d0, d1, scheduler_period_ms=10)
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


def test_button_press_resets_gate() -> None:
    d0 = FakeDisplayWithButtons("d0", refresh_period_ms=30)

    mgr = _mgr(d0, scheduler_period_ms=10)
    mgr.initialize_current()
    d0.calls.clear()

    mgr.tick()
    mgr.tick()  # gate at 2/3

    mgr._do_on_button_a(0)  # should reset gate
    # After reset, need 3 more ticks before render fires.
    mgr.tick()
    mgr.tick()
    assert "render" not in d0.calls

    mgr.tick()
    assert "render" in d0.calls


def test_button_b_press_resets_gate() -> None:
    d0 = FakeDisplayWithButtons("d0", refresh_period_ms=30)

    mgr = _mgr(d0, scheduler_period_ms=10)
    mgr.initialize_current()
    d0.calls.clear()

    mgr.tick()
    mgr.tick()
    mgr._do_on_button_b(0)
    mgr.tick()
    mgr.tick()

    assert "render" not in d0.calls


# ── RefreshGate unit tests ────────────────────────────────────────────


def test_refresh_gate_fires_every_period_ticks() -> None:
    gate = RefreshGate(3)

    fires = [gate.ready() for _ in range(7)]

    # Pattern: F F T F F T F
    assert fires == [False, False, True, False, False, True, False]


def test_refresh_gate_period_one_fires_every_call() -> None:
    gate = RefreshGate(1)

    assert [gate.ready() for _ in range(3)] == [True, True, True]


def test_refresh_gate_reset_restarts_count() -> None:
    gate = RefreshGate(3)
    gate.ready()
    gate.ready()  # count = 2/3

    gate.reset()

    # After reset, need 3 more calls to fire again.
    assert [gate.ready() for _ in range(3)] == [False, False, True]


def test_refresh_gate_clamps_zero_period_to_one() -> None:
    gate = RefreshGate(0)

    # Clamped to period=1 → fires every call.
    assert gate.ready() is True
    assert gate.ready() is True
