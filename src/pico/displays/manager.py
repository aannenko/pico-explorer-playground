class DisplayManager:
    def __init__(self, displays: list) -> None:
        self._displays: list = displays
        self._current: int = 0

        # Refs compatible with micropython.schedule(callback, arg)
        self.next_ref = self._do_next
        self.previous_ref = self._do_previous
        self.on_button_a_ref = self._do_on_button_a
        self.on_button_b_ref = self._do_on_button_b

    def initialize_current(self) -> None:
        self._displays[self._current].initialize()

    def next(self) -> None:
        self._displays[self._current].deinitialize()
        self._current = (self._current + 1) % len(self._displays)
        self.initialize_current()

    def previous(self) -> None:
        self._displays[self._current].deinitialize()
        self._current = (self._current - 1) % len(self._displays)
        self.initialize_current()

    def _do_next(self, _: int) -> None:
        self.next()

    def _do_previous(self, _: int) -> None:
        self.previous()

    def _do_on_button_a(self, _: int) -> None:
        display = self._displays[self._current]
        if hasattr(display, 'on_button_a'):
            display.on_button_a()

    def _do_on_button_b(self, _: int) -> None:
        display = self._displays[self._current]
        if hasattr(display, 'on_button_b'):
            display.on_button_b()
