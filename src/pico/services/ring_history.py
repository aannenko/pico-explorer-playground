from array import array

import micropython


class RingHistory:
    """Rolling history of the last ``capacity`` samples per metric.

    ``sampler()`` must return an indexable sequence whose first ``metric_count``
    entries are floats; any further entries are ignored.  Construction commits
    once, so ``sampler`` must return valid data by then.  Raises ``ValueError``
    if ``metric_count``, ``capacity`` or ``ticks_per_commit`` is below 1.

    Owns no timer: ``tick()`` must be called periodically.  Each commit
    increments ``commit_count``.
    """

    @micropython.native
    def __init__(
        self,
        sampler,  # () -> Sequence
        *,
        metric_count: int,
        capacity: int,
        ticks_per_commit: int,
    ) -> None:
        if metric_count < 1:
            raise ValueError("RingHistory metric_count must be >= 1")
        if capacity < 1:
            raise ValueError("RingHistory capacity must be >= 1")
        if ticks_per_commit < 1:
            raise ValueError("RingHistory ticks_per_commit must be >= 1")

        self._sampler = sampler
        self._capacity = capacity
        self._ticks_per_commit = ticks_per_commit

        self._buffers = tuple(
            array("f", [0.0] * capacity) for _ in range(metric_count)
        )

        self._next_slot = 0
        self._sample_count = 0
        self._ticks_since_commit = 0
        self.commit_count = 0

        self._commit()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def sample_count(self) -> int:
        """Samples stored for each metric, 0..capacity."""
        return self._sample_count

    @micropython.native
    def value_at(self, metric_index: int, age: int) -> float:
        """Return the sample ``age`` slots back from the newest.

        Requires ``0 <= age < sample_count``.
        """
        i = self._next_slot - 1 - age
        if i < 0:
            i += self._capacity
        return self._buffers[metric_index][i]

    def update_latest(self, metric_index: int, value: float) -> None:
        """Overwrite the newest sample of one metric without advancing the ring."""
        i = self._next_slot - 1
        if i < 0:
            i += self._capacity
        self._buffers[metric_index][i] = value

    def tick(self) -> None:
        self._ticks_since_commit += 1
        if self._ticks_since_commit >= self._ticks_per_commit:
            self._ticks_since_commit = 0
            self._commit()

    @micropython.native
    def _commit(self) -> None:
        reading = self._sampler()
        head = self._next_slot
        buffers = self._buffers
        for i in range(len(buffers)):
            buffers[i][head] = reading[i]

        head += 1
        if head >= self._capacity:
            head = 0
        self._next_slot = head

        if self._sample_count < self._capacity:
            self._sample_count += 1

        self.commit_count += 1
