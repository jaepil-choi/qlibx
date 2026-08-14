"""Model state의 JSON 부분.

구현할 것
    ModelMemory       bool | int | float | str | list | dict | None 의 재귀 타입
    normalize_memory  비유한 수치와 문자열 아닌 key를 거부하고 **detached deep copy**를 만든다

왜 detached copy인가
    스냅샷 이후 Model이 in-place로 memory를 바꿔도 과거 스냅샷이 바뀌면 안 된다. 그러면
    committed state가 사후에 달라진다(architecture §16).

memory와 payload는 하나의 state identity다
    memory      진행 위치, 최근 시점, 작은 계수처럼 사람이 검사할 수 있는 구조적 상태
    payload     신경망 weight처럼 JSON으로 표현하기 부적합한 Model 고유 상태

    둘은 함께 저장·복원된다. payload hook은 `model.py`에 있고 저장은 `flow/model_state.py`다.

숨은 durable state를 금지한다
    다음 invocation의 결과에 영향을 주는 mutable attribute는 memory 또는 payload에 반드시
    포함되어야 한다. Model을 새로 만들고 committed state를 복원해도 같은 결과가 나와야 한다.
    전략 파라미터(n, threshold)는 immutable configuration이므로 state가 아니다.

`UC-STATE-001` `UC-STATE-002`
"""
