from micropython import const

FRESH = const(0)
STALE = const(1)
ERROR = const(2)
DISABLED = const(3)


class Stream:
    """Event source for one calendar row.

    Refreshable sources also supply ``events_fn`` (a fresh-iterator factory),
    ``generation_fn`` (a monotonic counter that bumps when the snapshot changes)
    and ``status_fn`` (returning one of the freshness codes above); static
    generators leave all three ``None``.
    """

    def __init__(
        self,
        events_iter,  # Iterator[Event]
        events_fn=None,  # () -> Iterator[Event]
        generation_fn=None,  # () -> int
        status_fn=None,  # () -> int
    ) -> None:
        self.events_iter = events_iter
        self.events_fn = events_fn
        self.generation_fn = generation_fn
        self.status_fn = status_fn
