"""`vqapr agent install|update|remove` — onboarding.

구현할 것
    `agent/onboarding.py`를 부른다
    **dry-run preview가 기본**이고 적용은 명시적 확인 후

무엇을 건드리는가
    vqapr가 소유하는 marked block과 확인된 generated file만. instruction file의 나머지 내용이나
    project artifact를 삭제하지 않는다.

여러 target을 선택하면
    각 target의 변경을 **독립적으로** 보여주고 검증한다.

`UC-ONBOARD-001`
"""
