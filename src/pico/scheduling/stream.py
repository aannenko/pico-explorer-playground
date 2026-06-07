"""Hardware-agnostic stream descriptor used by the calendar display.

A ``Stream`` bundles an event iterator for one calendar row.  Bar colors
are not carried here — each ``Event`` sets a ``color_index`` instead.
Keeping streams free of pen/RGB references lets them be defined in config
or produced remotely without PicoGraphics references.
"""


class Stream:
    def __init__(
        self,
        events_iter,  # Iterator[Event]
    ) -> None:
        self.events_iter = events_iter
