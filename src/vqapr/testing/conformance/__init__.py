"""conformance — 계약을 지키는지 판정한다.

**입력은 `ComponentRef`다.**
    내장이든 사용자 것이든 같은 타입으로 들어오므로 **차별할 분기점이 존재하지 않는다.**
    `academic`과 `krx`가 이 suite를 통과하는 첫 두 구현이고, `no_short`와 `single_name_cap`이
    그 다음이다.

**세 경로가 같은 코드를 부른다.**
    pytest              사용자가 `my_strategy/`에서 돌린다
    vqapr check         agent가 읽는 기계 판독 결과
    vqapr register      등록 전 관문 (`extension/registration.py`)

    갈리면 *"로컬에선 되는데 등록이 안 된다"*가 생긴다.

여기가 유일한 계약 검사다
    `extension/`에 별도 검증 모듈을 두지 않는다. 검사가 두 곳에 있으면 반드시 어긋난다.
"""
