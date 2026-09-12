# vqapr 0.6.0 호출 흐름 정리 제안

Status: 1-4와 6의 sample 절반은 기록 [`167`](../implementations/167-explicit-runtime-ownership-and-boundaries.md)이 구현했다(2026-09-07). 5는 같은 기록이 측정하고 변경하지 않기로 결정했다. 6의 나머지 — Python 표면도 같은 판정을 거친다 — 는 기록 [`168`](../implementations/168-the-python-door-asks-the-judgments-too.md)이 닫았다(2026-09-08).

근거: [호출 흐름 진단](../diagnostics/2026-09-07-v060-call-flow-review.md). 원칙은 모듈 수 목표를 새로 세우는 대신, 생성 완료 시점·상태 소유권·한 단계의 입력과 출력을 코드에서 직접 읽을 수 있게 하는 것이다.

## 권장 순서

| 순서 | 범위 | 기대 결과 | 위험 / 인수조건 |
|---|---|---|---|
| 1 | orchestration의 자원 수명 | 자원 획득부터 종료까지 정리 경계 안에 둔다 | constructor/requirements/writer-open/run/finalize 각각 실패 시 획득한 자원만 정확히 정리. 본래 예외와 flush 실패 chain 보존 |
| 2 | valuation의 callback back-reference, Workspace._commit | 쓰지 않는 연결과 private helper 삭제 | valuation/monitoring/callback 결과 불변, 실제 참조 검색 재확인 |
| 3 | FlowContext와 SimulationFlow 조립 | 필수 의존성을 constructor로 한 번에 주입 | 빈 객체 + 사후 필드 할당 제거. 잘못된 layer/account/state는 이전과 동일하게 거절 |
| 4 | phase의 오류/타이밍 wrapper | 경제적 단계가 선형 코드로 보인다 | __cause__, stage, family, owner, PRE_COMMIT / FAILED_AFTER_COMMIT, timing 의미 보존 |
| 5 | judgments/preflight 준비 중복 | 검증한 선언과 판정을 다음 단계에 전달 | blocked와 failed 구분, source edit 반영, fresh payload 복원, process별 strategy 격리 보존 |
| 6 | public/CLI acceptance와 예제 정렬 | 같은 등록 run에 대한 거절 계약을 설명하고 검증 | 원본 sample의 lookback 거절 해결. preflight의 범위를 바꾸면 공개 API 호환성 판단 필요 |

각 단계는 독립 작업으로 구현·검증한다. 이를 한 번의 전면 재작성으로 묶을 근거는 없다.

## 1. 조립 지점을 자원 수명의 소유자로 만든다

`_run_strategy`/`_run_datamodel`이 모델, account, store, state, writer, flow를 조립하는 현재 위치 자체는 타당하다. 이를 또 factory registry로 감쌀 필요는 없다.

ScanSession은 이미 context manager를 제공한다. `with ScanSession() as session`으로 획득 직후부터 보호하고, writer는 **open 성공 직후** release를 보장하는 경계에 넣는다. ExitStack 또는 짧은 try/finally로 충분하다. writer.finish가 release하는 현재 계약을 먼저 확인해 중복 seal이나 실패 가리기를 피한다. 전용 lifecycle framework는 필요하지 않다.

## 2. phase 상호참조를 걷어낸다

첫 변경은 ValuationPhase의 callback 인자/필드와 SimulationFlow의 사후 backpatch 삭제다. 이후 callback에서 필요한 committed mark는 이미 보유한 AccountState에서 읽거나 작은 순수 함수로 읽는다. getter 한 개를 위해 새로운 service/protocol 계층을 추가하지 않는다.

```text
현재: SimulationFlow → shared context
      CallbackPhase ⇄ ValuationPhase
      ExecutionPhase → ValuationPhase

1차: SimulationFlow → fully initialized context
     CallbackPhase → account state
     ExecutionPhase → valuation operation
     ValuationPhase → account state
```

ExecutionPhase가 valuation을 호출하는 것은 실제 실행 순서를 나타내므로 단순히 화살표 수를 줄이려고 제거하지 않는다.

## 3. FlowContext는 완성된 상태로 만들어진다

필수 의존성을 keyword-only constructor 또는 dataclass 필드로 선언하고 한 번에 넣는다. `context.account`와 `context.state`처럼 correctness authority인 참조는 초기화 후 교체하지 않는 계약을 만든다. timing, horizon, recorded_measurements처럼 변하는 값은 명시적인 default로 둔다.

처음부터 phase마다 dependency interface와 state DTO를 하나씩 만들면 객체 수가 늘어난다. 우선 **하나의 완전히 초기화되는 context**로 시작하고, 서로 독립적으로 바뀌는 책임이 확인될 때만 immutable dependencies / mutable bookkeeping 두 묶음으로 나눈다. Context 하나를 여러 단계가 공유한다는 사실 자체는 삭제 사유가 아니다.

## 4. 단계는 유지하고, lambda 호출 방식만 바꾼다

현재:

