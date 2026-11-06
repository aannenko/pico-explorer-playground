from machine import Pin


class ButtonPoller:
    """Edge-detecting button poller using raw Pin levels (active-low).

    Tracks edges itself rather than via pimoroni.Button, whose read() consumes
    each press: a press whose schedule() hits a full queue is retried on the
    next poll.
    """

    def __init__(self, schedule) -> None:  # schedule: (callback, arg) -> None
        self._schedule = schedule
        self._buttons: list[tuple] = []  # list[tuple[Pin, Callable[[int], None], bool]]

    def add(self, pin: Pin, on_press) -> None:  # on_press: (int) -> None
        """Watch ``pin``; each press schedules ``on_press(0)``."""
        self._buttons.append((pin, on_press, False))

    def poll_once(self) -> None:
        buttons = self._buttons
        schedule = self._schedule
        for i in range(len(buttons)):
            pin, on_press, was_pressed = buttons[i]
            pressed = pin.value() == 0
            if pressed and not was_pressed:
                # Scheduled rather than called directly: scheduled callbacks
                # never nest, so no tick runs mid-handler.
                try:
                    schedule(on_press, 0)
                except RuntimeError:
                    continue
            if pressed != was_pressed:
                buttons[i] = (pin, on_press, pressed)
