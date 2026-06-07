"""Work-week calendar stream: work / rest / weekend blocks."""

from scheduling import event_factory
from scheduling.stream import Stream
from services.time_service import TimeService


def build_stream(time_service: TimeService) -> Stream:
    return Stream(
        events_iter=event_factory.work_week_loop(
            work_days={0, 1, 2, 3, 4},
            work_start=(9, 0),
            work_end=(18, 0),
            time_service=time_service,
        ),
    )
