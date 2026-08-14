"""run의 입력과 출력.

구현할 것
    RunDefinition
        run_id, strategy(ComponentRef), exchange(ComponentRef), account_mode,
        calendar, start, end, initial_account, initial_state_ref,
        dataset_bindings, policies,
        constraints: ConstraintSet | None       판단·검증·monitoring이 함께 본다
        monitoring: MonitoringPolicy | None     TriggerPolicy. decision cadence와 독립
    RunResult
        최종 actual state, 최종 Model state, evidence refs, **limitations**
    RunStatus   상태 기계
        CREATED -> PREFLIGHTED -> RUNNING -> FINALIZED
        DECISION -> DECISION_SKIPPED(warmup)   기록하고 다음 candidate로
        DECISION -> INTENT_FROZEN -> EXECUTION_READY -> FILLS_PRODUCED
                 -> ACCOUNT_COMMITTED -> MARKED -> FEEDBACK_PUBLISHED
        commit 전 실패      -> FAILED_WITHOUT_MUTATION
        commit 후 발행 실패 -> FAILED_AFTER_COMMIT(account_version 기록)

왜 limitations가 RunResult에 있나
    profile realism, 유도된 calendar/tradability 규칙, 미모델링 항목은 frozen input과 profile
    선언에 이미 있다. 나중에 재구성하게 두면 **result만 보고는 한계를 알 수 없는 상태**가
    생긴다. finalize에서 확정한다(architecture §3.6).

왜 constraints가 여기 있나
    전략이 소유하면 monitoring이 자기 사본을 갖게 되고 둘이 갈라진다. 그리고 생산 검증이
    독립적이려면 선언이 전략 바깥에 있어야 한다(architecture §5.7).

동결 후 project config 변경은 이 run에 영향을 주지 않는다
    `UC-CONFIG-001`.

중단된 run의 재개는 현재 범위 밖이다
    실패하면 처음부터 다시 실행한다. 한 Model invocation 안의 checkpoint 재개는 별개다
    (`UC-RECOVERY-001`은 future).
"""
