"""참조 — 저장된 것을 가리키는 값.

구현할 것
    ArtifactRef · ModelStateRef. 각각 대상 id + 버전 + schema identity를 갖는다.

왜 값이 여기 있고 발행은 다른 곳인가
    `PortfolioIntent`가 `model_state_ref`를 들고 다니므로 여러 층이 이 타입을 안다. 그러나
    실제로 state를 저장하고 ref를 **발행**하는 것은 `flow/model_state.py`이고, artifact를
    publish하고 ref를 발행하는 것은 `evidence/publication.py`다.

    Model이 store를 알면 자기 state를 스스로 commit할 수 있게 되어 working/committed 경계가
    무너진다(architecture §5.1.1, §10.1).

여기서 하지 않을 것
    payload의 로컬 파일 경로를 담지 않는다. 그것을 Model memory에 노출하면 durable state를
    파일 경로로 주장하는 것이 되어 PRD §12.5 금지 항목에 걸린다.
"""
