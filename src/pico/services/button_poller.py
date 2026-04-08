from machine import Pin


class ButtonPoller:
    """Edge-detecting button poller using raw Pin levels (active-low).

    Uses machine.Pin instead of pimoroni.Button to avoid the
    latch-and-clear + auto-repeat behavior of Button.read() which
    defeats edge detection.
    """

    def __init__(self, schedule) -> None:
        self._schedule = schedule
        self._buttons: list[tuple] = []  # list[tuple[Pin, Callable[[int], None], bool]]

    def add(self, pin: Pin, on_press) -> None:
        self._buttons.append((pin, on_press, False))

    def poll_once(self) -> None:
        buttons = self._buttons
        schedule = self._schedule
        for i in range(len(buttons)):
            pin, on_press, was_pressed = buttons[i]
            pressed = pin.value() == 0  # active-low with pull-up
            if pressed and not was_pressed:
                schedule(on_press, 0)
            if pressed != was_pressed:
                buttons[i] = (pin, on_press, pressed)
