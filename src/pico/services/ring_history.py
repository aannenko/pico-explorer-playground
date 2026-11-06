from array import array

import micropython


class RingHistory:
    """Rolling history of the last ``capacity`` samples per metric.

    ``sampler()`` must return an indexable sequence whose first ``num_metrics``
    entries are floats; any further entries are ignored.  Construction commits
    once, so ``sampler`` must return valid data by then.  Raises ``ValueError``
    if ``num_metrics``, ``capacity`` or ``ticks_per_commit`` is below 1.

    Owns no timer: ``_tick_ref`` must be called periodically.  Each commit
    increments ``commit_count``.
    """

    @micropython.native
    def __init__(
        self,
        sampler,  # () -> Sequence
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

        self._tick_ref = self._tick

        self._commit_now()

    @property
    def capacity(self) -> int:
        return self._capacity

    def filled(self, metric_idx: int) -> int:
        """Number of stored samples, 0..capacity."""
        return self._filled

    @micropython.native
    def value_at(self, metric_idx: int, value_idx: int) -> float:
        """Return the sample ``value_idx`` slots back from the newest.

        Requires ``0 <= value_idx < filled(metric_idx)``.
        """
        i = self._head - 1 - value_idx
        if i < 0:
            i += self._capacity
        return self._buffers[metric_idx][i]

    def update_latest(self, metric_idx: int, value: float) -> None:
        """Overwrite the newest sample of one metric without advancing the ring."""
        if self._filled == 0:
            return
        i = self._head - 1
        if i < 0:
            i += self._capacity
        self._buffers[metric_idx][i] = value

    def _tick(self) -> None:
        self._tick_counter += 1
        if self._tick_counter >= self._ticks_per_commit:
            self._tick_counter = 0
            self._commit_now()

    @micropython.native
    def _commit_now(self) -> None:
        reading = self._sampler()
        head = self._head
        buffers = self._buffers
        for i in range(len(buffers)):
            buffers[i][head] = reading[i]

        head += 1
        if head >= self._capacity:
            head = 0
        self._head = head

        if self._filled < self._capacity:
            self._filled += 1

        self.commit_count += 1
