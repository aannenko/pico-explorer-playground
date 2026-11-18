from micropython import const

INITIAL = const(0)
FETCHING = const(1)
DONE = const(2)
FAILED = const(3)


class FetchCoordinator:
    """One-at-a-time fetch gate; not thread safety (there is one thread).

    Two fetches due in the same tick would otherwise run back-to-back, freezing
    rendering for both; the second waits a tick instead.
    """

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
        """Only the attempt that acquired the gate may release it."""
        self._busy = False


class FetchState:
    """Data for one fetch attempt: its stage, then its result or error."""

    def __init__(self, fetcher, wifi, schedule, coordinator: FetchCoordinator) -> None:
        self.stage = INITIAL
        self.result = None
        self.error = None
        self.fetcher = fetcher          # () -> result; may raise
        self.wifi = wifi                # has is_connected() -> bool
        self.schedule = schedule        # (callback, arg) -> None
        self.coordinator = coordinator


def tick(state: FetchState) -> None:
    """Dispatch the fetch once WiFi is up and the gate is free; call once per owner tick."""
    if state.stage != INITIAL:
        return
    if not state.wifi.is_connected():
        return
    if not state.coordinator.try_acquire():
        return
    state.stage = FETCHING
    try:
        # Scheduled, so the current tick finishes before the blocking fetch.
        state.schedule(_do_fetch, state)
    except Exception:
        state.coordinator.release()
        state.stage = INITIAL


def _do_fetch(state: FetchState) -> None:
    try:
        state.result = state.fetcher()
        state.stage = DONE
    except Exception as exc:
        state.error = exc
        state.stage = FAILED
    finally:
        state.coordinator.release()


def is_done(state: FetchState) -> bool:
    """Return whether the attempt finished, with a result or an error."""
    return state.stage == DONE or state.stage == FAILED