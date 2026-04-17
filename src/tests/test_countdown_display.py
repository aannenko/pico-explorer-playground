from __future__ import annotations

import displays.countdown as countdown_mod

from displays.countdown import Display, DURATIONS, LABELS
from displays.ring import RING_SEGMENTS, TEXT_ABOVE_CENTER, TEXT_BELOW_CENTER, TEXT_CENTER
from services.countdown_timer import (
    CountdownTimer,
    INITIAL,
    RUNNING,
    PAUSED,
    DONE,
)


class FakeRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.update_calls = 0
        self.segments_cleared = 0

    def reset(self) -> None:
        self.calls.append(("reset", (), {}))
        self.segments_cleared = 0

    def ring_clear_segments(self, count: int) -> None:
        self.calls.append(("ring_clear_segments", (count,), {}))
        if count > self.segments_cleared:
            self.segments_cleared = count

    def text_write(self, position: int, text: str) -> None:
        self.calls.append(("text_write", (position, text), {}))

    def update(self) -> None:
        self.update_calls += 1


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


# ── initialize / deinitialize ──────────────────────────────────────────


def test_initialize_shows_idle_screen_with_default_label() -> None:
    d, engine, renderer, *_ = _mk_display()
    d.initialize()

    assert d._active is True
    assert engine.state == INITIAL
    assert ("reset", (), {}) in renderer.calls
    assert ("text_write", (TEXT_CENTER, "2 hours"), {}) in renderer.calls
    assert renderer.update_calls >= 1


def test_initialize_is_idempotent() -> None:
    d, *_ = _mk_display()
    d.initialize()
    calls_after_first = len(d._renderer.calls)

    d.initialize()
    assert len(d._renderer.calls) == calls_after_first


def test_deinitialize_resets_state() -> None:
    d, engine, renderer, *_ = _mk_display()
    d.initialize()
    d.deinitialize()

    assert d._active is False


def test_deinitialize_is_idempotent() -> None:
    d, *_ = _mk_display()
    d.initialize()
    d.deinitialize()
    active_after_first = d._active

    d.deinitialize()
    assert d._active == active_after_first


# ── button B: cycle duration ───────────────────────────────────────────


def test_on_button_b_cycles_duration_in_idle() -> None:
    d, engine, renderer, *_ = _mk_display()
    d.initialize()
    renderer.calls.clear()
    renderer.update_calls = 0

    d.on_button_b()
    assert engine.name == "4 hours"
    assert engine.total_sec == 4 * 3600
    assert ("text_write", (TEXT_CENTER, "4 hours"), {}) in renderer.calls
    assert renderer.update_calls == 1


def test_on_button_b_cycles_wrap_around() -> None:
    d, engine, *_ = _mk_display()
    d.initialize()
    for _ in range(len(DURATIONS)):
        d.on_button_b()
    assert engine.name == "2 hours"


def test_on_button_b_resets_in_running() -> None:
    d, engine, renderer, *_ = _mk_display()
    d.initialize()
    d.on_button_a()  # Start

    d.on_button_b()  # Should reset

    assert engine.state == INITIAL
    assert ("reset", (), {}) in renderer.calls


# ── button A: start countdown ─────────────────────────────────────────


def test_on_button_a_starts_countdown() -> None:
    d, engine, renderer, *_, clock = _mk_display()
    d.initialize()
    renderer.calls.clear()
    renderer.update_calls = 0

    d.on_button_a()

    assert engine.state == RUNNING
    assert ("reset", (), {}) in renderer.calls
    assert ("text_write", (TEXT_CENTER, "2 hours"), {}) in renderer.calls
    assert renderer.update_calls >= 1


def test_on_button_a_pauses_in_running() -> None:
    d, engine, renderer, *_ = _mk_display()
    d.initialize()
    d.on_button_a()  # Start
    d.on_button_a()  # Pause

    assert engine.state == PAUSED
    assert ("text_write", (TEXT_ABOVE_CENTER, "Paused"), {}) in renderer.calls


# ── button A/B in DONE state ──────────────────────────────────────────


