class DisplayManager:
    def __init__(self, displays: list, initializers: list) -> None:
        """
        Args:
            displays: list of display objects with initialize/deinitialize.
            initializers: list of callables, each returning a tuple of args
                          to pass to the corresponding display's initialize().
        """
        self._displays = displays
        self._initializers = initializers
        self._current = 0

    def initialize_current(self) -> None:
        args = self._initializers[self._current]()
        self._displays[self._current].initialize(*args)

    def cycle(self) -> None:
        self._displays[self._current].deinitialize()
        self._current = (self._current + 1) % len(self._displays)
        self.initialize_current()
