class Stream:
    """Event source for one calendar stream.

    Refreshable sources also supply ``events_iter_factory`` and ``get_generation``
    (returning a monotonic counter that bumps when the snapshot changes); static
    generators leave both ``None``.
    """

    def __init__(
        self,
        events_iter,  # Iterator[Event]
        events_iter_factory=None,  # () -> Iterator[Event]
        get_generation=None,  # () -> int
    ) -> None:
        self.events_iter = events_iter
        self.events_iter_factory = events_iter_factory
        self.get_generation = get_generation
