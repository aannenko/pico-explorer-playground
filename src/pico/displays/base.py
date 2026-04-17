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
