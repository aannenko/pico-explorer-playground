from __future__ import annotations

import time

from displays.shared.header import format_header_time


class TestFormatHeaderTime:
    def test_typical_timestamp(self):
        # 2026-04-10 17:56 UTC
        epoch = time.mktime((2026, 4, 10, 17, 56, 0, 0, 0))

        assert format_header_time(epoch) == "2026-04-10 17:56"

    def test_midnight(self):
        epoch = time.mktime((2026, 1, 1, 0, 0, 0, 0, 0))

        assert format_header_time(epoch) == "2026-01-01 00:00"
