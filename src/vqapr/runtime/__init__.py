"""runtime — 시간은 전부 선언에서 나온다.

이 층이 답하는 질문: **언제 호출하는가.**

핵심 성질 하나. 모든 시각이 선언에서 나오므로(SessionCalendar x TriggerPolicy가 DECISION을,
FillConvention이 EXECUTION을) 데이터가 도착해서 시각이 생기는 일이 없다. 따라서 **전체 이벤트
열이 preflight에서 계산된다**(architecture §2.1).

그래서 이 package에는 clock이 없고 `timeline.py`가 있다.
"""