```python
orders = context.due_boundary(
    stage=SimulationStage.DUE_ORDER_PLANNING,
    cutoff=target_at,
    owner=intent,
    family=SimulationFailureFamily.ORDER,
    kind=SimulationFailureKind.PRE_COMMIT,
    operation=lambda: plan_orders(...),
)
```

비교할 소규모 prototype:

```python
with stage_boundary(stage=..., cutoff=..., owner=..., family=..., kind=...):
    orders = plan_orders(...)
```

이는 구현 코드가 아니라 선택지를 비교할 예시다. `plan_orders` 호출 시 wrapper의 __enter__는 이미 반환됐으므로 실제 함수의 active stack에서 `due_boundary → timed → lambda`가 빠질 수 있다. 예외 변환은 __exit__ 경로에서 유지한다. 가독성, type inference, 실패 envelope 보존을 측정한 뒤 채택한다. 모든 guard를 기계적으로 한 종류로 통합하면 callback의 특수 data-owner 판정이 사라질 수 있다.

step 이름·실행 순서를 외부 설정이나 generic pipeline DSL로 옮기는 안은 권장하지 않는다. 그것도 다시 stack과 동적 dispatch를 추적하게 만든다. `snapshot → orders → fills → account commit → mark → monitoring`을 한 함수에서 읽는 장점은 남긴다.

OccurrenceFlow는 due/static 시간 순서를 공유하는 실제 이유가 있다. 현 50여 줄 loop의 상속 제거는 우선순위가 낮다. wrapper 정리 후에도 template-method 이동이 이해를 방해하는지 비교하고 판단한다.

## 5. 반복 로딩은 객체 cache보다 준비 결과 공유로 접근한다

먼저 명확히 할 계약:

- judgments는 가능한 모든 판정과 blocked 이유를 수집한다.
- preflight는 실행 권한과 immutable 계획을 만든다.
- execution은 격리된 mutable strategy와 자원을 소유한다.

check/run이 공통 prepare 절차를 사용하고, 검증된 requirements/agenda/identity를 전달하는 정도로 시작한다. payload round-trip에 필요한 별도 fresh instance는 남긴다. 실제 실행 객체에 판정 중 변한 memory를 재사용하지 않는다.

FrozenRun 안에 로드된 모델이나 DuckDB handle을 넣지 않는다. immutable 선언과 live runtime의 경계는 유용하다. `--jobs` worker는 자기 process의 runtime을 구성해야 한다. 글로벌 module/object cache로 로더 횟수만 줄이는 안은 피한다.

목표 수치를 먼저 4→1로 정하지 않는다. 회수할 수 있는 생성과 의미상 필요한 생성을 구분하고 결과와 실패 계약이 같을 때에만 감소를 인정한다.

## 6. 넓은 재설계 후보와 후순위

- `RunResult`의 네 mapping은 실행 결과·저장 기록·worker outcome을 구분하는 이유가 있다. 장기적으로 member별 outcome 하나를 authority로 두고 기존 접근자를 projection으로 만드는 안을 검토할 수 있다. datamodel 성공/실패·in-process와 worker의 반환 정책부터 확정해야 한다.
- `record.py` 1,976줄은 모델/schema, writer/lock/buffer, reader/list를 함께 담는다. 서로 독립적인 수정이 계속 확인되면 persistence I/O와 record model을 나눌 수 있다. 파일만 다시 나누는 작업은 이번 stack 문제를 해결하지 않는다.
- `scan.observation_rows` 238줄은 분기 19개로 phase 함수와 성격이 다르다. PIT/row-grain/query 결과를 고정한 별도 리뷰가 필요하다. 실행 wrapper와 같은 방식으로 일괄 추출하지 않는다.
- 현재 optimizer, order economics, Account single-writer, PIT cutoff, intended/requested/dealt/committed 구분을 바꿔야 한다는 근거는 이번 리뷰에서 얻지 못했다.

## 구현 시 검증

반복 중에는 책임별 기존 테스트를 실행한다: `tests/flow/`, `tests/qa/test_callback_failure_carries_the_whole_envelope.py`, `tests/qa/test_run_records_survive_and_race.py`, CLI judgments/preflight tests. 자원 획득 단계별 예외 주입은 새 회귀 테스트 가치가 있다. 단순 파일 이동이나 getter 자체를 복제하는 테스트는 추가하지 않는다.

조립 또는 record를 변경한 handoff 전에는 manifest의 `uv run pytest tests/ -q -m ""`, `uv run ruff check src/`를 완료한다. Vulture 후보는 수동 분류한다. 소스 동작 변경은 implementation record가 필요하다. 릴리스까지 요청될 경우에만 build와 실데이터 showcase 게이트를 추가한다.

10-session trace는 빠른 가독성 확인에 사용하고, 경제적 동일성은 초기 상태가 같은 before/after의 의사결정, 주문, 체결, account, 표를 대조한다. 무작위 correlation id, timing, path 같은 비경제적 차이는 비교에서 명시적으로 분리한다. 리팩터링으로 wrapper 프레임은 달라지는 것이 목표이므로 모든 함수의 exact trace 동일성을 요구하지 않는다. **경제적 연산 순서와 실패 경계**가 보존되는지 확인한다.