def test_on_button_a_in_done_resets_to_initial() -> None:
    d, engine, renderer, *_, clock = _mk_display()
    d.initialize()
    d.on_button_a()  # Start
    clock[0] += engine.total_sec  # Advance past end
    engine._tick()  # Triggers DONE
    d._update_display()
    renderer.calls.clear()

    d.on_button_a()  # Reset

    assert engine.state == INITIAL
    assert ("reset", (), {}) in renderer.calls
    assert ("text_write", (TEXT_CENTER, "2 hours"), {}) in renderer.calls


def test_on_button_b_in_done_resets_to_initial() -> None:
    d, engine, renderer, *_, clock = _mk_display()
    d.initialize()
    d.on_button_a()  # Start
    clock[0] += engine.total_sec
    engine._tick()
    d._update_display()
    renderer.calls.clear()

    d.on_button_b()

    assert engine.state == INITIAL
    assert ("reset", (), {}) in renderer.calls


# ── elapsed / remaining time formatting ───────────────────────────────


def test_update_display_formats_elapsed_and_remaining() -> None:
    d, engine, renderer, *_, clock = _mk_display(now=10_000)
    d.initialize()
    d.on_button_a()  # Start

    clock[0] = 10_000 + 3661
    renderer.calls.clear()

    d._update_display()

    assert ("text_write", (TEXT_ABOVE_CENTER, "01:01:01"), {}) in renderer.calls
    assert renderer.update_calls >= 1


def test_update_display_does_nothing_in_idle() -> None:
    d, engine, renderer, *_ = _mk_display()
    d.initialize()
    renderer.calls.clear()
    renderer.update_calls = 0

    d._update_display()

    time_writes = [c for c in renderer.calls if c[0] == "text_write"]
    assert time_writes == []
    assert renderer.update_calls == 0


def test_update_display_detects_done_state() -> None:
    d, engine, renderer, *_, clock = _mk_display()
    d.initialize()
    d.on_button_a()
    clock[0] += engine.total_sec
    engine._tick()  # Engine transitions to DONE
    renderer.calls.clear()

    d._update_display()  # Display should detect DONE and draw it

    assert ("text_write", (TEXT_CENTER, engine.name), {}) in renderer.calls
    assert ("text_write", (TEXT_ABOVE_CENTER, "Done!"), {}) in renderer.calls
    assert ("text_write", (TEXT_BELOW_CENTER, "-00:00:00"), {}) in renderer.calls
    assert ("ring_clear_segments", (RING_SEGMENTS,), {}) in renderer.calls


# ── tick() ─────────────────────────────────────────────────────────────


def test_tick_updates_ring_segments_while_running(monkeypatch) -> None:
    tick_time = [0]
    monkeypatch.setattr(countdown_mod.time, "ticks_ms", lambda: tick_time[0])
    monkeypatch.setattr(countdown_mod.time, "ticks_diff", lambda a, b: a - b)

    d, engine, renderer, *_, clock = _mk_display(now=1000)
    d.initialize()
    d.on_button_a()  # Start 2-hour countdown

    # Advance clock partway (600s = 10 min)
    clock[0] = 1000 + 600
    renderer.calls.clear()
    renderer.update_calls = 0

    # Advance tick clock past 1s interval
    tick_time[0] = 1500
    d.tick()

    # expected cleared: 600 * 120 // 7200 = 10
    assert ("ring_clear_segments", (10,), {}) in renderer.calls
    assert renderer.update_calls >= 1


def test_tick_detects_done_state(monkeypatch) -> None:
    tick_time = [0]
    monkeypatch.setattr(countdown_mod.time, "ticks_ms", lambda: tick_time[0])
    monkeypatch.setattr(countdown_mod.time, "ticks_diff", lambda a, b: a - b)

    d, engine, renderer, *_, clock = _mk_display(now=1000)
    d.initialize()
    d.on_button_a()  # Start

    # Advance past end
    clock[0] = 1000 + engine.total_sec
    engine._tick()  # Transitions engine to DONE
    renderer.calls.clear()

    # Advance tick clock past 1s interval
    tick_time[0] = 1500
    d.tick()

    assert ("text_write", (TEXT_ABOVE_CENTER, "Done!"), {}) in renderer.calls
    assert ("ring_clear_segments", (RING_SEGMENTS,), {}) in renderer.calls


