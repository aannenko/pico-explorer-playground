from __future__ import annotations

import pytest

from services.countdown_timer import (
    CountdownTimer,
    INITIAL,
    RUNNING,
    PAUSED,
    DONE,
)


def _mk_engine(**overrides):
    on_done_calls: list[int] = []
    on_configure_calls: list[int] = []
    defaults = dict(
        on_done=lambda: on_done_calls.append(1),
        on_configure=lambda: on_configure_calls.append(1),
        get_time=lambda: 1000,
    )
    defaults.update(overrides)
    e = CountdownTimer(**defaults)
    return e, on_done_calls, on_configure_calls


def _engine_in(state: int) -> tuple[CountdownTimer, list[int], list[int]]:
    """A 5-minute countdown driven to ``state``, started at 1000 s unless INITIAL, with its callback records cleared."""
    e, on_done_calls, on_configure_calls = _mk_engine()
    e.configure("5 min", 300)
    if state != INITIAL:
        e.start()
    if state == PAUSED:
        e.pause()
    elif state == DONE:
        e._get_time = lambda: 1000 + 300
        e._tick()
    assert e.state == state
    on_done_calls.clear()
    on_configure_calls.clear()
    return e, on_done_calls, on_configure_calls


# ── initial state ──────────────────────────────────────────────────────


def test_initial_state() -> None:
    e, *_ = _mk_engine()
    assert e.state == INITIAL
    assert e.label == ""
    assert e.total_sec == 0
    assert e.elapsed_sec == 0
    assert e.remaining_sec == 0


# ── configure ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", [INITIAL, RUNNING, PAUSED, DONE], ids=["initial", "running", "paused", "done"])
def test_configure_from_any_state_sets_up_the_new_countdown_and_calls_on_configure(state: int) -> None:
    e, _, on_configure_calls = _engine_in(state)
    e.configure("10 min", 600)
    assert e.state == INITIAL
    assert e.label == "10 min"
    assert e.total_sec == 600
    assert len(on_configure_calls) == 1


# ── start ──────────────────────────────────────────────────────────────


def test_start_counts_down_from_the_total_with_the_clock() -> None:
    e, *_ = _mk_engine()
    e.configure("2 hours", 7200)
    e.start()

    assert e.state == RUNNING
    assert e.elapsed_sec == 0
    assert e.remaining_sec == 7200

    e._get_time = lambda: 1060

    assert e.elapsed_sec == 60
    assert e.remaining_sec == 7200 - 60


def test_start_ignored_when_not_initial() -> None:
    e, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.start()
    e.start()  # should be ignored
    assert e.state == RUNNING


@pytest.mark.parametrize("total_sec", [0, -1])
def test_start_rejected_without_a_positive_total_sec(total_sec: int) -> None:
    e, *_ = _mk_engine()
    e.configure("invalid", total_sec)
    e.start()
    assert e.state == INITIAL


# ── pause / resume ────────────────────────────────────────────────────


def test_pause_freezes_the_elapsed_and_remaining_time() -> None:
    now = 1000
    e, *_ = _mk_engine(get_time=lambda: now)
    e.configure("2 hours", 7200)
    e.start()

    now = 1060
    e._get_time = lambda: now
    e.pause()
    assert e.state == PAUSED

    now = 9999
    e._get_time = lambda: now

    assert e.elapsed_sec == 60
    assert e.remaining_sec == 7200 - 60


def test_pause_ignored_when_not_running() -> None:
    e, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.pause()
    assert e.state == INITIAL


def test_resume_recalculates_timestamps() -> None:
    now = 1000
    e, *_ = _mk_engine(get_time=lambda: now)
    e.configure("2 hours", 7200)
    e.start()

    now = 1060
    e._get_time = lambda: now
    e.pause()

    now = 2000
    e._get_time = lambda: now
    e.resume()

    assert e.state == RUNNING
    remaining = 7200 - 60
    assert e.remaining_sec == remaining
    assert e.elapsed_sec == 60


def test_resume_ignored_when_not_paused() -> None:
    e, *_ = _mk_engine()
    e.configure("5 min", 300)
    e.resume()
    assert e.state == INITIAL


# ── reset ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", [INITIAL, RUNNING, PAUSED, DONE], ids=["initial", "running", "paused", "done"])
def test_reset_from_any_state_discards_progress_and_keeps_the_countdown(state: int) -> None:
    e, _, on_configure_calls = _engine_in(state)
    e.reset()

    assert e.state == INITIAL
    assert e.label == "5 min"
    assert e.total_sec == 300
    assert e.elapsed_sec == 0
    assert e.remaining_sec == 0
    assert len(on_configure_calls) == 1


# ── tick ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("elapsed_sec", [300, 301], ids=["at-end", "past-end"])
def test_tick_finishes_a_running_countdown_at_or_past_its_end(elapsed_sec: int) -> None:
    e, on_done_calls, _ = _engine_in(RUNNING)

    e._get_time = lambda: 1000 + elapsed_sec
    e._tick()

    assert e.state == DONE
    assert len(on_done_calls) == 1
    assert e.elapsed_sec == 300
    assert e.remaining_sec == 0


@pytest.mark.parametrize(
    "state, elapsed_sec",
    [(INITIAL, 0), (RUNNING, 100), (PAUSED, 301)],
    ids=["initial", "running-before-end", "paused-past-end"],
)
def test_tick_does_nothing_unless_running_at_or_past_the_end(state: int, elapsed_sec: int) -> None:
    e, on_done_calls, _ = _engine_in(state)

    e._get_time = lambda: 1000 + elapsed_sec
    e._tick()

    assert e.state == state
    assert len(on_done_calls) == 0
