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


def log_memory(tag: str) -> None:
    """Print ``tag``, a heap summary and the qstr pool's use.

    Allocates nothing, given a preformatted ``tag``, so it doesn't disturb the heap it reports.  It doesn't collect
    either, so garbage not yet collected counts as used.  "max free sz" is the largest contiguous free block in
    16-byte GC blocks.
    """
    print(tag)
    micropython.mem_info()
    micropython.qstr_info()
