import time

from micropython import const

INITIAL = const(0)
RUNNING = const(1)
PAUSED = const(2)
DONE = const(3)


class CountdownTimer:
    def __init__(
        self,
        on_done=lambda: None,
        on_configure=lambda: None,
        get_time=time.time,
        tick_scheduler=None,
    ) -> None:
        self._on_done_action = on_done
        self._on_configure_action = on_configure
        self._get_time = get_time

        self._state: int = INITIAL
        self._name: str = ""
        self._total_sec: int = 0
        self._start_timestamp: int = 0
        self._end_timestamp: int = 0
        self._remaining_sec: int = 0

        if tick_scheduler is not None:
            tick_scheduler.register(self._tick)

    @property
    def state(self) -> int:
        return self._state

    @property
    def name(self) -> str:
        return self._name

    @property
    def total_sec(self) -> int:
        return self._total_sec

    @property
    def elapsed_sec(self) -> int:
        if self._state == RUNNING:
            return self._get_time() - self._start_timestamp
        if self._state == PAUSED:
            return self._total_sec - self._remaining_sec
        if self._state == DONE:
            return self._total_sec
        return 0

    @property
    def remaining_sec(self) -> int:
        if self._state == RUNNING:
            return max(0, self._end_timestamp - self._get_time())
        if self._state == PAUSED:
            return self._remaining_sec
        return 0

    def configure(self, name: str, total_sec: int) -> None:
        self._on_configure_action()
        self._state = INITIAL
        self._name = name
        self._total_sec = total_sec
        self._start_timestamp = 0
        self._end_timestamp = 0
        self._remaining_sec = 0

    def start(self) -> None:
        if self._state != INITIAL or self._total_sec <= 0:
            return
        now = self._get_time()
        self._start_timestamp = now
        self._end_timestamp = now + self._total_sec
        self._state = RUNNING

    def pause(self) -> None:
        if self._state != RUNNING:
            return
        self._remaining_sec = max(0, self._end_timestamp - self._get_time())
        self._state = PAUSED

    def resume(self) -> None:
        if self._state != PAUSED:
            return
        now = self._get_time()
        elapsed = self._total_sec - self._remaining_sec
        self._start_timestamp = now - elapsed
        self._end_timestamp = now + self._remaining_sec
        self._state = RUNNING

    def reset(self) -> None:
        self.configure(self._name, self._total_sec)

    def _tick(self) -> None:
        if self._state == RUNNING and self._get_time() >= self._end_timestamp:
            self._state = DONE
            self._on_done_action()
