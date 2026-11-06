import sys

import micropython


def log_exception(tag: str, exc: Exception) -> None:
    """Print ``tag``, a heap summary for ``MemoryError``, then the traceback.

    Pass a preformatted ``tag``: formatting one inside a ``MemoryError`` handler
    allocates, and can fail.
    """
    print(tag)
    if isinstance(exc, MemoryError):
        # mem_info() reports "max free sz", the largest free run in 16-byte GC
        # blocks: plenty free but a small max means a fragmented heap.
        micropython.mem_info()
    sys.print_exception(exc)
