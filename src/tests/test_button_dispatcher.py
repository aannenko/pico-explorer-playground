from __future__ import annotations

import pytest

from conftest import TICKS_PERIOD_MS
from services.button_dispatcher import ButtonDispatcher


class FakePin:
    """machine.Pin, active-low; ``set_level`` runs the armed IRQ handler as an edge would."""

    def __init__(self, level: int = 1) -> None:
        self.level = level
        self.handler = None  # (FakePin) -> None

    def value(self) -> int:
        return self.level

    def irq(self, handler=None, trigger=None, hard=False) -> None:
        self.handler = handler

    def set_level(self, level: int) -> None:
        self.level = level
        self.handler(self)


class EdgeOnArmPin(FakePin):
    def irq(self, handler=None, trigger=None, hard=False) -> None:
        super().irq(handler, trigger, hard)
        handler(self)


class FakeQueue:
    """micropython.schedule that holds callbacks until ``run()``, raising like a full queue while ``full``."""

    def __init__(self) -> None:
        self.full = False
        self.scheduled_count = 0
        self._calls: list[tuple] = []

    def schedule(self, callback, arg: int) -> None:
        if self.full:
            raise RuntimeError("schedule queue full")
        self.scheduled_count += 1
        self._calls.append((callback, arg))

    def run(self) -> None:
        calls, self._calls = self._calls, []
        for callback, arg in calls:
            callback(arg)


def _build(ticks: list[int], pin_count: int = 1, on_press=None):
    """Return ``(dispatcher, queue, pins, presses)``; ``presses`` records each callback's button index."""
    queue = FakeQueue()
    dispatcher = ButtonDispatcher(schedule=queue.schedule)
    pins = [FakePin() for _ in range(pin_count)]
    presses: list[int] = []
    for index in range(pin_count):
        dispatcher.add(pins[index], on_press or (lambda _, index=index: presses.append(index)))
    ticks[0] += 1_000
    return dispatcher, queue, pins, presses


def _dispatch(dispatcher: ButtonDispatcher, queue: FakeQueue) -> None:
    dispatcher.dispatch_pending()
    queue.run()


def _tap(ticks: list[int], pin: FakePin) -> None:
    pin.set_level(0)
    ticks[0] += 100
    pin.set_level(1)
    ticks[0] += 100


def test_press_runs_its_callback_with_0_once(fake_ticks) -> None:
    args: list[int] = []
    dispatcher, queue, pins, _ = _build(fake_ticks, on_press=args.append)

    pins[0].set_level(0)
    _dispatch(dispatcher, queue)
    assert args == [0]

    fake_ticks[0] += 100
    pins[0].set_level(1)
    _dispatch(dispatcher, queue)
    assert args == [0]


def test_contact_bounce_on_press_and_release_counts_one_press(fake_ticks) -> None:
    dispatcher, queue, pins, presses = _build(fake_ticks)

    for _ in range(2):
        for level in (0, 1, 0):
            pins[0].set_level(level)
            fake_ticks[0] += 1
        fake_ticks[0] += 100
        for level in (1, 0, 1):
            pins[0].set_level(level)
            fake_ticks[0] += 1
        fake_ticks[0] += 100
        _dispatch(dispatcher, queue)

    assert presses == [0, 0]


def test_release_whose_bounce_edges_arrive_together_is_not_a_press(fake_ticks) -> None:
    dispatcher, queue, pins, presses = _build(fake_ticks)
    pins[0].set_level(0)
    _dispatch(dispatcher, queue)
    fake_ticks[0] += 500

    # One IRQ call for a release and a bounce back low, then the settled release.
    pins[0].set_level(0)
    fake_ticks[0] += 1
    pins[0].set_level(1)
    _dispatch(dispatcher, queue)

    assert presses == [0]


def test_button_held_at_startup_is_not_pressed_by_its_release(fake_ticks) -> None:
    queue = FakeQueue()
    dispatcher = ButtonDispatcher(schedule=queue.schedule)
    pin = FakePin(level=0)
    presses: list[int] = []
    dispatcher.add(pin, presses.append)
    fake_ticks[0] += 1_000

    pin.set_level(1)
    _dispatch(dispatcher, queue)

    assert presses == []


def test_press_made_while_a_press_callback_runs_is_dropped(fake_ticks) -> None:
    pins: list[FakePin] = []
    presses: list[int] = []

    def on_press_a(_: int) -> None:
        presses.append(0)
        fake_ticks[0] += 100
        _tap(fake_ticks, pins[1])

    queue = FakeQueue()
    dispatcher = ButtonDispatcher(schedule=queue.schedule)
    pins.extend([FakePin(), FakePin()])
    dispatcher.add(pins[0], on_press_a)
    dispatcher.add(pins[1], lambda _: presses.append(1))
    fake_ticks[0] += 1_000

    _tap(fake_ticks, pins[0])
    _dispatch(dispatcher, queue)
    _dispatch(dispatcher, queue)

    assert presses == [0]


def test_presses_count_again_after_a_press_callback_raises(fake_ticks) -> None:
    calls: list[int] = []

    def on_press(_: int) -> None:
        calls.append(0)
        if len(calls) == 1:
            raise ValueError("handler failed")

    dispatcher, queue, pins, _ = _build(fake_ticks, on_press=on_press)
    _tap(fake_ticks, pins[0])
    with pytest.raises(ValueError):
        _dispatch(dispatcher, queue)

    _tap(fake_ticks, pins[0])
    _dispatch(dispatcher, queue)

    assert calls == [0, 0]


