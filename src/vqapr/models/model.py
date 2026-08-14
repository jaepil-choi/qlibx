"""Model 공통 계약.

구현할 것
    Model (ABC)
        memory        ModelMemory. 기본 None
        recorder      write-only Recorder (`evidence/recorder.py`)
        trigger()     -> TriggerPolicy. **언제 계산하는가를 정의가 스스로 말한다**
        requirements() -> tuple[DataRequirement, ...]
        tables()      -> tuple[TableSpec, ...]. 기록할 것을 미리 선언
        save_payload(target) / load_payload(source)   기본 구현은 no-op

왜 trigger가 Model에 있나
    PRD §3.3 — "정의만 읽고 cadence를 알 수 있어야 한다." run script에 두면 같은 Model이
    스크립트마다 다른 것이 된다.

payload hook이 받는 것은 열려 있는 대상뿐이다
    Model은 그것이 어디에 쓰이는지 모른다. 열고 닫고 ModelStateRef를 발행하는 것은
    `flow/model_state.py`다. Model이 store를 알면 자기 state를 스스로 commit할 수 있게 되어
    working/committed 경계가 무너진다(architecture §5.1.1).

여기서 하지 않을 것
    state를 commit하지 않는다. 시간을 진행시키지 않는다. 자기를 호출하지 않는다.
"""
