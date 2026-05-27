class Display:
    """Base class for display views managed by ``DisplayManager``.

    ``refresh_period_ms`` (class attribute) sets the redraw cadence;
    the manager converts it to scheduler ticks.  Use ``0`` to render
    every scheduler tick.  ``initialize`` must produce a complete first
    render; ``render`` then updates whatever changed.  ``on_button_a``
    / ``on_button_b`` fire when A/B are pressed while this view is
    active.
    """

    refresh_period_ms: int = 1000

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
