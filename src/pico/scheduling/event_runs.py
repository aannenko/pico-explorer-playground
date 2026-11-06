"""Building calendar ``Event`` bars from per-hour samples."""

from micropython import const

from scheduling.event import Event

_SEC_PER_HOUR = const(3600)


def _level(value, warn: int, severe: int) -> int:
    """``warn`` / ``severe`` are inclusive lower bounds; a missing value
    (``None``) is treated as below warning.
    """
    if value is None:
        return 0
    if value >= severe:
        return 2
    if value >= warn:
        return 1
    return 0


def best_by_priority(candidates: list[tuple[int, str, int]]) -> tuple[str, int] | None:
    """Pick the highest-``priority`` candidate; ties keep the earliest listed.

    Each candidate is ``(priority, label, color_index)``.  Returns the
    winner's ``(label, color_index)``, or ``None`` for an empty list.
    """
    best = None
    best_priority = 0
    for priority, label, color_index in candidates:
        if best is None or priority > best_priority:
            best = (label, color_index)
            best_priority = priority
    return best


def merge_runs(emitted: list[tuple[int, str, int]]) -> list[Event]:
    """Merge hourly ``(epoch, label, color_index)`` entries into ``Event`` bars.

    Requires ``emitted`` in ascending epoch order.

    Only adjacent hours with equal label and color_index merge into one ``Event``.
    """
    events: list[Event] = []
    run = None  # [label, color_index, start_epoch, end_epoch]
    for epoch, label, color_index in emitted:
        if run is not None and run[0] == label and run[1] == color_index and run[3] == epoch:
            run[3] = epoch + _SEC_PER_HOUR
        else:
            if run is not None:
                events.append(_event_from_run(run))
            run = [label, color_index, epoch, epoch + _SEC_PER_HOUR]
    if run is not None:
        events.append(_event_from_run(run))
    return events


def _event_from_run(run: list) -> Event:
    label, color_index, start_epoch, end_epoch = run
    return Event(label, start_epoch, end_epoch - start_epoch, color_index=color_index)
