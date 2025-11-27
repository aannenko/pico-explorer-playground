class Event:
    """
    Represents a scheduled event.

    Attributes:
        name (str): Event name.
        start_timestamp (int): Event start time as seconds since Epoch (Unix timestamp).
        duration_sec (int): Event duration in seconds.
    """
    def __init__(
        self,
        name: str,
        start_timestamp: int,
        duration_sec: int,
    ) -> None:
        self.name = name
        self.start_timestamp = start_timestamp
        self.duration_sec = duration_sec

    def __repr__(self) -> str:
        return (
            f"Event(name={self.name}, "
            f"start_timestamp={self.start_timestamp}, "
            f"duration_sec={self.duration_sec})"
        )