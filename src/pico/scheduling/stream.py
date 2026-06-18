"""Hardware-agnostic stream descriptor used by the calendar display.

A ``Stream`` bundles an event iterator for one calendar row.  Bar colors
are not carried here — each ``Event`` sets a ``color_index`` instead.
Keeping streams free of pen/RGB references lets them be defined in config
or produced remotely without PicoGraphics references.

Refreshable (network-backed) sources additionally supply ``events_fn``
(a fresh-iterator factory), ``generation_fn`` (a monotonic counter that
bumps when the snapshot changes) and ``status_fn`` (freshness, rendered
as a row glyph).  Static generators leave all three ``None``.
"""

from micropython import const

# Stream freshness, returned by ``status_fn`` and rendered as a row glyph.
FRESH = const(0)
STALE = const(1)
ERROR = const(2)
DISABLED = const(3)


class Stream:
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
