"""실패를 기계가 읽을 수 있게 한다.

구현할 것
    VqaprError      hierarchical stage path (예: "dataset.register.key_uniqueness")
                    충족되지 않은 requirement id와 bounded diagnostic
                    state/artifact가 commit되었는지 여부
                    retry 전에 충족해야 할 precondition과 idempotency 정보
                    correlation id
    FailureFamily   DATA_* CALENDAR_* INTENT_* ORDER_* EXCHANGE_* ACCOUNT_*
                    VALUATION_* PUBLICATION_*

mutation 여부가 왜 필수인가
    architecture §8.3 — commit 전 실패는 아무것도 바꾸지 않고, VALUATION_*만 Fill이 이미
    commit된 뒤일 수 있다. 이 구분이 없으면 안전한 retry를 판단할 수 없다.

여기서 하지 않을 것
    **resolution 후보나 user에게 물을 질문을 담지 않는다.** package는 deterministic하게
    판정하고, 그 error를 해석해 복수의 해결 경로를 만드는 것은 agent layer다(PRD §2.6).
    사용하지 않은 optional stage는 stage path에 나타나지 않는다(`UC-ERROR-001`).
"""
