"""언제부터 이 관측을 쓸 수 있는가 — 추측하지 않는다.

구현할 것
    AvailabilityBinding   직접 컬럼 지정 또는 user가 선언한 지연 규칙
    검증                  형식 · coverage · PIT consistency를 deterministic하게

**DATE를 자동으로 00:00으로 해석하지 않는다.**
    DATE를 available_at으로 바로 binding할 수 있는 것은 user가 그 값이 실제 공개 시각이라고
    확인한 경우뿐이다. 별도 availability field가 없으면 agent가 후보 규칙과 각각의 look-ahead
    영향을 설명하고 user가 근거를 확인해 선택한다(PRD §4.2, `UC-AGENT-001`).

`runtime/calendar_derivation.py`와 대칭이다
    package는 추측하지 않는다 -> user가 근거와 함께 선언 -> package가 결정적으로 검증 ->
    규칙이 frozen input에 남는다. 두 파일이 같은 모양이어야 그 원칙이 하나임이 보인다.

계산 결과의 available_at은 여기 오지 않는다
    DataModel이 만든 데이터의 available_at은 생산자가 주장하지 않고 package가 정한다.
    그 계산은 `flow/materialize.py`에 있다(architecture §4.5).
"""
