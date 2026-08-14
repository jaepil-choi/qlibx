"""언제 계산하는가 — 닫힌 어휘, 그리고 해석하는 유일한 코드.

구현할 것
    EveryNSessions       n, local_time, timezone, 선택적 anchor
    LastSessionOfMonth   months(None이면 매월), local_time, timezone
    TriggerPolicy        위 둘의 union
    resolve(...)         TriggerPolicy x SessionCalendar -> 시점 목록

**이 변환 코드는 여기 한 벌뿐이다.**
    DataModel의 materialize와 StrategyModel의 run이 같은 함수를 부른다. 두 벌 두면 새 trigger를
    추가할 때 한쪽만 고치는 사고가 난다(architecture §4.4).

왜 두 종류가 필요한가
    "N 세션마다"와 "매월 마지막 거래일"은 서로를 표현하지 못한다. 한 달의 거래일 수가 달마다
    다르기 때문이다. Fama-French의 6월말 형성은 세션 수로 근사하면 매년 날짜가 밀린다.

왜 임의 표현을 받지 않나
    cadence는 경제적 의미이고 재현 가능해야 한다. 임의 콜백은 데이터나 외부 상태를 읽을 수
    있어 "데이터에서 cadence를 유도하지 않는다"를 우회한다.

trigger는 회전율을 말하지 않는다
    EveryNSessions(1)을 선언하고 대부분의 날 같은 목표가 나오는 것은 정상이다. 판단을 안 한
    것이 아니라 판단 결과가 같았던 것이고, 그 둘은 구분되어 기록된다. **보유기간·회전율·
    리밸런싱 주기는 선언이 아니라 결과**이며 체결 기록에서 사후에 계산된다.

Warmup은 여기 없다
    StrategyModel만 갖는 것이라 `strategy_model.py`에 있다. 공유 어휘 파일에 두면 DataModel도
    갖는 것처럼 읽힌다.

`UC-TRIGGER-001`
"""
