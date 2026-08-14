"""체결 시각과 체결가 선택 — 선언이다.

구현할 것
    FillConvention   offset_sessions(판단 이벤트가 속한 session 기준, 기본 0)
                     local_time, timezone
                     trade_price  체결 테이블의 어느 가격 컬럼

`models/triggers.py`와 대칭이다
    Model      "매 세션 04:00에 판단한다"        TriggerPolicy
    Exchange   "그 session 15:30에 close로 체결"  FillConvention

    둘 다 선언이고 어느 쪽도 스스로 시간을 진행시키지 않는다. `runtime/timeline.py`가
    SessionCalendar와 결합해 이벤트를 만든다. 소유자가 다른 이유는 언제 판단할지는 전략의
    성질이고 언제 체결되는지는 venue의 성질이기 때문이다.

**대체하지 않는다.**
    선언한 컬럼이 없거나 값이 유한하지 않거나 양수가 아니면 **다른 컬럼으로 떨어지지 않고
    실패한다.** qlib이 체결가가 NaN일 때 경고를 찍고 종가로 대체하는 것을 명시적으로 금지한다
    (`UC-FILL-001`).

컬럼 이름에 의미가 없다
    프레임워크는 그 컬럼이 시가인지 종가인지 모른다. trade_price="D"도 성립한다. 매수/매도에
    다른 컬럼을 쓰고 싶으면 side별로 나눈다 — 공짜로 표현된다.

측정할 수 없는 것 — stale price
    trade_at=15:30인 행의 컬럼이 실제로는 09:00 관측일 수 있다. package는 알 수 없으므로 검사
    대상이 아니라 **profile의 선언된 limitation**이고, 컬럼 이름을 보고 경고하는 것은 agent의
    일이다. 정직하게 하려면 세션당 행을 둘 둔다.

이 파일의 소비자는 셋이다
    `runtime/timeline.py` · venue 구현 · `flow/preflight.py`. 그래서 타입 하나짜리 파일이지만
    남는다(architecture §10의 판정 규칙).
"""