def test_tick_skipped_within_1s_interval(monkeypatch) -> None:
    tick_time = [0]
    monkeypatch.setattr(countdown_mod.time, "ticks_ms", lambda: tick_time[0])
    monkeypatch.setattr(countdown_mod.time, "ticks_diff", lambda a, b: a - b)

    d, engine, renderer, *_, clock = _mk_display(now=1000)
    d.initialize()
    d.on_button_a()  # Start
    renderer.calls.clear()
    renderer.update_calls = 0

    # tick_time hasn't advanced enough (still 0, diff < 1000)
    tick_time[0] = 500
    d.tick()

    assert renderer.update_calls == 0


# ── ring segment calculation ──────────────────────────────────────────


def test_update_display_advances_ring_segments() -> None:
    d, engine, renderer, *_, clock = _mk_display(now=1000)
    d.initialize()
    d.on_button_a()
    renderer.calls.clear()
    renderer.update_calls = 0

    # Advance 600s: expected = 600 * 120 // 7200 = 10 segments
    clock[0] = 1600
    d._update_display()

    assert ("ring_clear_segments", (10,), {}) in renderer.calls
    assert renderer.update_calls == 1


def test_countdown_with_changed_duration() -> None:
    d, engine, renderer, *_ = _mk_display()
    d.initialize()
    d.on_button_b()  # 4 hours
    d.on_button_b()  # 8 hours
    d.on_button_b()  # 5 min (wraps)

    d.on_button_a()

    assert engine.state == RUNNING
    assert engine.total_sec == 5 * 60


# ── pause / resume ────────────────────────────────────────────────────


def test_pause_shows_paused_text() -> None:
    d, engine, renderer, *_ = _mk_display()
    d.initialize()
    d.on_button_a()
    renderer.calls.clear()

    d.on_button_a()  # Pause

    assert ("text_write", (TEXT_ABOVE_CENTER, "Paused"), {}) in renderer.calls


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
    assert ("ring_clear_segments", (1,), {}) in renderer.calls
    assert renderer.update_calls >= 1


def test_button_b_resets_from_paused() -> None:
    d, engine, renderer, *_ = _mk_display()
    d.initialize()
    d.on_button_a()
    d.on_button_a()  # Pause

    d.on_button_b()  # Reset

    assert engine.state == INITIAL


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
    assert ("ring_clear_segments", (10,), {}) in renderer.calls
    assert ("text_write", (TEXT_CENTER, "2 hours"), {}) in renderer.calls
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
    assert ("text_write", (TEXT_CENTER, engine.name), {}) in renderer.calls
    assert ("text_write", (TEXT_ABOVE_CENTER, "Done!"), {}) in renderer.calls
    assert ("text_write", (TEXT_BELOW_CENTER, "-00:00:00"), {}) in renderer.calls
    assert ("ring_clear_segments", (RING_SEGMENTS,), {}) in renderer.calls


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
    assert ("ring_clear_segments", (1,), {}) in renderer.calls
    assert ("text_write", (TEXT_ABOVE_CENTER, "Paused"), {}) in renderer.calls
    # Remaining time shown
    remaining_writes = [c for c in renderer.calls if c[0] == "text_write" and c[1][0] == TEXT_BELOW_CENTER]
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
    elapsed_writes = [c for c in renderer.calls if c[0] == "text_write" and c[1][0] == TEXT_ABOVE_CENTER]
    assert len(elapsed_writes) >= 1
    assert elapsed_writes[-1][1][1] == "00:01:00"

    # Remaining time should be rendered
    remaining_writes = [c for c in renderer.calls if c[0] == "text_write" and c[1][0] == TEXT_BELOW_CENTER]
    assert len(remaining_writes) >= 1
    assert remaining_writes[-1][1][1] == "-00:04:00"

    # Display must have been updated
    assert renderer.update_calls >= 1
