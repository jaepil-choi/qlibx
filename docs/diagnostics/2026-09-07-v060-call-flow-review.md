# vqapr 0.6.0 호출 흐름 리뷰 — 2026-09-07

## 범위와 근거

기준 HEAD: `7d2ab0ee`, pyproject version `0.6.0`. 리뷰 도중 `src/vqapr/declarations.py`에 사용자 수정이 있었으며 보존했다. 수치는 pristine tag가 아니라 측정 시점 working tree 기준이다.

전 src의 AST inventory, configured Vulture, Ruff, 실행 경로 중심 소스 읽기, 기존 관련 테스트 읽기, 실제 CLI profile, 생성자 실패 주입을 수행했다. **115개 Python 파일 / 33,411줄**(빈 줄·주석 포함). 모든 함수의 의미와 모든 실행 분기를 감사한 것은 아니다.

계약은 `.agent/project.yaml`이 지정하는 PRD, surface design, diagnostics index, one-shape campaign과 architecture §17을 대조했다. 예전 진단의 미해결 목록을 현재 결함으로 재사용하지 않았다. 기존 캠페인의 import cycle 제거와 파일 통합은 객체 소유권이나 실행 stack 단순화와 다른 측정이다.

## 실제 실행

원본 `agent.sample.journey.install()`로 등록한 `sample-run`을 CLI로 실행하면 `check.lookback.uncovered`에서 거절됐다. 첫 관측은 2022-01-03 15:30, 첫 결정은 같은 날 08:00, lookback은 6행이다. sample `execute()`는 CLI judgments를 거치지 않고 public preflight/run을 직접 호출한다. 두 진입점의 acceptance 차이가 실제로 노출된 사례다. 이 실행을 성공 trace라고 세지 않았다.

준비된 동일 데이터에서 첫 10세션을 이력으로 남기고, 다음 **10세션**만 실행하는 별도 `review-bounded`를 등록했다. CLI `run.complete`, account_version 10, accepted intents 10, orders 42, dealt 36, no_trade 6. 원본 등록은 그대로 두었다.

`sys.setprofile`의 package 내부 call events 기준: **66개 파일 / 660개 서로 다른 code label**. label에는 lambda·generator·class body도 포함하므로 660개 business function이라는 뜻이 아니다. 외부 라이브러리 프레임은 제외했고 등록·데이터 준비는 profile 밖이다. 이 숫자는 성능 benchmark나 전체 경로 coverage가 아니다.

핵심 데이터 흐름(중간 wrapper 생략):

```text
CLI.run
  judgments → preflight → FrozenRun
  orchestration.run → _run_strategy
    load strategy / exchange / constraints
    ScanSession → DuckDbObservationStore
    AccountState → RunStateRepository
    Account + ModelWindow factories → SimulationFlow
      OccurrenceFlow.run
        callback occurrence
          CallbackPhase.dispatch
            ModelWindow → StrategyModelContext → strategy.decide
            Hold 또는 Rebalance → stamp → accepted pending + model state
        due occurrence
          ExecutionPhase.execute_due
            execution snapshot → plan_orders → exchange.execute
            Account.prepare_fill → commit_fill → run-state publication
            valuation / monitoring → evidence rows
    RunRecordWriter → parquet + strategy record
```

실제 첫 `decide`의 package stack은 13프레임, `plan_orders`와 `Account.prepare_fill`은 각각 **17프레임**이었다. 후자의 경로:

```text
main → CLI.run → orchestration.run → _run_strategy
→ SimulationFlow.run → OccurrenceFlow.run → _dispatch_due
→ timed → lambda → guard → lambda → _dispatch_pending
→ execute_due → due_boundary → timed → lambda → plan_orders
```

## 관측된 문제

### R1. 생성 중 실패가 자원 정리를 건너뛴다 — correctness, 우선순위 높음

`flow/orchestration.py:559`에서 ScanSession, `573`에서 writer.open, `588`에서 SimulationFlow를 만들지만 보호하는 try는 `632`부터다. requirements 검사, state 구성, Account/SimulationFlow 생성 중 실패하면 아래 release/finally에 도달하지 않는다. datamodel도 `433–454`에 같은 구조가 있다.

