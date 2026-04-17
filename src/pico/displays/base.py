import time


class Display:
    """Base class for display views managed by ``DisplayManager``.

    Every method has a no-op default so subclasses only override what they
    need.  ``DisplayManager`` calls ``initialize`` / ``deinitialize`` on view
    switch, ``tick`` every scheduler tick, and ``on_button_a`` /
    ``on_button_b`` when the A/B hardware buttons are pressed while this
    view is active.
    """

    def initialize(self) -> None:
        pass

    def deinitialize(self) -> None:
        pass

    def tick(self) -> None:
        pass

    def on_button_a(self) -> None:
        pass

    def on_button_b(self) -> None:
        pass


class RefreshGate:
    """Throttle helper for displays that redraw on a coarse interval.

    Use from within ``tick()``::

        if not self._gate.ready():
            return
        self._redraw()

    ``reset()`` re-arms the gate (useful on ``initialize()`` so the next
    ``ready()`` call only fires after a full interval rather than
    immediately).
    """

    def __init__(self, period_ms: int) -> None:
        self._period_ms = period_ms
        self._last = time.ticks_ms()

    def reset(self) -> None:
        self._last = time.ticks_ms()

    def ready(self) -> bool:
        now = time.ticks_ms()
        diff = time.ticks_diff(now, self._last)
        if diff < self._period_ms:
            return False
        # Advance the anchor by a full period so repeated jitter doesn't
        # slide future fires forward.  If we somehow fell more than one
        # period behind, snap to *now* to avoid a catch-up burst.
        if diff >= 2 * self._period_ms:
            self._last = now
        else:
            self._last = time.ticks_add(self._last, self._period_ms)
        return True
