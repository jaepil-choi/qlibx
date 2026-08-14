"""venue의 거래 calendar — frozen run input.

구현할 것
    SessionCalendar   session 날짜 목록과 각 session의 open/close 시각. 불변.
    조회              특정 월의 마지막 eligible session, N번째 session, 판단 시점의 성질 등
                      `models/contexts.py`의 CalendarView가 얹힐 원시 질의

**데이터에서 session을 만들어내는 함수가 여기 존재하지 않는다.**
    이것이 architecture §3.1의 금지를 문서가 아니라 부재로 표현한 것이다. 특정 종목의 결측
    때문에 후보 session이 사라지면 cadence 전체가 미래 정보에 오염된다.

    user가 선언한 유도 규칙으로 만드는 경로는 `calendar_derivation.py`에 있고, 그 결과가 이리로
    들어온다. package의 추측과 user의 선언은 다른 것이다(architecture §3.6).

받아들이는 입력은 셋뿐이다
    명시적 session 목록 · 승인된 provider의 결과 · user가 선언한 유도 규칙의 결과
"""
