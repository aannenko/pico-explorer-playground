from __future__ import annotations

import pytest

from displays.countdown import Display, DURATIONS_SEC
from displays.ring import RING_SEGMENTS, TEXT_ABOVE_CENTER, TEXT_BELOW_CENTER, TEXT_CENTER
from services.countdown_timer import (
    CountdownTimer,
    INITIAL,
    RUNNING,
    PAUSED,
    DONE,
)

from conftest import RecordingRenderer


class FakeRenderer(RecordingRenderer):
    """Recording renderer with countdown-specific segment tracking."""

    def __init__(self) -> None:
        super().__init__()
        self.segments_cleared = 0

    def reset(self) -> None:
        self.calls.append(("reset", (), {}))
        self.segments_cleared = 0

    def clear_ring_segments(self, count: int) -> None:
        self.calls.append(("clear_ring_segments", (count,), {}))
        if count > self.segments_cleared:
            self.segments_cleared = count


def _mk_display(now=1000):
    """Build a Display + CountdownTimer with shared fakes and a mutable clock."""
    current_time = [now]
    get_time = lambda: current_time[0]
    renderer = FakeRenderer()
    on_done_calls: list[int] = []
    on_configure_calls: list[int] = []

    engine = CountdownTimer(
        on_done=lambda: on_done_calls.append(1),
        on_configure=lambda: on_configure_calls.append(1),
        get_time=get_time,
    )

    display = Display(renderer=renderer, countdown_timer=engine)

    return display, engine, renderer, on_done_calls, on_configure_calls, current_time


def _display_in(state: int) -> tuple[Display, CountdownTimer, FakeRenderer, list[int]]:
    """An entered display with its default 2-hour countdown driven to ``state``, started at 1000 s unless INITIAL,
    with its renderer's record cleared."""
    d, engine, renderer, _, _, clock = _mk_display()
    d.initialize()
    if state != INITIAL:
        d.on_button_a()  # Start
    if state == PAUSED:
        d.on_button_a()  # Pause
    elif state == DONE:
        clock[0] += engine.total_sec
        engine._tick()
        d.render()
    assert engine.state == state
    renderer.calls.clear()
    renderer.update_calls = 0
    return d, engine, renderer, clock


# ── initialize / deinitialize ──────────────────────────────────────────


def test_initialize_shows_idle_screen_with_default_label() -> None:
    d, engine, renderer, *_ = _mk_display()
    d.initialize()

    assert d._active is True
    assert engine.state == INITIAL
    assert ("reset", (), {}) in renderer.calls
    assert ("write_text", (TEXT_CENTER, "2 hours"), {}) in renderer.calls
    assert renderer.update_calls >= 1


def test_initialize_is_idempotent() -> None:
    d, *_ = _mk_display()
    d.initialize()
    calls_after_first = len(d._renderer.calls)

    d.initialize()
    assert len(d._renderer.calls) == calls_after_first


def test_deinitialize_deactivates_the_display_idempotently() -> None:
    d, *_ = _mk_display()
    d.initialize()

    d.deinitialize()
    assert d._active is False

    d.deinitialize()
    assert d._active is False


# ── button B: cycle duration ───────────────────────────────────────────


@pytest.mark.parametrize(
    "press_count, label, total_sec",
    [(1, "4 hours", 4 * 3600), (3, "5 min", 5 * 60), (len(DURATIONS_SEC), "2 hours", 2 * 3600)],
)
def test_on_button_b_cycles_the_duration_in_idle_wrapping_after_the_last(
    press_count: int, label: str, total_sec: int
) -> None:
    d, engine, renderer, _ = _display_in(INITIAL)

    for _ in range(press_count):
        d.on_button_b()

    assert engine.label == label
    assert engine.total_sec == total_sec
    assert renderer.calls[-1] == ("write_text", (TEXT_CENTER, label), {})
    assert renderer.update_calls == press_count


# ── button A: start countdown ─────────────────────────────────────────


