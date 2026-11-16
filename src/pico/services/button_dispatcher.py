import time

import micropython
from machine import Pin
from micropython import const


# A falling edge counts as a press only after this long without edges: shorter
# gaps are contact bounce, on press and on release.
_QUIET_BEFORE_PRESS_MS = const(30)


class ButtonDispatcher:
    """Runs button-press callbacks on the main thread, from presses latched by hard IRQs.

    A press made while a press callback runs is dropped. A press made while
    other work blocks the main thread is kept and runs once it returns. Presses
    of one button awaiting their run collapse into one; different buttons run
    in the order they were pressed.
    """

    def __init__(self, schedule) -> None:  # schedule: (callback, arg) -> None
        self._schedule = schedule
        self._buttons: list[_Button] = []
        self._pending = False
        self._busy = False
        self._run_ref = self._run

    def add(self, pin: Pin, on_press) -> None:  # on_press: (int) -> None
        """Watch active-low ``pin``; each press calls ``on_press(0)``."""
        self._buttons.append(_Button(pin, on_press, self))

    def dispatch_pending(self) -> None:
        """Schedule a run of the oldest pending press; call it regularly from the main loop.

        A full schedule queue leaves the press pending for the next call.
        """
        if self._pending:
            return
        buttons = self._buttons
        for index in range(len(buttons)):
            if buttons[index]._pending:
                # Set before scheduling: the run can start at the first branch
                # after schedule() returns, and must find it set to clear it.
                self._pending = True
                try:
                    self._schedule(self._run_ref, 0)
                except RuntimeError:
                    self._pending = False
                return

    def _run(self, _: int) -> None:
        self._pending = False
        # The IRQs ignore presses while _busy, so claiming one below can't race them.
        self._busy = True
        try:
            buttons = self._buttons
            first = None
            for index in range(len(buttons)):
                button = buttons[index]
                if button._pending and (first is None or time.ticks_diff(button.press_ms, first.press_ms) < 0):
                    first = button
            if first is not None:
                first._pending = False
                first.on_press(0)
        finally:
            self._busy = False


class _Button:
    """One active-low button whose hard IRQ latches presses for a ``ButtonDispatcher``.

    Warning: the IRQ runs with the heap locked, so every attribute of this
    object and of its dispatcher exists before ``pin.irq(...)`` arms it, and
    none is added later: adding one allocates, and a lookup racing the resize
    can miss. Either raises, and any exception there disables this pin's IRQ
    until the next reset (a soft reset will do).
    """

    def __init__(self, pin: Pin, on_press, dispatcher: ButtonDispatcher) -> None:  # on_press: (int) -> None
        self.on_press = on_press
        self._dispatcher = dispatcher
        self._pending = False
        self.press_ms = 0  # time of the oldest press awaiting its run; valid while _pending
        self.level = pin.value()  # 1 = released
        self._last_edge_ms = time.ticks_ms()
        pin.irq(handler=self._on_edge, trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, hard=True)

    # Native, not bytecode: bytecode checks for a pending Ctrl-C at every
    # branch, which would raise it in here and disable this pin's IRQ.
    @micropython.native
    def _on_edge(self, pin: Pin) -> None:
        now_ms = time.ticks_ms()
        elapsed_ms = time.ticks_diff(now_ms, self._last_edge_ms)
        self._last_edge_ms = now_ms
        level = self.level
        # After a quiet gap this holds the settled level: a change after this
        # read latches another edge, so a bounce burst's last call reads its final level.
        self.level = pin.value()
        # A negative gap means over half a ticks period (about 6 days) passed: quiet.
        if not level or 0 <= elapsed_ms < _QUIET_BEFORE_PRESS_MS:
            return
        if self._dispatcher._busy or self._pending:
            return
        self.press_ms = now_ms
        self._pending = True
