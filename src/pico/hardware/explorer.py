"""Pico Explorer hardware boundary: GPIO pin numbers for on-board peripherals."""

from micropython import const


BUTTON_A_PIN = const(12)
BUTTON_B_PIN = const(13)
BUTTON_X_PIN = const(14)
BUTTON_Y_PIN = const(15)

BUZZER_PIN = const(0)  # Pico Explorer piezo is on GP0