def test_on_button_a_starts_countdown() -> None:
    d, engine, renderer, *_, clock = _mk_display()
    d.initialize()
    renderer.calls.clear()
    renderer.update_calls = 0

    d.on_button_a()

    assert engine.state == RUNNING
    assert ("reset", (), {}) in renderer.calls
    assert ("write_text", (TEXT_CENTER, "2 hours"), {}) in renderer.calls
    assert renderer.update_calls >= 1


def test_on_button_a_pauses_in_running() -> None:
    d, engine, renderer, _ = _display_in(RUNNING)

    d.on_button_a()

    assert engine.state == PAUSED
    assert ("write_text", (TEXT_ABOVE_CENTER, "Paused"), {}) in renderer.calls


# ── reset to idle ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "state, button",
    [(RUNNING, "b"), (PAUSED, "b"), (DONE, "b"), (DONE, "a")],
    ids=["b-running", "b-paused", "b-done", "a-done"],
)
def test_button_resets_a_started_countdown_to_the_idle_screen(state: int, button: str) -> None:
    d, engine, renderer, _ = _display_in(state)

    getattr(d, f"on_button_{button}")()

    assert engine.state == INITIAL
    assert ("reset", (), {}) in renderer.calls
    assert ("write_text", (TEXT_CENTER, "2 hours"), {}) in renderer.calls


# ── render() ───────────────────────────────────────────────────────────


# The 2-hour countdown clears one of the ring's 120 segments a minute.
@pytest.mark.parametrize(
    "elapsed_sec, elapsed_text, remaining_text, cleared_segment_count",
    [(600, "00:10:00", "-01:50:00", 10), (3661, "01:01:01", "-00:58:59", 61)],
)
def test_render_while_running_shows_the_time_and_drains_the_ring(
    elapsed_sec: int, elapsed_text: str, remaining_text: str, cleared_segment_count: int
) -> None:
    d, _, renderer, clock = _display_in(RUNNING)
    clock[0] += elapsed_sec

    d.render()

    assert ("write_text", (TEXT_ABOVE_CENTER, elapsed_text), {}) in renderer.calls
    assert ("write_text", (TEXT_BELOW_CENTER, remaining_text), {}) in renderer.calls
    assert ("clear_ring_segments", (cleared_segment_count,), {}) in renderer.calls
    assert renderer.update_calls == 1


def test_update_display_does_nothing_in_idle() -> None:
    d, engine, renderer, *_ = _mk_display()
    d.initialize()
    renderer.calls.clear()
    renderer.update_calls = 0

    d._update_display()

    time_writes = [c for c in renderer.calls if c[0] == "write_text"]
    assert time_writes == []
    assert renderer.update_calls == 0


def test_render_detects_done_state() -> None:
    d, engine, renderer, clock = _display_in(RUNNING)
    clock[0] += engine.total_sec
    engine._tick()  # Engine transitions to DONE

    d.render()

    assert ("write_text", (TEXT_CENTER, engine.label), {}) in renderer.calls
    assert ("write_text", (TEXT_ABOVE_CENTER, "Done!"), {}) in renderer.calls
    assert ("write_text", (TEXT_BELOW_CENTER, "-00:00:00"), {}) in renderer.calls
    assert ("clear_ring_segments", (RING_SEGMENTS,), {}) in renderer.calls


# ── pause / resume ────────────────────────────────────────────────────


def test_resume_restores_ring_and_time() -> None:
    d, engine, renderer, *_, clock = _mk_display()
    d.initialize()
    d.on_button_a()

    clock[0] = 1060  # 60s elapsed
    d.on_button_a()  # Pause

    clock[0] = 2000
    renderer.calls.clear()
    renderer.update_calls = 0
    d.on_button_a()  # Resume

    assert engine.state == RUNNING
    # Ring progress restored: 60 * 120 // 7200 = 1 segment
    assert ("clear_ring_segments", (1,), {}) in renderer.calls
    assert renderer.update_calls >= 1


# ── survive display switch ────────────────────────────────────────────


