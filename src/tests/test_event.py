from operator import setitem

import pytest
from scheduling.event import create_event, Event


def test_event_has_the_given_fields_and_color_index_zero_by_default() -> None:
    e = create_event("work", 123, 45, color_index=2)
    assert (e.label, e.start_utc, e.duration_sec, e.color_index) == ("work", 123, 45, 2)
    assert create_event("work", 0, 1).color_index == 0


@pytest.mark.parametrize(
    "args, message",
    [
        (("", 0, 1), "^Event label cannot be empty$"),
        (("x", -1, 1), "^Event start timestamp cannot be negative$"),
        (("x", 0, -1), "^Event duration cannot be negative$"),
        (("x", 0, 1, -1), "^Event color_index cannot be negative$"),
    ],
)
def test_event_rejects_an_invalid_field(args: tuple, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        create_event(*args)


def test_event_repr_is_stable() -> None:
    e = create_event("rest", 10, 20, color_index=2)
    assert repr(e) == (
        "Event(label='rest', start_utc=10, duration_sec=20, "
        "color_index=2)"
    )


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
