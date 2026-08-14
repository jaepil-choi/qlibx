"""시각 — 타입이 아니라 함수.

구현할 것
    TzAware          pydantic 경계 검증용 Annotated[datetime, ...]
    reject_naive     timezone 없는 datetime을 거부한다
    at_local         (session 날짜, local time, tz) -> tz-aware 시점
    shift_calendar   CalendarLookback의 달력 산술. month-end clamp policy 포함

**감싸는 클래스를 만들지 않는다.**
    datetime을 감싸면 산술이 필요한 모든 소비자가 매번 벗긴다. 창 경계 계산, calendar 산술,
    available_at 비교가 전부 진짜 datetime을 원한다. nautilus도 `core/datetime`을 함수 모음으로
    두었고 Timestamp 클래스가 없다.

    막으려는 것은 타입이 아니라 **경계**다. 등록 · 선언 · 역직렬화 입구에서 한 번 거부한다
    (`UC-TIME-001`: naive datetime을 임의 timezone으로 해석하지 않는다).

왜 at_local이 여기 있나
    TriggerPolicy(04:00)도 FillConvention(15:30)도 AvailabilityBinding(15:30)도 **같은 산술**을
    한다. 세 곳이 각자 구현하면 month-end clamp와 DST 처리가 어긋난다.
"""
