"""Hardware-agnostic stream descriptor used by the calendar display.

A ``Stream`` bundles an event iterator with the RGB colors its bars
should be drawn in.  ``app.py`` converts each Stream to an
``EventWindow`` by mapping the RGB pairs to PicoGraphics pens at wiring
time.

Keeping streams RGB-based (rather than pen-based) means stream
definitions can live in config files or, eventually, be produced by a
web configuration server without carrying PicoGraphics references.
"""


class Stream:
    def __init__(
        self,
        events_iter,  # Iterator[Event]
        color_a: tuple[int, int, int],
        color_b: tuple[int, int, int],
    ) -> None:
        self.events_iter = events_iter
        self.color_a = color_a
        self.color_b = color_b
