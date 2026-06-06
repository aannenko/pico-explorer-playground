"""Hardware-agnostic stream descriptor used by the calendar display.

A ``Stream`` bundles an event iterator with the RGB ``palette`` its bars
should be drawn in.  Each palette entry is either a single RGB triple or a
``(main_rgb, alt_rgb)`` pair; an event's ``color_index`` selects the entry.
``app.py`` converts the palette to ``(main_pen, alt_pen)`` PicoGraphics pen
pairs at wiring time (``displays.palette.build_stream_pen_pairs``).

Keeping streams RGB-based (rather than pen-based) means stream
definitions can live in config files or, eventually, be produced by a
web configuration server without carrying PicoGraphics references.
"""


class Stream:
    def __init__(
        self,
        events_iter,  # Iterator[Event]
        palette: tuple,  # tuple of RGB triples and/or (main_rgb, alt_rgb) pairs
    ) -> None:
        self.events_iter = events_iter
        self.palette = palette
