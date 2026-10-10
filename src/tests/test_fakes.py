"""Fidelity tests for the shared host fakes.

``FakePicoGraphics.measure_text`` stands in for firmware text measurement, so
layout assertions across the suite are only as trustworthy as its glyph table.
Nothing else exercises the letter region of that table, and a single wrong
digit there would silently shift every width it feeds.
"""

import pytest

from _fakes import FakePicoGraphics


# Measured on a Pimoroni Pico Explorer (MicroPython 1.27.0, bitmap8) via
# ``gfx.measure_text(s, scale=n)``.  The first four were read directly off the
# device; the rest were the values previously pinned in the fake by hand.
DEVICE_WIDTHS = (
    ("-88.8", 3, 63),
    ("2044-08-08 04:44", 3, 219),
    ("2044-08-08 04:44", 4, 292),
    ("2111-11-11 11:11", 3, 186),
    ("8888", 3, 57),
    ("9999", 3, 57),
    ("1000", 3, 54),
    ("-999", 3, 54),
    ("99.9", 3, 51),
    ("-100", 3, 51),
    ("-99.9", 3, 63),
    ("100.0", 3, 63),
    ("-100.0", 3, 75),
)


@pytest.mark.parametrize("text,scale,expected", DEVICE_WIDTHS)
def test_measure_text_matches_device(text: str, scale: int, expected: int) -> None:
    assert FakePicoGraphics().measure_text(text, scale=scale) == expected


def test_measure_text_scales_linearly() -> None:
    """The firmware multiplies the whole advance sum by ``scale``, so a string's
    width at scale n is exactly n times its width at scale 1."""
    gfx = FakePicoGraphics()
    base = gfx.measure_text("2044-08-08 04:44", scale=1)
    for scale in (2, 3, 4, 6):
        assert gfx.measure_text("2044-08-08 04:44", scale=scale) == base * scale


def test_measure_text_is_proportional_not_monospaced() -> None:
    """bitmap8 glyphs differ in width, which is why calendar bar labels can't be
    sized by character count.  Guards the letter region of the table."""
    gfx = FakePicoGraphics()
    narrow = gfx.measure_text("I", scale=1)
    normal = gfx.measure_text("A", scale=1)
    wide = gfx.measure_text("M", scale=1)
    assert (narrow, normal, wide) == (3, 4, 5)
    # Same character count, different rendered width.
    assert gfx.measure_text("WORK", scale=3) != gfx.measure_text("BIOS", scale=3)


def test_measure_text_empty_string_is_zero() -> None:
    """``len(text) - 1`` would go negative for the empty string."""
    assert FakePicoGraphics().measure_text("", scale=3) == 0


def test_measure_text_rejects_untabulated_glyph() -> None:
    """Non-ASCII (e.g. a Czech waste label) must fail loudly rather than return a
    guessed width that a layout assertion would silently trust."""
    with pytest.raises(ValueError, match="printable ASCII"):
        FakePicoGraphics().measure_text("SMĚSNÝ", scale=3)
