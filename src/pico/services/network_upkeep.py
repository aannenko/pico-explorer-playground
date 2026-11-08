import time

from services.tick_scheduler import TickScheduler
from utilities.log import log_exception


class NetworkUpkeep:
    """Keeps the WiFi link up and the clock synced, on one schedule.

    Every ``period_ms`` it calls ``start_reconnect``, which must leave a live link
    alone, then calls ``sync_clock`` on the first tick that finds the link up;
    after a reconnect that is a fresh link, the likeliest to carry the sync.  A
    failed sync waits for the next check.  ``period_ms`` must be under 2**29 ms
    (about 6.2 days), the range of ``time.ticks_add``.
    """

    def __init__(
        self,
        wifi,  # has is_connected() -> bool
        start_reconnect,  # () -> None
        sync_clock,  # () -> bool
        period_ms: int,
        tick_scheduler: TickScheduler,
    ) -> None:
        self._wifi = wifi
        self._start_reconnect = start_reconnect
        self._sync_clock = sync_clock
        self._period_ms = period_ms
        self._next_check_ms = time.ticks_add(time.ticks_ms(), period_ms)
        self._sync_pending = False
        tick_scheduler.register(self._tick)

    def _tick(self) -> None:
        try:
            self._advance()
        except Exception as e:
            log_exception("[upkeep] tick err:", e)

    def _advance(self) -> None:
        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, self._next_check_ms) >= 0:
            # Rescheduled before acting, so a check that raises waits a full period
            # instead of retrying on every tick.
            self._next_check_ms = time.ticks_add(now_ms, self._period_ms)
            self._sync_pending = True
            self._start_reconnect()
        if self._sync_pending and self._wifi.is_connected():
            # Cleared first, so a sync that raises isn't retried on every tick.
            self._sync_pending = False
            self._sync_clock()
