"""Exchange가 고정하는 체결 시각과 가격 선택."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class FillConvention:
    """한 decision을 어느 session 시각의 어느 execution field로 체결할지 선언한다."""

    offset_sessions: int
    local_time: time
    timezone: str
    trade_price: str

    def __post_init__(self) -> None:
        if isinstance(self.offset_sessions, bool) or not isinstance(self.offset_sessions, int):
            raise TypeError("offset_sessions must be an integer")
        if self.offset_sessions < 0:
            raise ValueError("offset_sessions must be non-negative")
        if not isinstance(self.local_time, time):
            raise TypeError("local_time must be a datetime.time")
        if self.local_time.tzinfo is not None:
            raise ValueError("local_time must be a timezone-naive wall time")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone must be a non-empty IANA timezone name")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown IANA timezone: {self.timezone!r}") from error
        if not isinstance(self.trade_price, str) or not self.trade_price.strip():
            raise ValueError("trade_price must be a non-empty semantic price field")
