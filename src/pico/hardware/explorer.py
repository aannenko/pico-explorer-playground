"""Pico Explorer hardware boundary: pin numbers for on-board peripherals.

Centralizing these constants lets the composition layer (``app.py``)
and individual services share one source of truth for which GPIO does
what.  Useful if the board ever changes or if we want to support a
different carrier.
"""

from micropython import const


BUTTON_A_PIN = const(12)
BUTTON_B_PIN = const(13)
BUTTON_X_PIN = const(14)
BUTTON_Y_PIN = const(15)

BUZZER_PIN = const(0)  # Pico Explorer piezo is on GP0
