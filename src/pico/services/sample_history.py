from array import array

from micropython import const

# Fills a slot no commit has reached, and stands for a sample the sampler hasn't got.  Its value is the smallest small
# int, so it lies below every other sample and reading it back from an array doesn't allocate.
MISSING = const(-0x40000000)


class SampleHistory:
    """The last ``capacity`` samples of each metric: ``samples[m]`` is metric ``m``'s array, oldest first.

    ``sampler()`` must return an indexable sequence whose first ``metric_count``
    entries are ints from ``MISSING`` to ``-MISSING - 1`` (small ints, so
    reading them back doesn't allocate); any further entries are ignored.
    Slots no commit has reached hold ``MISSING``.  Construction commits once,
    so ``sampler`` must return valid data by then.  Raises ``ValueError`` if
    ``metric_count``, ``capacity`` or ``ticks_per_commit`` is below 1.

    Owns no timer: ``tick()`` must be called periodically.  Each commit
    increments ``commit_count`` and shifts every array in place, so a
    reference to one stays valid; a reader may overwrite its newest sample.
    A commit allocates nothing beyond what ``sampler()`` does, so it either
    completes or, if ``sampler()`` raises, changes nothing.
    """

    def __init__(
        self,
        sampler,  # () -> Sequence
        *,
        metric_count: int,
        capacity: int,
        ticks_per_commit: int,
    ) -> None:
        if metric_count < 1:
            raise ValueError("SampleHistory metric_count must be >= 1")
        if capacity < 1:
            raise ValueError("SampleHistory capacity must be >= 1")
        if ticks_per_commit < 1:
            raise ValueError("SampleHistory ticks_per_commit must be >= 1")

        self._sampler = sampler
        self._ticks_per_commit = ticks_per_commit
        self._ticks_since_commit = 0
        self.samples = tuple(array("i", [MISSING] * capacity) for _ in range(metric_count))
        self.commit_count = 0
        self._commit()

    def tick(self) -> None:
        self._ticks_since_commit += 1
        if self._ticks_since_commit >= self._ticks_per_commit:
            self._ticks_since_commit = 0
            self._commit()

    def _commit(self) -> None:
        reading = self._sampler()
        samples = self.samples
        for i in range(len(samples)):
            metric = samples[i]
            # Not a slice copy, which would allocate.
            for j in range(len(metric) - 1):
                metric[j] = metric[j + 1]
            metric[-1] = reading[i]
        self.commit_count += 1