def test_presses_while_the_main_thread_is_busy_run_afterwards_collapsed(fake_ticks) -> None:
    dispatcher, queue, pins, presses = _build(fake_ticks)

    _tap(fake_ticks, pins[0])
    _tap(fake_ticks, pins[0])
    _dispatch(dispatcher, queue)
    _dispatch(dispatcher, queue)

    assert presses == [0]


def test_press_while_its_run_is_queued_collapses_into_it(fake_ticks) -> None:
    dispatcher, queue, pins, presses = _build(fake_ticks)

    _tap(fake_ticks, pins[0])
    dispatcher.dispatch_pending()
    _tap(fake_ticks, pins[0])
    dispatcher.dispatch_pending()
    queue.run()
    _dispatch(dispatcher, queue)

    assert presses == [0]
    assert queue.scheduled_count == 1


def test_different_buttons_run_in_press_order(fake_ticks) -> None:
    dispatcher, queue, pins, presses = _build(fake_ticks, pin_count=3)

    _tap(fake_ticks, pins[2])
    _tap(fake_ticks, pins[0])
    _dispatch(dispatcher, queue)
    _dispatch(dispatcher, queue)
    _dispatch(dispatcher, queue)

    assert presses == [2, 0]


def test_press_while_another_buttons_run_is_queued_runs_afterwards(fake_ticks) -> None:
    dispatcher, queue, pins, presses = _build(fake_ticks, pin_count=2)

    _tap(fake_ticks, pins[0])
    dispatcher.dispatch_pending()
    _tap(fake_ticks, pins[1])
    queue.run()
    _dispatch(dispatcher, queue)

    assert presses == [0, 1]


def test_collapsed_presses_keep_their_first_press_order(fake_ticks) -> None:
    dispatcher, queue, pins, presses = _build(fake_ticks, pin_count=2)

    _tap(fake_ticks, pins[0])
    _tap(fake_ticks, pins[1])
    _tap(fake_ticks, pins[0])
    _dispatch(dispatcher, queue)
    _dispatch(dispatcher, queue)

    assert presses == [0, 1]


def test_press_stays_pending_while_the_schedule_queue_is_full(fake_ticks) -> None:
    dispatcher, queue, pins, presses = _build(fake_ticks)
    queue.full = True
    _tap(fake_ticks, pins[0])
    _dispatch(dispatcher, queue)

    queue.full = False
    _dispatch(dispatcher, queue)

    assert presses == [0]


def test_run_starting_inside_schedule_leaves_later_presses_dispatchable(fake_ticks) -> None:
    presses: list[int] = []
    dispatcher = ButtonDispatcher(schedule=lambda callback, arg: callback(arg))
    pin = FakePin()
    dispatcher.add(pin, presses.append)
    fake_ticks[0] += 1_000

    _tap(fake_ticks, pin)
    dispatcher.dispatch_pending()
    _tap(fake_ticks, pin)
    dispatcher.dispatch_pending()

    assert presses == [0, 0]


def test_release_bounce_across_a_ticks_rollover_is_not_a_press(wrapping_ticks) -> None:
    wrapping_ticks[0] = TICKS_PERIOD_MS - 2_000
    dispatcher, queue, pins, presses = _build(wrapping_ticks)

    pins[0].set_level(0)
    _dispatch(dispatcher, queue)
    wrapping_ticks[0] += 995
    pins[0].set_level(1)
    wrapping_ticks[0] += 10
    pins[0].set_level(0)
    wrapping_ticks[0] += 1
    pins[0].set_level(1)
    _dispatch(dispatcher, queue)

    assert presses == [0]


def test_first_press_after_half_a_ticks_period_idle_counts(wrapping_ticks) -> None:
    dispatcher, queue, pins, presses = _build(wrapping_ticks)
    wrapping_ticks[0] += TICKS_PERIOD_MS // 2 + 1_000

    pins[0].set_level(0)
    _dispatch(dispatcher, queue)

    assert presses == [0]


def test_irq_and_main_thread_never_add_attributes(fake_ticks) -> None:
    pins: list[FakePin] = []
    presses: list[int] = []

    def on_press_a(_: int) -> None:
        presses.append(0)
        _tap(fake_ticks, pins[1])

    queue = FakeQueue()
    dispatcher = ButtonDispatcher(schedule=queue.schedule)
    pins.extend([FakePin(), FakePin()])
    dispatcher.add(pins[0], on_press_a)
    dispatcher.add(pins[1], lambda _: presses.append(1))
    objects = [dispatcher, *dispatcher._buttons]
    names_before = [set(vars(obj)) for obj in objects]
    fake_ticks[0] += 1_000

    pins[0].set_level(0)
    pins[0].set_level(1)
    fake_ticks[0] += 1
    pins[0].set_level(0)
    fake_ticks[0] += 100
    pins[0].set_level(1)
    queue.full = True
    dispatcher.dispatch_pending()
    queue.full = False
    _dispatch(dispatcher, queue)
    _tap(fake_ticks, pins[1])
    _dispatch(dispatcher, queue)

    assert presses == [0, 1]
    assert [set(vars(obj)) for obj in objects] == names_before


def test_edge_at_arming_finds_every_attribute(fake_ticks) -> None:
    queue = FakeQueue()
    dispatcher = ButtonDispatcher(schedule=queue.schedule)
    presses: list[int] = []

    dispatcher.add(EdgeOnArmPin(), presses.append)
    _dispatch(dispatcher, queue)

    assert presses == []
