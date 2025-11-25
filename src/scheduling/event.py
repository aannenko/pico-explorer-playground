class Event:
    """
    Represents a scheduled event.

    Attributes:
        name (str): The name of the event.
        start_timestamp (int): The start time of the event in the form of seconds since Epoch.
        duration_sec (int): The duration of the event in seconds.
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