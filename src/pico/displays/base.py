class Display:
    """Base class for display views managed by ``DisplayManager``.

    Subclasses declare their redraw cadence via the ``refresh_period_ms``
    class attribute; the manager converts this to scheduler ticks and
    calls ``render()`` on the correct cadence.  A value of ``0`` means
    "I'm fine rendering on every scheduler tick" — no throttling.

    ``initialize`` / ``deinitialize`` fire on view switch.  ``initialize``
    must produce a complete first render; ``render`` then updates
    whatever state has changed.  ``on_button_a`` / ``on_button_b`` fire
    when the A/B hardware buttons are pressed while this view is active.
    Every method has a no-op default so subclasses only override what
    they need.
    """

    refresh_period_ms: int = 0

    def initialize(self) -> None:
        pass

    def deinitialize(self) -> None:
        pass

    def render(self) -> None:
        pass

    def on_button_a(self) -> None:
        pass

    def on_button_b(self) -> None:
        pass


class RefreshGate:
    """Tick-count throttle used by ``DisplayManager``.

    Fires every ``period_ticks`` calls to ``ready()``.  A period of ``1``
    (or less) fires every call.  No wall-clock involvement — the manager
    converts the display's ``refresh_period_ms`` to ticks using the
    scheduler period, and calls ``ready()`` once per scheduler tick.
    """

    def __init__(self, period_ticks: int) -> None:
        self._period = period_ticks if period_ticks > 1 else 1
        self._count = 0

    def reset(self) -> None:
        self._count = 0

    def ready(self) -> bool:
        self._count += 1
        if self._count >= self._period:
            self._count = 0
            return True
        return False
