from operator import setitem

import pytest
from scheduling.event import create_event, Event


def test_event_init_sets_fields() -> None:
    e = create_event("work", 123, 45)
    assert e.label == "work"
    assert e.start_utc == 123
    assert e.duration_sec == 45


def test_event_requires_label() -> None:
    with pytest.raises(ValueError, match="^Event label cannot be empty$"):
        create_event("", 0, 1)


def test_event_requires_non_negative_start() -> None:
    with pytest.raises(ValueError, match="^Event start timestamp cannot be negative$"):
        create_event("x", -1, 1)


def test_event_requires_non_negative_duration() -> None:
    with pytest.raises(ValueError, match="^Event duration cannot be negative$"):
        create_event("x", 0, -1)


def test_event_repr_is_stable() -> None:
    e = create_event("rest", 10, 20)
    assert repr(e) == (
        "Event(label='rest', start_utc=10, duration_sec=20, "
        "color_index=0)"
    )


def test_event_color_index_defaults_to_zero() -> None:
    assert create_event("work", 0, 1).color_index == 0


def test_event_color_index_explicit() -> None:
    assert create_event("rain", 0, 1, color_index=2).color_index == 2


def test_event_rejects_negative_color_index() -> None:
    with pytest.raises(ValueError, match="^Event color_index cannot be negative$"):
        create_event("x", 0, 1, color_index=-1)


def test_event_repr_includes_explicit_color_index() -> None:
    e = create_event("rain", 5, 600, color_index=2)
    assert "color_index=2" in repr(e)


def test_event_factory_returns_event_compared_by_value() -> None:
    e = create_event(label="rain", start_utc=0, duration_sec=0, color_index=2)

    assert type(e) is Event
    assert e == create_event("rain", 0, 0, 2)
    assert e != create_event("snow", 0, 0, 2)
    assert e != create_event("rain", 1, 0, 2)
    assert e != create_event("rain", 0, 1, 2)
    assert e != create_event("rain", 0, 0, 1)


def test_event_fields_and_tuple_items_are_immutable() -> None:
    e = create_event("rain", 5, 600, 2)

    for field in ("label", "start_utc", "duration_sec", "color_index"):
        with pytest.raises(AttributeError):
            setattr(e, field, None)
    with pytest.raises(TypeError):
        setitem(e, 0, "snow")

    assert e == create_event("rain", 5, 600, 2)
