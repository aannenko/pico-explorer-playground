from displays.base import Display, RefreshGate


class DisplayManager:
    """View carousel: switches between views and drives the current one."""

    def __init__(self, displays: list[Display], scheduler_period_ms: int) -> None:
        self._displays = displays
        self._scheduler_period_ms = scheduler_period_ms
        self._current = 0
        self._gate = self._build_gate(displays[0])

        # Refs compatible with micropython.schedule(callback, arg)
        self.next_ref = self._do_next
        self.previous_ref = self._do_previous
        self.on_button_a_ref = self._do_on_button_a
        self.on_button_b_ref = self._do_on_button_b

    def _build_gate(self, display: Display) -> RefreshGate | None:
        period_ms = display.refresh_period_ms
        if period_ms <= 0:
            return None
        ticks = round(period_ms / self._scheduler_period_ms)
        return RefreshGate(ticks if ticks > 1 else 1)

    def initialize_current(self) -> None:
        """Enter the current view with a fresh redraw cadence."""
        self._gate = self._build_gate(self._displays[self._current])
        self._displays[self._current].initialize()

    def _deinitialize_current(self) -> None:
        self._displays[self._current].deinitialize()

    def next(self) -> None:
        """Leave the current view and enter the next, wrapping around."""
        self._deinitialize_current()
        self._current = (self._current + 1) % len(self._displays)
        self.initialize_current()

    def previous(self) -> None:
        """Leave the current view and enter the previous, wrapping around."""
        self._deinitialize_current()
        self._current = (self._current - 1) % len(self._displays)
        self.initialize_current()

    def tick(self) -> None:
        """Render the current view when due; call once per ``scheduler_period_ms``."""
        if self._gate is None or self._gate.ready():
            self._displays[self._current].render()

    def _do_next(self, _: int) -> None:
        self.next()

    def _do_previous(self, _: int) -> None:
        self.previous()

    def _do_on_button_a(self, _: int) -> None:
        display = self._displays[self._current]
        display.on_button_a()
        # Overridden handlers must redraw inline; restart their cadence.
        # Stray presses on passive views must not delay the next redraw.
        if self._gate is not None and type(display).on_button_a is not Display.on_button_a:
            self._gate.reset()

    def _do_on_button_b(self, _: int) -> None:
        display = self._displays[self._current]
        display.on_button_b()
        if self._gate is not None and type(display).on_button_b is not Display.on_button_b:
            self._gate.reset()
