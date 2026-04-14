import time


def format_header_time(local_epoch: int) -> str:
    """Format a local-epoch timestamp as `'YY-MM-DD HH:MM` for display headers."""
    year, month, mday, hour, minute = time.gmtime(local_epoch)[0:5]
    return f"'{(year % 100):02}-{month:02}-{mday:02} {hour:02}:{minute:02}"
