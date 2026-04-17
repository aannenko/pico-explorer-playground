from displays.base import Display, RefreshGate


class DisplayManager:
    def __init__(self, displays: list[Display], scheduler_period_ms: int) -> None:
        self._displays: list[Display] = displays
        self._scheduler_period_ms: int = scheduler_period_ms
        self._current: int = 0
        # Only one view is active at a time, so one gate is enough.  It's
        # rebuilt on every view switch to match the active display's
        # ``refresh_period_ms``.  ``None`` means "render every tick"
        # (display opted out of throttling via refresh_period_ms=0).
        self._gate = self._build_gate(displays[0])  # RefreshGate | None

        # Refs compatible with micropython.schedule(callback, arg)
        self.next_ref = self._do_next
        self.previous_ref = self._do_previous
        self.on_button_a_ref = self._do_on_button_a
        self.on_button_b_ref = self._do_on_button_b

    def _build_gate(self, display: Display):  # RefreshGate | None
        period_ms = display.refresh_period_ms
        if period_ms <= 0:
            return None
        ticks = round(period_ms / self._scheduler_period_ms)
        return RefreshGate(ticks if ticks > 1 else 1)

    def initialize_current(self) -> None:
        self._gate = self._build_gate(self._displays[self._current])
        self._displays[self._current].initialize()

    def _deinitialize_current(self) -> None:
        self._displays[self._current].deinitialize()

    def next(self) -> None:
        self._deinitialize_current()
        self._current = (self._current + 1) % len(self._displays)
        self.initialize_current()

    def previous(self) -> None:
        self._deinitialize_current()
        self._current = (self._current - 1) % len(self._displays)
        self.initialize_current()

    def tick(self) -> None:
        if self._gate is None or self._gate.ready():
            self._displays[self._current].render()

    def _do_next(self, _: int) -> None:
        self.next()

    def _do_previous(self, _: int) -> None:
        self.previous()

    def _do_on_button_a(self, _: int) -> None:
        self._displays[self._current].on_button_a()
        # Button presses typically redraw inline; re-anchor the cadence
        # so the next gated render is a full period away.
        if self._gate is not None:
            self._gate.reset()

    def _do_on_button_b(self, _: int) -> None:
        self._displays[self._current].on_button_b()
        if self._gate is not None:
            self._gate.reset()
