"""Fetch mechanics for the network-backed calendar streams.

Three small pieces, split by responsibility:

* ``FetchState`` — plain data for ONE fetch attempt: the stage it's in plus the
  result/error once it finishes.  ``FetchMachine.start`` allocates it when a fetch
  begins; the owner drops it (GC) the moment it harvests the outcome, so nothing
  fetch-related is pinned during the long idle between fetches.
* ``FetchMachine`` — stateless.  Pure functions that drive a ``FetchState``
  forward: gate, dispatch the blocking work off-tick, record the outcome.  No
  timing/backoff/freshness lives here — that belongs to the long-lived owner
  (see ``EventStreamService``).
* ``FetchCoordinator`` — a one-at-a-time gate.  NOT thread safety (there is one
  thread); it serialises fetches so two services that come due in the same tick
  don't queue back-to-back in a single ``schedule`` drain (which would freeze
  rendering for the sum of both).  The second waits a tick, letting a render slip
  in between.
"""

from micropython import const

# ``FetchState`` stages.
INITIAL = const(0)   # created; tick() will try wifi + the gate, then dispatch
FETCHING = const(1)  # blocking work dispatched off-tick, not yet finished
DONE = const(2)      # finished OK; ``result`` is set
FAILED = const(3)    # finished with an exception; ``error`` is set


class FetchCoordinator:
    """One-at-a-time fetch gate (serialises fetches; not thread safety)."""

    def __init__(self) -> None:
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def try_acquire(self) -> bool:
        if self._busy:
            return False
        self._busy = True
        return True

    def release(self) -> None:
        # Only the fetch that acquired the gate ever calls this (its own
        # ``_do_fetch`` finally, or its schedule-fail rollback), so an
        # unconditional clear is safe — there is no cross-release on one thread.
        self._busy = False


class FetchState:
    """Data for one in-flight fetch; advanced by ``FetchMachine``."""

    def __init__(self, fetcher, wifi, schedule, coordinator) -> None:
        self.stage: int = INITIAL
        self.result = None
        self.error = None
        self.fetcher = fetcher          # () -> result; may raise
        self.wifi = wifi                # has is_connected() -> bool
        self.schedule = schedule        # (callback, arg) -> None
        self.coordinator = coordinator  # FetchCoordinator


class FetchMachine:
    """Stateless driver for a ``FetchState``; call ``tick`` once per owner tick."""

    @staticmethod
    def start(fetcher, wifi, schedule, coordinator) -> FetchState:
        return FetchState(fetcher, wifi, schedule, coordinator)

    @staticmethod
    def tick(state: FetchState) -> None:
        if state.stage != INITIAL:
            return  # FETCHING waits for the scheduled callback; DONE/FAILED terminal
        if not state.wifi.is_connected():
            return  # hold in INITIAL; re-poll cheaply next tick
        if not state.coordinator.try_acquire():
            return  # another fetch in flight; stay INITIAL
        state.stage = FETCHING
        try:
            state.schedule(FetchMachine._do_fetch, state)
        except Exception:
            state.coordinator.release()
            state.stage = INITIAL

    @staticmethod
    def _do_fetch(state: FetchState) -> None:
        # Runs off the tick via schedule(); the blocking work lives here.
        try:
            state.result = state.fetcher()
            state.stage = DONE
        except Exception as exc:
            state.error = exc
            state.stage = FAILED
        finally:
            state.coordinator.release()

    @staticmethod
    def is_done(state: FetchState) -> bool:
        return state.stage == DONE or state.stage == FAILED
