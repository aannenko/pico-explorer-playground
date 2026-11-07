from micropython import const

FRESH = const(0)
STALE = const(1)
ERROR = const(2)
DISABLED = const(3)


class Stream:
    """Event source for one calendar row.

    Refreshable sources also supply ``events_iter_factory``, ``get_generation``
    (returning a monotonic counter that bumps when the snapshot changes) and
    ``get_status`` (returning one of the freshness codes above); static
    generators leave all three ``None``.
    """

    def __init__(
        self,
        events_iter,  # Iterator[Event]
        events_iter_factory=None,  # () -> Iterator[Event]
        get_generation=None,  # () -> int
        get_status=None,  # () -> int
    ) -> None:
        self.events_iter = events_iter
        self.events_iter_factory = events_iter_factory
        self.get_generation = get_generation
        self.get_status = get_status
