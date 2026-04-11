import pytest
from scheduling.event import Event


def test_event_init_sets_fields() -> None:
    e = Event("work", 123, 45)
    assert e.name == "work"
    assert e.start_timestamp == 123
    assert e.duration_sec == 45


def test_event_requires_name() -> None:
    with pytest.raises(ValueError, match="Event name cannot be empty"):
        Event("", 0, 1)


def test_event_requires_non_negative_start_timestamp() -> None:
    with pytest.raises(ValueError, match="Event start timestamp cannot be negative"):
        Event("x", -1, 1)


def test_event_requires_non_negative_duration() -> None:
    with pytest.raises(ValueError, match="Event duration cannot be negative"):
        Event("x", 0, -1)


def test_event_repr_is_stable() -> None:
    e = Event("rest", 10, 20)
    assert repr(e) == "Event(name=rest, start_timestamp=10, wall_clock_duration_sec=20, real_duration_sec=20)"


def test_event_real_duration_defaults_to_duration() -> None:
    e = Event("work", 100, 3600)
    assert e.real_duration_sec == 3600


def test_event_real_duration_explicit() -> None:
    e = Event("rest", 100, 3600, real_duration_sec=3000)
    assert e.real_duration_sec == 3000
    assert e.duration_sec == 3600