**실패 주입 결과:** SimulationFlow 생성자가 ValueError를 던지도록 한정 patch했을 때 sessions_created=1, writers_opened=1, session_close_calls=0, writer_release_calls=0. probe가 측정 후 직접 정리했다. constructor 실패는 실제 생성자의 여러 validation과 사용자 account_history 호출로도 발생할 수 있는 분기다.

확인한 결함은 cleanup 누락이다. 이 주입은 flow 실행 이전이므로 열린 DB connection 개수나 영구적인 메모리 누수를 입증하지 않는다. writer claim의 명시적 release가 생략되고 객체/프로세스 수명에 복구를 맡긴다는 문제는 남는다. datamodel 분기는 정적으로 확인했으며 별도 주입은 하지 않았다.

### R2. 사용하지 않는 back-reference와 불완전한 객체 구성 — 직접 삭제 가능한 smell

`flow/simulation.py:196–198`:

```python
self._valuation = ValuationPhase(self._context, None)
self._callback = CallbackPhase(self._context, self._valuation)
self._valuation._callback = self._callback
```

`flow/valuation.py:106–108`은 callback을 저장하지만 valuation의 다른 메서드는 그 필드를 읽지 않는다. `TYPE_CHECKING` import를 없앤 것과 실제 instance 참조를 없앤 것은 다르다. 현재는 의미 없는 양방향 연결과 type ignore가 남아 있다.

반대쪽 `CallbackPhase → ValuationPhase`도 `callback.py:394`의 `committed_mark()` 한 호출이다. 그 메서드는 `valuation.py:404`에서 `state.current.account.latest_mark`를 반환한다. phase 전체를 참조할 이유가 매우 좁다. 전역 `_callback` 이름 사용 여부를 세는 Vulture는 이런 class-specific 무사용 필드를 놓칠 수 있다.

### R3. FlowContext의 타입과 초기화 계약이 생성자에 드러나지 않는다 — 구조 문제

`flow/context.py:452–480`의 빈 생성자는 frozen_run, layer, state, account, strategy 등을 annotation만 하고 실제 값을 채우지 않는다. `simulation.py:96–222`의 127줄 생성자가 외부에서 필드를 하나씩 설정한다. 이후 세 phase가 같은 context를 받는다.

따라서 FlowContext() 직후 사용 가능한 필드를 생성자만 보고 알 수 없다. 고정 의존성, state authority, timing·horizon cache가 같은 객체에 있다. 단, 실제 상태의 다중 writer 버그를 증명한 것은 아니다. Account/RunStateRepository의 commit 경계를 공유 객체라는 이유만으로 제거해서는 안 된다.

### R4. 선형 실행을 고차함수 wrapper로 표현해 stack이 길어진다 — 가장 직접적인 가독성 문제

`CallbackPhase.dispatch`는 192줄, `ExecutionPhase.execute_due`는 296줄이다. AST에서 센 if/for/while/except/if-expression/match 노드는 각각 6개와 4개다(정식 cyclomatic complexity 점수 아님). 특히 execute_due는 분기 알고리즘보다 단계 metadata, lambda, publication 준비가 길이를 차지한다.

10 callback 실행에서 guard 92회, timed 170회, callback_intent_boundary 80회, due_boundary 150회였다. 17프레임 가운데 `timed → lambda → guard → lambda`와 `due_boundary → timed → lambda`가 삽입된다.

이 wrapper는 실패 단계·원인·체결 전후와 timing을 보존한다. 필요 없는 것은 경계 자체라기보다 경계를 매번 함수 호출의 인자로 표현하는 방식일 수 있다. 깊은 stack만으로 runtime overhead가 크다고 결론 내리지는 않는다.

### R5. 판단·동결·실행이 같은 extension을 반복 생성한다 — 합치기 전 의미 확인 필요

이번 CLI 실행에서 `load_strategy_model` 4회:

1. `judgments._judge_member_datasets` — 요구 데이터 판정.
2. `preflight._freeze_strategy` — frozen requirements 구성.
3. `preflight._validate_initial_model_state` — 별도 fresh instance로 payload round-trip 검증.
4. `orchestration._run_strategy` — 실제 실행 객체.

Exchange loader는 preflight와 execution에서 총 2회. `_load`는 호출할 때마다 fingerprint를 계산하고 `exec_module` 후 constructor를 부른다(`extension/loading.py:55–114`). 모듈 이름을 sys.modules에 넣지만 여기서는 이미 로드된 객체를 반환하는 cache가 아니다.

