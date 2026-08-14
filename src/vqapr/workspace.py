"""한 project의 선언 집합이 명령 사이에서 사는 곳.

구현할 것
    Workspace          project root를 해석하고 선언을 읽고 쓴다
    담는 것
        등록된 dataset          DatasetRegistration + SourceSpec
        유도된 SessionCalendar  frozen. 어느 dataset의 어느 규칙에서 나왔는지 함께
        등록된 ComponentRef     path + config + fingerprint (`extension/`)
        Exchange config         listing · cost · 체결 테이블 선언

왜 필요한가
    `vqapr data register`와 나중의 `vqapr materialize` 사이에 선언이 살아 있어야 한다.
    `RunDefinition`의 `dataset_bindings`와 `ComponentRef`들이 **어디선가 와야 하는데** 그 어디가
    없었다.

`config/`를 만들지 않는다는 결정과 모순이 아니다

    config **타입**       소유자 옆에 산다. 이름공간으로 모으는 것은 `public.py`
    config **인스턴스**   project마다 다르므로 project를 아는 곳에 산다   ← 여기

**전역이 아니다.**
    명시적으로 전달한다. qlib의 `qlib.init()` 같은 process-global provider는 PRD §12.5가 금지한
    것이며, 그것이 있으면 동시 run이 서로의 설정을 본다.

점진적 구성을 표현한다
    PRD §12.1 — user와 agent는 instrument와 execution assumption 같은 결정을 **한 번에 모두 입력하지
    않고 점진적으로** 확정할 수 있어야 한다. agent가 "어떤 종목을 거래하나요"를 하나씩 확인하는
    대화 형태가 그것이다. 거대한 spec 생성자를 한 번에 채우는 표면만 제공하면 그 대화를 표현할 수
    없다.

run과의 관계 — workspace는 변하고 run은 동결된다

    workspace       변한다. 선언이 쌓인다
    RunDefinition   시작 시점에 동결된다. 이후 workspace 변경과 무관하다 (`UC-CONFIG-001`)

    **frozen input은 완전하다.** 실행과 재현에 workspace를 다시 읽을 필요가 없어야 하며, 암묵적으로
    다시 읽는 경로가 생기면 §12.1의 보장이 무너진다.

여기서 하지 않을 것
    검증. 무엇이 유효한 선언인지는 각 타입이 안다(`data/datasets.py`, `extension/registration.py`).
    이 파일은 **보관과 조회**만 한다.
"""
