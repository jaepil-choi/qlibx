"""값 -> 표현. **그림은 만들지 않는다.**

구현할 것
    table renderer             사람이 읽는 표
    machine-readable renderer  agent가 읽는 구조화 출력

**계산을 하지 않는다.**
    값은 `performance.py` `activity.py` `signal.py` `ledger.py` `diagnostics.py`가 만든다.
    계산과 표현이 한 함수에 있으면 "renderer가 달라도 underlying value와 lineage가 같다"가
    **구조적으로 보장되지 않고 우연이 된다**(`UC-REPORT-001`).

**plotting 의존성을 갖지 않는다.**
    chart는 user가 같은 값 위에 구성하는 renderer다(PRD §12.4의 "report composition").
    agent가 first-class user이므로 machine-readable 표현이 우선순위를 갖는다 — agent는 PNG보다
    표를 읽는다.

stored result를 재실행 없이 report한다
    producer를 다시 돌리지 않고 저장된 것만 읽는다(`UC-REPORT-001`, `UC-REPORT-002`).
"""
