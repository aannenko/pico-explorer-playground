"""Pre-allocated ring buffers for time-series history of N numeric metrics.

Holds the last ``capacity`` samples of each of ``num_metrics`` floats sourced
from a user-supplied ``sampler`` callable.  A ``TickScheduler`` subscriber
commits one snapshot every ``ticks_per_commit`` ticks; commits also bump
``commit_count`` so consumers can detect "new data" without doing diff work.

The ``sampler`` is called as ``sampler()`` and must return an indexable
sequence (tuple/list) whose first ``num_metrics`` entries are floats —
extra trailing entries (e.g. a sensor's status string) are ignored.

Construction performs **one immediate commit** so the newest slot is
populated from boot; callers must ensure ``sampler()`` returns valid data
at construction time.

This module owns no timers; the application is responsible for registering
``self._tick_ref`` on the long-lived ``TickScheduler``.  Single-site
registration keeps ownership clear and (on MicroPython, where bound
methods compare by identity) makes ``TickScheduler.register``'s ``not in``
dedup work reliably with the cached ref.
"""

from array import array

import micropython


class RingHistory:
    @micropython.native
    def __init__(
        self,
        sampler,  # () -> sequence[float] of length >= num_metrics
        *,
        num_metrics: int,
        capacity: int,
        ticks_per_commit: int,
    ) -> None:
        if num_metrics < 1:
            raise ValueError("RingHistory num_metrics must be >= 1")
        if capacity < 1:
            raise ValueError("RingHistory capacity must be >= 1")
        if ticks_per_commit < 1:
            raise ValueError("RingHistory ticks_per_commit must be >= 1")

        self._sampler = sampler
        self._capacity = capacity
        self._ticks_per_commit = ticks_per_commit

        self._buffers = tuple(
            array("f", [0.0] * capacity) for _ in range(num_metrics)
        )

        self._head = 0
        self._filled = 0
        self._tick_counter = 0
        self.commit_count = 0

        # MicroPython bound methods compare by identity — caching once
        # is what makes TickScheduler.register's dedup work reliably.
        self._tick_ref = self._tick

        # Reused per commit to avoid a fresh range() allocation each time.
        self._metric_range = range(num_metrics)

        self._commit_now()

    @property
    def capacity(self) -> int:
        return self._capacity

    def filled(self, metric_idx: int) -> int:
        """Number of valid samples available for ``metric_idx`` (0..capacity)."""
        return self._filled

    @micropython.native
    def value_at(self, metric_idx: int, value_idx: int) -> float:
        """Return the sample ``value_idx`` slots back from newest.

        ``value_idx == 0`` is the most recent sample; ``value_idx == filled()-1``
        is the oldest still held.  No bounds-check — callers loop up to
        ``filled(metric_idx)``.
        """
        i = self._head - 1 - value_idx
        if i < 0:
            i += self._capacity
        return self._buffers[metric_idx][i]

    def _tick(self) -> None:
        """TickScheduler subscriber — zero-arg (scheduler calls ``callback()``).

        Runs in scheduled (not IRQ) context, so ``sampler()`` allocations
        are safe.
        """
        self._tick_counter += 1
        if self._tick_counter >= self._ticks_per_commit:
            self._tick_counter = 0
            self._commit_now()

    @micropython.native
    def _commit_now(self) -> None:
        reading = self._sampler()
        head = self._head
        buffers = self._buffers
        for i in self._metric_range:
            buffers[i][head] = reading[i]

        head += 1
        if head >= self._capacity:
            head = 0
        self._head = head

        if self._filled < self._capacity:
            self._filled += 1

        self.commit_count += 1
