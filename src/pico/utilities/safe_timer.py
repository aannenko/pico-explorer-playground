import gc


def safe_init(timer, **kwargs) -> None:
    """Init a Timer with one retry after gc.collect() on ENOMEM.

    The RP2040 alarm pool frees slots asynchronously via the IRQ handler.
    A gc.collect() gives the handler time to run and also frees any
    orphaned Timer objects that still hold alarm pool slots.
    """
    try:
        timer.init(**kwargs)
    except OSError:
        gc.collect()
        timer.init(**kwargs)