def test_countdown_survives_display_switch() -> None:
    """Start countdown → deinitialize → time passes → initialize → state restored."""
    d, engine, renderer, *_, clock = _mk_display()
    d.initialize()
    d.on_button_a()  # Start 2-hour countdown

    assert engine.state == RUNNING

    # Switch away
    d.deinitialize()
    assert d._active is False
    assert engine.state == RUNNING  # Engine still running!

    # Time passes (600 seconds = 10 minutes)
    clock[0] = 1000 + 600
    renderer.calls.clear()
    renderer.update_calls = 0

    # Switch back
    d.initialize()

    assert d._active is True
    assert engine.state == RUNNING

    # Ring segments should be recalculated: 600 * 120 // 7200 = 10
    assert renderer.segments_cleared == 10
    assert ("clear_ring_segments", (10,), {}) in renderer.calls
    assert ("write_text", (TEXT_CENTER, "2 hours"), {}) in renderer.calls
    assert renderer.update_calls >= 1


def test_done_fires_while_away() -> None:
    """Engine done fires while display is deinitialized — on_done callback fires."""
    d, engine, renderer, on_done_calls, _, clock = _mk_display()
    d.initialize()
    d.on_button_a()  # Start
    d.deinitialize()  # Switch away

    # Engine done fires
    clock[0] += engine.total_sec
    engine._tick()
    assert engine.state == DONE
    assert len(on_done_calls) == 1

    # Come back — display should show "Done!"
    renderer.calls.clear()
    d.initialize()
    assert ("write_text", (TEXT_CENTER, engine.label), {}) in renderer.calls
    assert ("write_text", (TEXT_ABOVE_CENTER, "Done!"), {}) in renderer.calls
    assert ("write_text", (TEXT_BELOW_CENTER, "-00:00:00"), {}) in renderer.calls
    assert ("clear_ring_segments", (RING_SEGMENTS,), {}) in renderer.calls


def test_paused_survives_display_switch() -> None:
    d, engine, renderer, *_, clock = _mk_display()
    d.initialize()
    d.on_button_a()  # Start

    clock[0] = 1060  # 60s elapsed
    d.on_button_a()  # Pause
    d.deinitialize()  # Switch away

    assert engine.state == PAUSED

    renderer.calls.clear()
    d.initialize()  # Come back

    # Ring progress restored: 60 * 120 // 7200 = 1 segment
    assert renderer.segments_cleared == 1
    assert ("clear_ring_segments", (1,), {}) in renderer.calls
    assert ("write_text", (TEXT_ABOVE_CENTER, "Paused"), {}) in renderer.calls
    # Remaining time shown
    remaining_writes = [c for c in renderer.calls if c[0] == "write_text" and c[1][0] == TEXT_BELOW_CENTER]
    assert len(remaining_writes) == 1
    assert remaining_writes[0][1][1].startswith("-")


def test_resume_after_display_switch_updates_screen() -> None:
    """Bug repro: start → pause → switch away → come back → resume → display must update."""
    d, engine, renderer, *_, clock = _mk_display()
    d.initialize()

    # Pick 5 min timer
    for _ in range(3):
        d.on_button_b()  # cycle: 4h → 8h → 5min

    d.on_button_a()  # Start 5-min countdown
    assert engine.state == RUNNING

    clock[0] = 1060  # 60s elapsed
    d.on_button_a()  # Pause
    assert engine.state == PAUSED

    d.deinitialize()  # Switch away
    assert engine.state == PAUSED

    d.initialize()  # Come back — shows paused state
    assert engine.state == PAUSED

    # Resume
    renderer.calls.clear()
    renderer.update_calls = 0
    clock[0] = 2000  # time advanced while on pause screen
    d.on_button_a()  # Resume

    assert engine.state == RUNNING

    # Elapsed time should be rendered (60s elapsed before pause)
    elapsed_writes = [c for c in renderer.calls if c[0] == "write_text" and c[1][0] == TEXT_ABOVE_CENTER]
    assert len(elapsed_writes) >= 1
    assert elapsed_writes[-1][1][1] == "00:01:00"

    # Remaining time should be rendered
    remaining_writes = [c for c in renderer.calls if c[0] == "write_text" and c[1][0] == TEXT_BELOW_CENTER]
    assert len(remaining_writes) >= 1
    assert remaining_writes[-1][1][1] == "-00:04:00"

    # Display must have been updated
    assert renderer.update_calls >= 1
