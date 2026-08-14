"""`vqapr data ...` — dataset 등록과 조회.

구현할 것
    register   SourceSpec + DatasetRegistration을 검증하고 project에 기록
    inspect    등록된 dataset의 binding, coverage, available_at 규칙을 보여준다

여기서 하지 않을 것
    **availability를 추측하지 않는다.** `DATE`를 자동으로 00:00으로 해석하지 않으며, 근거가
    확인되기 전에는 `available_at`으로 간주해 등록하지 않는다. 후보를 제시하는 것은 agent의
    일이다(`UC-AGENT-001`).

    등록된 값이 point-in-time으로 안전한지 판정하지 않는다. 보장하는 것은 **선언된 availability의
    준수**뿐이다(PRD §3.2).
"""