**4회 모두 중복이라는 판단은 틀리다.** 3번은 fresh-instance 재구성 검증이고 실행 객체도 mutable memory/payload를 가진다. 공유하면 의미가 달라질 수 있다. 그러나 judgments와 preflight가 판정 결과/선언을 넘기지 않고 사용자 코드를 다시 읽고 생성하는 구조는 통합 후보다. 글로벌 singleton cache는 source edit 반영과 전략 격리를 훼손할 수 있다.

`RunResult` 역시 전략에서는 results/records/outcomes/errors 네 mapping을 채우고 datamodel에서는 outcomes가 비어 있다(`orchestration.py:334–386`). 빈 outcomes에 대한 all()로 ok가 True가 되는 현상은 표현상의 비대칭이다. datamodel 실패가 현재는 raise하므로 이를 곧바로 실패를 성공으로 보고하는 버그라고 부르지는 않는다.

### R6. Vulture: 작은 잔여물은 있지만 대규모 삭제 근거는 아니다

configured `uv run --no-sync vulture`: **23건**, 대부분 confidence 60%.

- `workspace.py:499`의 `_commit`: src/tests 호출 검색에서 호출자 없음. 직접 등록 문 제거 후 남은 private helper 후보.
- `record.py`의 declared_digest 3건, `report/document.py` 필드 15건: record/report의 직렬화 표면. 이름을 dot access로 읽지 않아도 model construction/dump가 사용한다. 삭제 근거가 아니다.
- `workspace_document.py:356`의 strategy_configs: 구형 문서 호환 필드이며 문자열 exclude에도 사용. 삭제 근거가 아니다.
- `workspace.py:1268`의 tb: context-manager signature의 traceback argument. 미사용 자체는 dead business code가 아니다.
- 테스트의 `_Evidence`, `_decision`: 테스트 정리 후보이며 src 구조를 설명하지 않는다.

public export·외부 사용자·plugin 동적 로딩은 Vulture가 입증할 수 없다. 테스트만 읽는 코드 역시 제품에서 불필요한지 별도 판단해야 한다.

### R7. 문서/예제의 실행 설명이 현재 제품과 어긋난다

원본 sample의 CLI 거절은 위에서 재현했다. sample install→public execute와 install→CLI run이 같은 acceptance 경로가 아니다. 이는 예제의 경로 대표성을 제한한다.

`orchestration.py:578` 부근은 killed run이 마지막 accepted occurrence까지 보존된다고 설명하지만, 현 writer의 `record.py:918` 이후 계약은 정상/예외 종료 flush + spill이며 hard kill은 미spill buffer를 잃는다(record 164). diagnostics index와 architecture §17에도 과거 상태가 남아 있다. 긴 역사적 docstring을 현재 동작으로 읽으면 코드 흐름을 더 어렵게 이해하게 된다.

## 검증과 한계

- 성공 CLI profile와 생성자 실패 주입을 모두 실행했다.
- Ruff는 실행 당시 사용자 수정 중인 declarations.py:179의 E501 1건으로 실패했다. 리뷰가 소스를 수정하지 않았으며 이 파일을 고치지 않았다. 리뷰 도중 사용자가 계속 수정할 수 있으므로 최신 lint 상태라고 일반화하지 않는다.
- 기본 uv cache는 os error 5로 거절되어 workspace `.agent/uv-cache`를 사용했다. 최초 TemporaryDirectory 경로 접근 문제 뒤 일반 task-owned 폴더로 바꿨다. 초기 실데이터 준비 시도는 중단했고, 이후 준비된 데이터로 bounded run을 완주했다.
- 전체 regression suite는 실행하지 않았다. production 수정 없는 리뷰이며 full-suite 성공을 주장하지 않는다. 병렬 worker, datamodel 실행, payload failure 전 분기, constraint-heavy 전략은 runtime coverage 밖이다.
- 원시 trace, 재현 probe, 실패 주입 결과, 원본 sample 거절, 성공 envelope는 `v060-review-evidence/`에 있다. probe는 repo root에서 실행하며 기존 local warehouse가 필요하고 task-owned `.agent/runs/v060-call-flow-review/`만 생성한다. 계정·데이터 원본을 수정하지 않는다.

설계 선택과 적용 순서는 별도 [리팩터링 제안](../refactoring/2026-09-07-v060-call-flow-proposal.md)에 둔다.