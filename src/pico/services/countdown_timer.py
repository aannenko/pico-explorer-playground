import time

from micropython import const

INITIAL = const(0)
RUNNING = const(1)
PAUSED = const(2)
DONE = const(3)


class CountdownTimer:
    """Pausable countdown with a label, measured in seconds."""

    def __init__(
        self,
        on_done=lambda: None,  # () -> None
        on_configure=lambda: None,  # () -> None
        get_time=time.time,  # () -> int
        tick_scheduler=None,
    ) -> None:
        self._on_done_action = on_done
        self._on_configure_action = on_configure
        self._get_time = get_time

        self._state = INITIAL
        self._label = ""
        self._total_sec = 0
        self._start_timestamp = 0
        self._end_timestamp = 0
        self._remaining_sec = 0

        if tick_scheduler is not None:
            tick_scheduler.register(self._tick)

    @property
    def state(self) -> int:
        """Lifecycle state: INITIAL, RUNNING, PAUSED or DONE."""
        return self._state

    @property
    def label(self) -> str:
        return self._label

    @property
    def total_sec(self) -> int:
        return self._total_sec

    @property
    def elapsed_sec(self) -> int:
        """Seconds counted down so far, excluding pauses."""
        if self._state == RUNNING:
            return self._get_time() - self._start_timestamp
        if self._state == PAUSED:
            return self._total_sec - self._remaining_sec
        if self._state == DONE:
            return self._total_sec
        return 0

    @property
    def remaining_sec(self) -> int:
        """Seconds left while running or paused, else 0."""
        if self._state == RUNNING:
            return max(0, self._end_timestamp - self._get_time())
        if self._state == PAUSED:
            return self._remaining_sec
        return 0

    def configure(self, label: str, total_sec: int) -> None:
        """Set up a new countdown, discarding any progress."""
        self._on_configure_action()
        self._state = INITIAL
        self._label = label
        self._total_sec = total_sec
        self._start_timestamp = 0
        self._end_timestamp = 0
        self._remaining_sec = 0

    def start(self) -> None:
        """Begin counting down from ``total_sec``.

        Requires the INITIAL state and a positive ``total_sec``.
        """
        if self._state != INITIAL or self._total_sec <= 0:
            return
        now = self._get_time()
        self._start_timestamp = now
        self._end_timestamp = now + self._total_sec
        self._state = RUNNING

    def pause(self) -> None:
        """Freeze a running countdown, keeping the time left."""
        if self._state != RUNNING:
            return
        self._remaining_sec = max(0, self._end_timestamp - self._get_time())
        self._state = PAUSED

    def resume(self) -> None:
        """Continue a paused countdown where it left off."""
        if self._state != PAUSED:
            return
        now = self._get_time()
        elapsed = self._total_sec - self._remaining_sec
        self._start_timestamp = now - elapsed
        self._end_timestamp = now + self._remaining_sec
        self._state = RUNNING

    def reset(self) -> None:
        """Discard progress, keeping the label and duration."""
        self.configure(self._label, self._total_sec)

    def _tick(self) -> None:
        if self._state == RUNNING and self._get_time() >= self._end_timestamp:
            self._state = DONE
            self._on_done_action()
