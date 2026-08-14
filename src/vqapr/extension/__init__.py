"""extension — 네 확장점의 정문.

user가 작성할 수 있는 것은 넷이다.

    DataModel       `models/data_model.py`        내장 없음
    StrategyModel   `models/strategy_model.py`    **내장 없음 — 의도적** (PRD §2.7)
    Exchange        `exchange/venue.py`           `exchange/venues/`
    Constraint      `constraints/constraint.py`   `constraints/builtin/`

**내장도 같은 문으로 들어온다.**
    academic도 krx도 no_short도 ComponentRef로 지목되고, preflight는 그것이 내장인지 사용자
    것인지 **구분하지 않는다.** 이것이 PRD §2.7의 "built-in은 executable example"의 실체이며,
    검사 가능한 형태는 하나다 — **내장이 쓰는 API 집합 ⊆ public surface.**

**여기에 extension이 살지 않는다. extension을 검증하는 코드가 산다.**
    qlib의 `contrib/`이 반면교사다 — 확장 지점을 패키지 안에 두면 사용자 코드가 패키지에
    축적되고, 결국 그것을 읽어야 쓸 수 있게 된다(architecture §2.6).

닫힌 것
    account · valuation · orders · flow · runtime · evidence. 결과의 의미를 정의하므로 project
    마다 달라지면 두 run을 비교할 수 없게 된다.
"""
