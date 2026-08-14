"""analysis — 저장된 것을 읽고 계산한다.

**규칙 하나: 새 portfolio return을 만들지 않는다.**
    가격 dataset을 읽어 weight와 곱하는 코드가 여기 있으면 그것은 척추 우회다(`UC-RETURN-001`).
    portfolio return, NAV, PnL, turnover는 explicit execution/accounting 경로에서만 산출된다.

    저장된 signal과 저장된 실현값의 상관(IC)은 return 주장이 아니므로 여기서 계산한다.

**visualization을 제공하지 않는다.**
    값과 renderer가 분리되어 있다는 것이 `UC-REPORT-001`의 요구이지, 특정 renderer를 출하하는
    것이 요구가 아니다. vqapr는 table과 machine-readable을 제공하고 chart는 user가 구성한다
    (PRD §12.4의 "report composition").

    이것이 가능한 이유는 기록 테이블과 저장된 result가 다른 dataset과 **같은 방식으로 읽히기**
    때문이다 — 시각화에 필요한 값이 이미 조회 가능한 형태로 있다.

    **의존성 목록에 plotting 라이브러리가 없는 것**이 이 경계의 검사 가능한 형태다.
"""
