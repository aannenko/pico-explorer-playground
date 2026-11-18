"""Building calendar event runs from per-hour warnings."""

from micropython import const

from scheduling.event import create_event, Event

_SEC_PER_HOUR = const(3600)


def level(value: float | None, thresholds: tuple[float, float, float]) -> int:
    """Warning level of ``value``: how many of the ascending ``thresholds`` it reaches.

    ``None``, a missing value, is level 0.
    """
    if value is None:
        return 0
    reached = 0
    for threshold in thresholds:
        if value >= threshold:
            reached += 1
    return reached


class RunBuilder:
    """Joins hourly warnings into events: adjacent hours with one label form one event, coloured by the highest of
    their levels.

    Hours are UTC and must be added in ascending order.  ``level_colors[level - 1]`` is a level's ``color_index``.
    Events over by ``now_utc`` are dropped, and hours after the first ``max_events`` events that aren't are ignored.
    """

    def __init__(
        self,
        level_colors: tuple[int, int, int],
        max_events: int,
        now_utc: int,
    ) -> None:
        self._level_colors = level_colors
        self._max_events = max_events
        self._now_utc = now_utc
        self._events: list[Event] = []
        self._label: str | None = None
        self._level = 0
        self._start_utc = 0
        self._end_utc = 0

    def add(self, utc_epoch: int, label: str | None, level: int) -> None:
        """Add the hour starting at ``utc_epoch``; level 0 or a ``None`` label means no warning that hour."""
        if self._label is not None and (not level or label != self._label or utc_epoch != self._end_utc):
            self._close_run()
        if not level or label is None or len(self._events) == self._max_events:
            return
        if self._label is None:
            self._label = label
            self._level = level
            self._start_utc = utc_epoch
        elif level > self._level:
            self._level = level
        self._end_utc = utc_epoch + _SEC_PER_HOUR

    def events(self) -> list[Event]:
        """Return every event in start order, after ending the run in progress."""
        self._close_run()
        return self._events

    def _close_run(self) -> None:
        label = self._label
        if label is None:
            return
        self._label = None
        # A run in progress keeps its past hours, but one already over would only take the place of a later one.
        if self._end_utc <= self._now_utc:
            return
        color_index = self._level_colors[self._level - 1]
        self._events.append(
            create_event(label, self._start_utc, self._end_utc - self._start_utc, color_index=color_index)
        )
