class Display:
    """Base class for a view: one full screen of the app.

    An ``on_button_a`` / ``on_button_b`` override must redraw what the press
    changed before returning: the press restarts the view's redraw cadence, so
    the next scheduled render is a full period away.
    """

    refresh_period_ms = 1000  # 0 renders every scheduler tick

    def initialize(self) -> None:
        """Enter the view; must produce a complete first render."""
        pass

    def deinitialize(self) -> None:
        pass

    def render(self) -> None:
        """Redraw whatever has changed since the last draw."""
        pass

    def on_button_a(self) -> None:
        pass

    def on_button_b(self) -> None:
        pass


class RefreshGate:
    """Tick-count throttle for a view's redraw cadence.

    A ``period_ticks`` below 1 counts as 1.
    """

    def __init__(self, period_ticks: int) -> None:
        self._period = period_ticks if period_ticks > 1 else 1
        self._count = 0

    def reset(self) -> None:
        self._count = 0

    def ready(self) -> bool:
        """Count one tick; return True if it completes the period."""
        self._count += 1
        if self._count >= self._period:
            self._count = 0
            return True
        return False
