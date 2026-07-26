# qlibx Architecture Critical Review

## 1. 문서의 지위

이 문서는 [`qlibx-architecture-old.md`](qlibx-architecture-old.md)를 [`qlibx-prd.md`](qlibx-prd.md) 요구사항 기준으로,
그리고 `qlib-integration-codex/`(prototype, `architecture.md`·`critical-review.md`·실제 소스 약 31,655줄)를
증거로 비판적으로 검토한 기록이다. 아직 `qlibx` 자체의 실제 코드는 없으므로 이 리뷰는 "구현이 architecture를
어겼는가"가 아니라 "이 architecture가 PRD를 달성 가능한 계획인가, prototype이 이미 알려준 위험을 제대로
반영했는가"를 판단한다.

결론부터 말하면, hexagonal 경계와 canonical contract(7장), guardrail(17장) 설계는 견고하고 prototype의 실패
사례(여러 catalog, custom bar scheduler, test harness의 production 승격)를 정확히 짚어 배제했다. 그러나 다음
세 가지는 architecture 문서 수준에서 아직 미해결이며, 특히 1번은 전체 migration의 최대 기술 위험인데도
7장의 canonical contract가 아니라 18장의 "review가 필요한 선택" 목록 한 줄로 축소되어 있다.

1. PRD의 핵심 차별점인 signed alpha × Qlib native execution(P6)을 구현하는 두 mechanism 중 어느 것도 아직
   같은 코드 경로에서 함께 증명된 적이 없다.
2. Catalog를 하나로 통합하는 결정은 옳지만, 통합된 catalog의 schema 표면이 prototype이 스스로 배운 "lean
   core table" 교훈보다 훨씬 넓어 같은 복잡도를 다른 형태로 재생산할 위험이 있다.
3. P0(agent onboarding)는 prototype에 선례가 전혀 없는 완전히 새로운 서브시스템인데, 나머지 7개 bounded
   context와 동일한 "1차 버전 범위"로만 서술되고 phasing이나 우선순위가 없다.

## 2. 최우선 위험: matched-capitalization과 native Qlib lifecycle의 미검증 조합

### 2.1 근거

- `qlib-integration-codex/critical-review.md` §13은 이미 다음을 명시한다: 기존 `QlibClosedLoopBackend.run_targets()`는
  Qlib `Exchange`/`Account`를 쓰지만 자체 `for date` loop가 `Order.deal_order()`를 직접 호출하므로 진짜
  `BaseStrategy.generate_trade_decision()` migration 증거가 아니다. 진짜 native lifecycle 증거는
  `peer_momentum_runtime/strategy.py`의 `QlibPeerMomentumStrategy(BaseStrategy)`뿐이다.
- `matched_capitalization`(signed alpha를 Qlib long-only account에서 실행하는 compatibility hack, PRD §11.2~11.6)은
  `kwam_qlib_backend/`에만 있고, `peer_momentum_runtime/*.py`(native twin) 전체에서 `matched_capitalization`
  또는 `MatchedCapitalization` 문자열이 한 번도 등장하지 않는다(grep 확인).
- 즉 prototype이 실제로 증명한 것은 "custom loop 위의 matched-capitalization"과 "native `BaseStrategy`
  위의 long-only peer momentum" 두 개의 서로 다른 결합이며, PRD가 요구하는 "native `BaseStrategy` 위의
  matched-capitalization signed execution"은 어느 코드에도 존재하지 않는다.

### 2.2 architecture 문서에서의 취급

`qlibx-architecture-old.md` §10.5는 target이 native Qlib scheduler/`BaseStrategy` lifecycle을 쓴다고 명확히
선언하고, §10.6은 matched-capitalization의 8단계 bar sequence를 정의한다. 그러나 이 둘을 "하나의 bridge"로
연결하는 구체적 hook(예: `strategy_bridge.py`가 매 bar마다 baseline activation → composite target 계산 →
`TradeDecisionWO` 생성을 어떤 순서로 Qlib에 노출하는지)은 정의하지 않는다. §18의 review 항목 6번
("Matched-capitalization을 native Qlib lifecycle에 연결할 최소 adapter hook과 지원 Qlib version")이 이
공백을 인지는 하고 있지만, 7개 review 항목 중 하나로 나열되어 "config 이름 정하기"나 "report section 정하기"와
같은 우선순위로 취급된다.

### 2.3 왜 이게 나머지 항목과 다른가

> **[2026-07-24 수정]** 이 절의 초판은 "`BaseStrategy.generate_trade_decision()`이 한 bar에 하나의
> `TradeDecisionWO`만 반환하므로 baseline endowment와 active order를 같은 bar에 어떻게 나눠 제출할지가
> Qlib API 차원에서 막혀 있을 수 있다"고 주장했다. 다른 agent의 재검토에서 이 근거가 틀렸다는 지적을
> 받고 코드로 재확인했다: 설치된 `.venv/Lib/site-packages/qlib/backtest/position.py:390`의
> `Position.update_order(order, trade_val, cost, trade_price)`는 `Exchange` fill을 거치지 않고 `Position`을
> 직접 mutate할 수 있고, prototype의 `kwam_qlib_backend/backend.py:1059`(`_apply_capitalization`)는
> 실제로 이 경로로 baseline quantity/cash를 zero-cost로 반영한 뒤, 진짜 active BUY/SELL만 `Exchange`를
> 통과하는 order로 제출한다. 즉 "한 bar에 decision을 두 번 내야 한다"는 전제 자체가 prototype의 실제
> 구현과 다르므로 이 문장은 근거로서 틀렸다. 아래는 정정한 내용이다.

- P6는 PRD가 명시하는 이 product의 존재 이유("Qlib의 order/fill/account lifecycle에서 signed alpha를
  실행"; PRD §1.1, §11)다. 여기가 막히면 P5(ensemble/enhanced index)까지의 모든 mechanism이 "실행할 수
  없는 research 결과물"로 남는다.
- 16.2의 "반드시 유지할 high-risk acceptance" 목록에 matched-capitalization의 NAV neutrality와 `A = C - B`는
  있지만, "native `BaseStrategy` 내부에서 baseline activation이 가능한가"라는 더 근본적인 feasibility
  질문은 없다. 다만 이 질문이 막혀 있는 이유는 "한 bar에 decision을 하나만 낼 수 있어서"가 아니라, 다음
  질문들이 아직 어느 코드에서도 native `BaseStrategy` lifecycle 위에서 검증된 적이 없기 때문이다.
  - `account.current_position.update_order()`(또는 동등한 direct mutation)가 `BaseStrategy` lifecycle의
    어느 hook(`generate_trade_decision()` 진입 시점, `post_exe_step()` 이후 등)에서 안전하게 호출될 수
    있는가.
  - Exchange fill을 우회하는 이 direct mutation이 Qlib의 `PortfolioMetrics`, `accum_info`, 누적
    return/cost/turnover 계산을 왜곡하지 않는가.
  - Capitalization journal(baseline sidecar)의 checkpoint와 Qlib account checkpoint가 원자적으로 같은
    시점에 저장/복원되는가.
  - Resume 이후, 그리고 partial/blocked fill 이후에도 `A = C - B`가 유지되는가.
  - `Position.update_order()`처럼 public이지만 execution lifecycle을 우회하는 API가 qlibx가 지원하려는
    Qlib version 범위에서 안정적인 공개 계약인가, 아니면 내부 구현 세부사항에 의존하는 것인가.

### 2.4 권고

이 조합을 최소 fixture(예: 종목 1~2개, bar 5~10개)로 spike하여 native `BaseStrategy` 안에서 baseline
activation(direct position mutation) + composite order 제출 + checkpoint/resume이 위 다섯 질문을 만족하며
동작하는지 확인하는 작업을 architecture 확정 **이전**의 gate 0으로 승격해야 한다. "제출 자체가 가능한가"는
prototype 코드로 이미 답이 나와 있으므로 spike의 진짜 목적은 "제출이 가능하다"가 아니라 "제출이 lifecycle,
metrics, checkpoint와 일관되게 안전한가"를 확인하는 데 있다. 이 결과에 따라 §10.5/§10.6과 §7장 canonical
contract가 바뀔 수 있으므로, 지금 이 사실을 모르는 채로 나머지 architecture(package layout, catalog schema
등)를 고정하는 것은 순서가 바뀐 것이다.

## 3. Catalog 통합이 실제로 복잡도를 줄이는지 재검토

### 3.1 근거

`qlib-integration-codex/research/architecture.md` §8은 prototype이 이미 한 번 "catalog를 무겁게 만들었다가
줄인" 경험을 기록한다. 결론은 "core table은 세 개(`runs`, `metrics`, `members`)만 두고, pair correlation·trade
crossing matrix·상세 provenance는 core table에 넣지 않고 필요할 때 artifact에서 계산한다"였다. 즉 prototype이
스스로 배운 lesson은 "catalog는 identity/검색 index로만 쓰고, 무거운 것은 artifact로 유지"다.

`qlibx-architecture-old.md` §6.8은 하나의 catalog에서 다음을 모두 query 가능해야 한다고 요구한다: project/dataset
정의와 snapshot, component/strategy 정의, session/proposal/run attempt, artifact와 lineage, metric/comparison/
orthogonality, research decision과 supersede relation. 이는 prototype이 具現했던 `RunCatalog`(`qlib_extended/store.py`),
`DataCatalog`(`qlib_extended/research/catalog.py`), `AlphaPoolCatalog`(`qlib_extended/research/pool.py`),
`ParquetResearchCatalog`(`kwam_qlib_backend/research_graph.py`) 네 개를 합친 것보다도 넓은 schema 표면이다.

### 3.2 문제

§4.2("Control plane과 data plane을 분리한다")와 §17 guardrail("여러 catalog와 manifest schema를 병렬
유지하는 방식")은 정확히 옳은 원칙이다. 하지만 "catalog가 하나다"는 것과 "catalog schema가 lean하다"는 것은
다른 속성이다. Identity와 publication rule이 여러 개로 나뉘어 있던 문제(semantic 불일치)를 고치면서, 그
대가로 단일 catalog의 schema가 넓어지면 §12(parallel-agent publication)에서 이 catalog 하나가 모든 bounded
context—project 등록, dataset 등록, alpha 연구, ensemble, portfolio, execution—의 publish가 거쳐야 하는
단일 serialization point(§12.2, DuckDB single-writer)가 된다.

> **[2026-07-24 수정]** 초판은 이를 "§4.2가 경계하는 것과 본질적으로 같은 종류의 결합"이라고 표현했는데,
> 이는 과장이다. DuckDB는 read-write 접속을 하나의 process 안에서만 허용하는 것이 공식 concurrency
> model이므로([DuckDB concurrency](https://duckdb.org/docs/current/connect/concurrency)), 여러 bounded
> context의 publish가 하나의 writer를 거치는 것은 그 자체로 architecture 결함이 아니라 DuckDB를 선택한
> 이상 필요한 **operational coordination**이다. 반면 "여러 catalog가 서로 다른 identity/publication
> rule을 가지는 문제"(§3.1, prototype의 실제 실패 사례)는 **semantic inconsistency**이며 이 둘은 다른
> 종류의 문제다. 그래서 "single writer를 없애야 한다"는 결론은 틀렸고, 올바른 결론은 "single writer가
> 존재하는 것은 맞지만, 그 writer가 처리하는 transaction을 작게 유지해 병목이 되지 않게 해야 한다"는
> 쪽으로 좁혀야 한다.

### 3.3 권고

§6.8을 "이 6개 entity를 하나의 catalog에서 query할 수 있어야 한다"는 관측 가능한 요구사항으로 유지하되,
prototype의 lean-core 교훈을 명시적으로 재적용해야 한다: 어떤 column이 hot-path identity/조회용 core
table이고, 어떤 것이 artifact에서 derive해 필요 시 materialize하는 view/cache인지 §6.8이나 §7.2에서
구분해 문서화한다. 그렇지 않으면 orthogonality(semantic/empirical/incremental, PRD §9.5)처럼 원래도 무거운
개념이 core catalog table로 그대로 들어가 §12.2의 "짧은 catalog transaction"이라는 전제를 깨뜨릴 위험이
크다.

## 4. Onboarding/agent-facing surface는 선례 없는 신규 서브시스템인데 phasing이 없다

### 4.1 근거

Prototype 전체(약 31,655줄, `tests/` 포함)에서 `managed block`, `SKILL.md`, 또는 instruction file을
idempotent하게 append/update하는 코드는 전혀 없다(grep 결과 "idempotent"가 언급되는 4개 파일은 모두 catalog
publish idempotency 테스트이며 onboarding과 무관). 실제 CLI(`qlib_extended/cli.py`)도 `run`/`report`/`ensemble`
세 subcommand뿐이며 `--help` 이상의 machine-readable schema나 error-code lookup은 없다. `qlibx-architecture-old.md`
§3.2도 P0을 "낮음"으로 정직하게 평가한다.

### 4.2 문제

그런데 §8(package layout)과 §11(agentic workflow), §6.10은 onboarding/documentation을 `data`, `strategy`,
`research`, `ensemble`, `portfolio`, `execution`, `artifact`, `reporting`과 동일한 층위의 bounded
context/module로 나열한다. PRD도 P0을 acceptance criteria 표의 첫 행에 두지만 우선순위라고 명시하지는
않는다. 결과적으로 architecture 문서에는 "이미 mechanism이 검증된 7개 영역을 hexagonal 경계 안으로
재배치하는 작업"과 "prototype에 단 한 줄의 선례도 없는 새 서브시스템(instruction file parser/writer, skill
template engine, versioned JSON Schema exporter, error-code catalog)을 처음부터 설계하는 작업"이 구분 없이
같은 "1차 버전 범위"로 섞여 있다. 전자는 재구성(risk가 구조 변경에 있음)이고 후자는 순수 신규 개발(risk가
요구사항 자체의 불확실성에 있음)이므로 같은 계획 단위로 묶으면 일정과 위험 추정이 왜곡된다.

### 4.3 권고

18장에 "몇 개 bounded context를 먼저 완성하고 어떤 순서로 확장할지"를 review 항목으로 추가하거나, 최소한
"prototype에서 이미 mechanism이 검증된 영역"과 "qlibx에서 처음 설계하는 영역"을 구분하는 표를 §3.2 옆에
하나 더 두는 것을 권한다. 이미 §3.2 표의 "확인된 evidence" 열이 사실상 이 구분을 암시하고 있으므로, 이를
명시적인 순서 결정으로 승격하면 된다.

## 5. Nested child research의 resource bound가 optional로 남아 있다

### 5.1 근거

§6.3(Strategy 소유 정보)은 "Optional child-research resource limit"이라고 명시한다. PRD §7.3~7.4는 child가
ML retraining, 여러 historical rule/model 비교, Bayesian belief update 등 임의로 깊이 nesting될 수 있다고
서술하며, §9.7(parallel-agent)은 최소 3개 agent가 동시에 독립 session을 실행한다고 요구한다.

### 5.2 문제

"Child는 parent보다 넓은 scope를 가질 수 없다"(§4.4, §6.3)는 시간/데이터 경계이지 계산량 경계가 아니다.
Child가 child를 spawn하는 재귀 구조(§6.4의 "child evaluation은 별도의 bounded runtime tree")에서 fan-out이나
depth의 **기본값 있는 상한**이 없으면, 하나의 잘못 구현된 StrategyAgent(특히 §15 roadmap의 AI-driven
strategy)가 공유 branch에서 실행 중인 여러 agent session의 자원을 소진시킬 수 있다. 이는 §17 guardrail
목록에 없는 drift 유형이다.

### 5.3 권고

> **[2026-07-24 보강]** 다른 agent의 재검토도 이 항목을 독립적으로 유효하다고 확인했다. "Limit capability가
> optional"인 것과 "limit 값이 없어서 사실상 무제한"인 것을 구분해야 한다는 지적을 반영해 아래를 구체화한다.

Optional이 아니라 default-on resource limit을 domain contract에 두고, project가 이를 완화(loosen)할 수는
있어도 처음부터 무제한으로 시작하지 않게 한다. 최소한 다음 다섯 축에 기본값을 둔다.

- Maximum nesting depth
- Maximum child count/fan-out
- CPU/time/memory budget
- Maximum produced artifact bytes
- Cancellation과 timeout propagation(부모가 취소되면 진행 중인 child도 취소되어야 한다)

§17에 "unbounded child fan-out"을 drift 신호로 추가하는 것도 함께 권한다.

## 6. DecisionScope 상속 규칙이 "다른 dataset을 새로 구독하는 child"에 대한 formal invariant를 명시하지 않는다

§10.3은 child가 "parent의 snapshot, maximum observation time과 lookback upper bound를 상속하며 더 넓힐 수
없다"고 정의한다. 이는 parent가 이미 구독한 dataset 내에서 child가 더 좁은 window를 요청하는 경우는 명확히
규정하지만, PRD §7.3 예시(child가 signal 생성, historical counterfactual, 후처리 등 "다른 목적"으로 쓰일 수
있다)를 고려하면 child가 parent는 구독하지 않은 다른 logical dataset을 decision-time 이하에서 새로
구독하려는 경우가 자연스럽게 생긴다.

> **[2026-07-24 수정]** 초판은 이 규칙이 "완전히 미정"이라고 표현했는데, 이는 과장이다. PRD §7.3은
> "Child strategy는 해당 decision에서 parent StrategyAgent가 볼 수 있는 data와 feedback만 볼 수 있다"고
> 명시하므로, 의도된 방향은 "child는 parent가 (그 decision 시점에) 볼 수 없는 dataset을 새로 구독할 수
> 없다"로 이미 상당히 분명하다. 남아 있는 진짜 gap은 방향의 부재가 아니라, 이 방향을 architecture §10.3이
> **formal invariant**로 명시하지 않았다는 것이다. 다음을 §10.3에 추가하는 것을 권한다.
>
> ```text
> child.allowed_dataset_ids ⊆ parent.decision_scope.dataset_ids
> child.max_available_at   <= parent.max_available_at
> child.lookback(dataset)  <= parent.lookback(dataset)
> ```
>
> Parent가 직접 쓰지 않지만 child에게 위임하려는 dataset은 parent strategy definition이 dependency
> union으로 미리 선언해야 한다는 규칙도 함께 필요하다.

이 invariant가 명시되어야 §6.3의 "Strategy definition이 필요한 logical dataset을 선언한다"는 계약이
child에도 재귀적으로 강제되는지가 test로 검증 가능해지고, P2 acceptance("Child strategy는 parent의 allowed
lookback 밖 또는 parent decision 이후 data에 접근할 수 없다")를 구현 가능한 test로 번역할 수 있다.

## 7. Frozen dataset snapshot의 materialization 단위가 아직 정해지지 않았다

이 저장소의 production 코드(`kwam_enhanced_index`, 이 repo의 root `AGENTS.md` "Data Layer Rules")는 의도적으로
`backtest_panel.parquet` 같은 persisted 물리 panel을 두지 않고, `base_universe_inputs`를 매 실행마다 DuckDB
query로 재계산한다(`82aef5b` 커밋). `qlibx-architecture-old.md` §6.2와 PRD §6.3은 registration이 "qlibx 전용
derived Parquet"을 `data/qlibx/`에 물리적으로 만든다고 규정한다.

> **[2026-07-24 수정]** 초판은 이를 "기존 원칙과의 긴장/충돌"로 표현했는데, 다른 agent의 재검토에서
> 이 프레이밍이 대부분 성립하지 않는다는 지적을 받아들인다. Root `AGENTS.md`의 no-panel 원칙은 "하나의
> monolithic runtime panel을 만들지 않는다"는 특정 production 파이프라인의 결정이고, qlibx의 "derived
> Parquet"도 반드시 그런 단일 monolithic panel을 뜻하지 않는다 — field별 materialization, partitioned
> snapshot, 기존 source partition과 query manifest의 조합, incremental content-addressed dataset 등
> 여러 형태로 구현할 수 있다. 즉 이것은 "서로 다른 목표를 가진 두 원칙의 충돌"이 아니라, **qlibx가
> 아직 어떤 materialization profile을 쓸지 구체화하지 않았다는 문제**로 재정의해야 한다.

§4.5(Frozen run bundle이 "physical content hash"를 요구)와 §9.4(idempotency를 위한 content-addressed
snapshot)를 만족하려면 최소한 하나의 구체적인 materialization 단위(monolithic panel/field-level
partition/incremental snapshot 중 무엇인지)를 §6.3의 registration 절차에 명시해야 이 요구사항을 구현
가능한 계약으로 검증할 수 있다. 이는 별도의 위험 항목이라기보다 §6.3에 한두 문장을 추가하면 해결되는
명확성 문제다.

## 8. Version compatibility를 실행시 판정할 절차가 없다

§15는 package version, project config schema version, dataset/artifact schema version, extension contract
version, Qlib adapter compatibility version 다섯 개를 독립적으로 관리한다고 선언한다. 독립 관리 자체는
옳은 방향(하나의 monolithic version보다 유연)이지만, 다섯 축의 조합이 유효한지—예를 들어 qlibx package
v2.x가 extension contract v1과 dataset schema v3의 조합을 지원하는지—를 project status(§6.10, §11.2 1번
단계)가 어떻게 판정하는지는 §15에 없다. Compatibility matrix가 없으면 "Unknown config key, schema mismatch...는
structured error로 끝난다"(§4.6)는 원칙이 이 다섯 축 조합에서는 무엇을 unknown/mismatch로 규정할지 모호해진다.

> **[2026-07-24 수정]** 초판은 이 해법을 "compatibility matrix"라고 표현했는데, 다섯 축의 전체 조합을
> 정적 matrix로 나열하면 축이 늘어날수록 조합 폭발이 생긴다는 지적을 받아들인다. 더 적합한 형태는 각
> component가 자신이 지원하는 범위를 선언하는 **compatibility predicate**다.
>
> ```text
> package supports project schema in [2, 3]
> artifact reader supports artifact schema in [1, 2]
> extension contract requires qlibx >= 1.4
> qlib adapter supports pyqlib == 0.9.7
> ```
>
> `project status`는 이 predicate들을 평가해 unsupported, migration-required, readable-but-not-writable을
> 구분해서 보고해야 한다.

Agent가 §11.2 1단계("project status와 schema version 확인")에서 실제로 무엇을 비교해야 하는지 이 predicate
평가 절차를 최소 한 문단으로 §15에 추가하는 것을 권한다.

## 9. Hexagonal diagram에서 StrategyAgent 같은 "domain plug-in" extension의 위치가 애매하다

§5의 diagram은 `Built-in components --> D(domain contracts)`, `Project-local extensions --> P(outbound
ports)`로 그려, project-local extension은 전부 outbound port(DB, Qlib, 파일시스템 같은 infra adapter)로
연결되는 것처럼 보인다. 그러나 이 product에서 가장 중요한 project-local extension은 StrategyAgent
자체(PRD §12.1: "User가 작성한 Strategy가 qlibx의 data, decision, Qlib execution과 recording workflow
사이에 들어가 실행되는 것 자체가 대표적인 extension")이며, 이는 infra adapter가 아니라 domain-level 알고리즘
교체에 가깝다. §13(Extension architecture)은 StrategyAgent를 다섯 개 첫 extension point 중 하나로 올바르게
분류하지만, §5 diagram이 이를 outbound port 상자 하나로만 표현하면 구현자가 "project-local Strategy는
domain의 StrategyAgent contract를 구현하는 것"과 "project-local Strategy는 port를 구현해 application이
호출하는 것"을 혼동할 수 있다. Diagram에 StrategyAgent/transform/analyzer 같은 domain-facing plug-in과
Qlib/DuckDB 같은 infra-facing adapter를 시각적으로 구분하는 것을 권한다.

## 10. 검증된 문서 정확성 (긍정적 확인)

리뷰 과정에서 architecture 문서가 prototype 코드를 인용한 구체적 사실 주장은 모두 grep으로 재확인했으며
오류를 찾지 못했다:

- §3.1의 `RunCatalog`(`qlib_extended/store.py`), `AlphaPoolCatalog`(`qlib_extended/research/pool.py`),
  `ParquetResearchCatalog`(`kwam_qlib_backend/research_graph.py`) 세 catalog 병존 주장 — 확인됨.
- §3.3의 "1,000줄 이상의 custom bar scheduler" 주장 — `kwam_qlib_backend/backend.py` 1,476줄로 규모상 부합.
- §3.2의 P0 CLI 표면이 "낮음"이라는 평가 — `qlib_extended/cli.py`는 실제로 `run`/`report`/`ensemble` 세
  subcommand뿐임을 확인.
- §10.5의 native twin 경로 서술(prototype `QlibClosedLoopBackend.run_targets()`를 migration oracle로만
  남긴다는 판단) — `critical-review.md` §13의 결론과 일치.

이 문서 자체의 근거 서술은 신뢰할 수 있으며, 이번 리뷰의 지적은 "사실이 틀렸다"가 아니라 "알려진 사실에서
architecture가 아직 답하지 않은 질문이 남아 있다"는 종류다.

## 11. 우선순위 요약과 권고 순서

| 우선순위 | 항목 | 권고 |
| --- | --- | --- |
| 1 (blocking) | Native `BaseStrategy` 위에서 direct position mutation + checkpoint가 lifecycle/metrics/resume과 안전하게 맞물리는지 미검증 (§2) | Architecture 확정 전 최소 fixture spike로 feasibility 확인 |
| 2 | 단일 catalog의 schema 팽창 위험 (§3) | §6.8을 lean core / derived view로 구분해 재서술 (single-writer 자체는 제거 대상 아님) |
| 3 | Onboarding subsystem에 phasing 부재 (§4) | §3.2 옆에 "재구성 vs 신규 개발" 구분과 순서 추가 |
| 4 | Child research resource limit이 optional (§5) | Default-on bound(depth/fan-out/budget/artifact bytes/cancellation)로 승격, §17에 drift 신호 추가 |
| 5 | DecisionScope의 cross-dataset child invariant 미명시 (§6) | §10.3에 `child.allowed_dataset_ids ⊆ parent...` formal invariant 추가 |
| 6 (informational) | Frozen snapshot의 materialization 단위 미확정 (§7) | §6.3에 materialization profile(단일 panel/partition/incremental) 명시 |
| 7 (informational) | Version compatibility 판정 절차 부재 (§8) | §15에 predicate 기반(matrix 아님) 판정 절차 한 문단 추가 |
| 8 (minor) | Diagram에서 domain plug-in과 infra adapter 미구분 (§9) | §5 diagram 개선 |

1~2번은 architecture의 근본 가정에 영향을 주므로 구현 착수 전에 해소하는 것을 권하고, 3~5번은 §18(review가
필요한 선택)에 항목을 추가하는 수준으로 다음 반복에서 다루면 된다. 6~8번은 문서 완성도 문제이며 즉시
반영해도 구조를 바꾸지 않는다.

## 12. 다른 agent 리뷰(`critical-review-on-architecture-codex.md`)와의 교차검증

같은 architecture 문서를 독립적으로 검토한 다른 agent의 리뷰를 읽고 겹치는 결론, 상충하는 주장, 내가
놓친 지적을 코드로 재검증했다.

### 12.1 공통 발견 (독립 수렴 — 신뢰도 상승)

- **Native Qlib `BaseStrategy` lifecycle × matched-capitalization 조합이 어디에서도 함께 증명된 적이
  없다**는 결론을 두 리뷰가 서로 다른 근거로 독립 도달했다. 나는 grep으로 `matched_capitalization`이
  `peer_momentum_runtime/`에 전혀 없다는 사실에서 출발했고, 상대는 §18의 review item이 architecture 전체를
  흔들 수 있는 우선순위로 취급되지 않는다는 점에서 출발했다. 두 경로가 같은 결론에 도달했으므로 이 항목의
  우선순위(Gate 0급 spike 필요)는 추가 논증 없이 확정으로 격상해도 된다.
- **Agent onboarding/skill 생성은 나머지 bounded context와 같은 "1차 버전"으로 묶지 말고 순서를
  뒤로 미뤄야 한다**는 점도 양쪽이 동일하게 지적했다(내 §4, 상대의 [P2-5]/Gate 5).

### 12.2 상대가 찾았고 나는 놓친 것 — 코드로 재검증한 결과 유효함

1. **[P0-1] FrozenRunBundle이 identity만 freeze하고 실행 가능한 code/config bytes는 freeze하지
   않는다.** `qlib_extended/runner.py`의 `_compute_strategy(config_path, ...)`가 worker 프로세스 안에서
   `load_project_config(config_path)`를 다시 호출하고, `qlib_extended/config.py:104`의
   `load_project_config`는 매 호출마다 `yaml.safe_load(config_path.read_text(...))`로 디스크에서 새로
   읽는다는 것을 직접 확인했다. 즉 §7.1이 "Worker는 mutable config path를 다시 읽지 않는다"고 선언한
   목표와 prototype의 실제 동작이 정반대다. 나는 §7.1을 "이미 잘 설계된 계약"으로 읽고 넘어갔는데, 상대는
   "계약을 문장으로 선언하는 것"과 "worker가 구조적으로 mutable path에 접근할 수 없게 만드는 것"을
   구분해야 한다고 짚었다. 이건 내가 놓친 정당한 지적이다.
2. **[P0-2] Matched-capitalization baseline sidecar는 사실상 Qlib account와 함께 authoritative한
   joint checkpoint다.** 나는 §2에서 이 mechanism의 존재와 native bridge 연결 여부만 문제 삼았는데, 상대는
   §4.1/§10.6의 "Qlib account만 authoritative, sidecar는 read-only projection"이라는 **문구 자체**가
   실제 failure model(Qlib account update는 성공했는데 sidecar checkpoint만 실패하는 경우)을 가린다고
   지적한다. 이어지는 invariant 제안(Qlib checkpoint ID와 capitalization journal checkpoint ID가 하나의
   execution step ID를 공유해야 한다)은 내 §2의 "spike로 확인하자"보다 한 단계 더 구체적인 canonical
   contract 수정안이며, 타당하다.
3. **[P0-4] Point-in-time 계약에 revision/vintage 축이 없다.** PRD §6.4가 quarterly data와 economic
   calendar의 point-in-time timestamp를 명시적으로 요구하는데도(내가 §7에서 이 절을 읽었음에도) architecture
   §6.2/§10.1의 `observation time`/`availability lag`만으로는 `event_time`, `available_at`,
   `valid_from/to`(수정 공시), `ingested_at`을 구분하지 못한다. 이 지적은 PRD 원문에 직접 근거하므로
   유효하다.
4. **[P0-5] Run/attempt/result/artifact identity의 잔여 모호성.** 나는 §4.5를 인용하며 "이 네 identity
   분리로 cache hit/failed retry/duplicate publication을 구분할 수 있다"는 architecture의 주장을 그대로
   받아들였다. 상대는 "cache hit가 새 attempt를 만드는지", "같은 payload를 다른 run이 만들면 artifact ID가
   같은지" 같은 구체적 질문이 실제로는 미답임을 보여준다. 개념을 선언한 것과 정의를 끝낸 것은 다르다는
   점에서 내가 너무 관대하게 읽었다.
5. **[P1-3] StrategyAgent output kind(signal/weight/physical target/order)를 처음부터 모두 열어두면
   execution bridge가 네 갈래로 분기한다.** PRD §7.2가 이 유연성을 실제로 허용하지만, 상대가 제안하는
   "1차 release는 `signed_signal`/`signed_active_weight`로 좁히고 나머지는 별도 extension으로 분리"는 내가
   §4에서 onboarding에만 적용했던 "phasing 필요" 논리를 StrategyAgent output에도 똑같이 적용한 것이다.
   같은 패턴을 한 곳에서만 찾고 다른 곳에 적용하지 못한 내 리뷰의 사각지대다.
6. **[P1-7] Data registration이 만드는 Parquet과 실제 native Qlib backtest `Exchange`/`StaticDataLoader`
   소비 경로가 분리되어 있다.** Prototype에서 `kwam_qlib_backend/ml_research.py`가 쓰는 `StaticDataLoader`
   경로와 backtest `Exchange` 구독 경로가 서로 다른 integration이라는 사실 자체는 맞다(critical-review.md
   §5.1도 이 둘을 별도 track으로 구분한다). "Parquet을 만들었다"가 "native Qlib이 그 data를 실제로
   구독한다"를 보장하지 않는다는 지적은 §6.2/§6.3(data registration)을 다룬 내 리뷰가 놓친 부분이다.
7. **[P1-5] Same-branch parallelism이 run isolation은 보장하지만 project file(같은 YAML, 같은
   `AGENTS.md` managed block) concurrent edit conflict는 다루지 않는다.** 이건 내 리뷰에 전혀 없던 지적이고,
   PRD §1.2의 "한 repository와 한 branch에서 병렬 연구"가 보장하는 범위를 정확히 좁힌다. Frozen run bundle은
   *실행 중인 run*을 보호하지만 *아직 실행되지 않은 두 agent의 동시 파일 편집*은 다른 문제라는 구분은
   타당하다.
8. **[P2-4]/[P2-6] Stochastic StrategyAgent의 cache determinism 정책, local extension의 trust boundary
   명시.** 둘 다 PRD가 실제로 여는 문(§7.1 stochastic 예외, §13 explicit reference load)에서 파생되는
   정당한 후속 질문인데 내 리뷰에는 없었다.

### 12.3 내가 찾았고 상대는 다루지 않은 것 (유지)

- 단일 catalog가 prototype 자체의 "lean core table" 교훈(`research/architecture.md` §8)과 대비해 schema가
  넓어지는 위험 — 상대는 catalog의 durability/atomicity([P1-4])는 짚었지만 schema breadth는 다루지 않았다.
  두 지적은 서로 다른 축이므로 병존한다.
- Nested child research resource limit이 optional로 남아있는 위험(§5) — 상대 문서에 없음.
- DecisionScope의 cross-dataset child 확장 규칙 미정의(§6) — 상대는 static/stateful bridge([P1-2])는
  짚었지만 dataset-axis 상속 규칙은 다루지 않았다.
- Frozen snapshot 계약과 이 repo의 "no persisted panel" 원칙(root `AGENTS.md`) 간 긴장(§7) — 상대 문서는
  prototype 코드만 인용하고 root `AGENTS.md`나 `research/architecture.md` 같은, 같은 repo의 이미 확정된
  다른 target architecture 문서는 인용하지 않는다.
- Version compatibility matrix(5개 축) 실행시 검증 전략 부재(§8) — 상대 문서에 없음.

### 12.4 Fact-check: 상대 주장 중 과장된 부분

**[P2-3]** "PRD가 recordable Python type을 제한하지 않는데 architecture는 JSON/Parquet만 허용해 서로
충돌한다"는 주장을 PRD 원문으로 재확인했다. `qlibx-prd.md` §12.3은 "PRD는 recordable Python type 또는
serializer 목록을 제한하지 않는다"는 문장 바로 다음 문단에서 "Initial portable format은 metadata/config에
JSON, table/matrix에 Parquet 또는 Arrow-compatible data를 사용한다"고 **PRD 스스로** 명시한다. 즉 PRD는
"개념적으로 특정 Python type을 영구히 금지하지 않는다"와 "v1 portable format은 JSON/Parquet으로 좁힌다"를
이미 구분해서 선언했고, architecture §7.2("새로운 payload type은 serializer와 loader contract가 함께
등록될 때만 허용")는 이를 그대로 따른 것뿐이다. PRD와 architecture는 이 지점에서 충돌하지 않으며, 상대가
제안하는 "수정"은 이미 두 문서에 존재한다. 이 항목은 실질적 gap이 아니라 architecture 문서에 그 근거
문장을 한 줄 더 명시하면 끝나는 수준의 minor nit으로 재분류해야 한다.

### 12.5 종합 — 배운 점과 내 리뷰를 고치는 방향

상대 리뷰는 "**선언된 계약과 구조적으로 강제된 계약의 간극**"이라는 하나의 축을 나보다 훨씬 깊게 팠다.
FrozenRunBundle의 실행 가능성(§7.1), baseline sidecar의 checkpoint atomicity(§10.6), run/attempt/result
identity(§4.5), publisher crash recovery(§12.2) 네 곳 모두 "architecture 문서는 올바른 목표 문장을 적어
뒀지만, 그 문장이 worker/publisher 구현을 구조적으로 강제하는 mechanism까지는 정의하지 않았다"는 동일한
패턴이다. 나는 이 패턴을 matched-capitalization 한 곳(§2)에서만 짚었고, 나머지 세 곳은 architecture의
서술을 액면 그대로 받아들여 "잘 설계됐다"고 넘어갔다. 이것이 이번 비교에서 가장 크게 배운 점이다 — 문서가
올바른 원칙을 명시했다는 사실과, 그 원칙이 구현 가능한 구조적 제약으로 번역되어 있다는 사실을 구분해서
검증했어야 했다.

반대로 나는 "**이 repo에 이미 존재하는 다른 확정 문서와의 정합성**"(research/architecture.md의 lean catalog
교훈, root `AGENTS.md`의 no-persisted-panel 원칙)이라는 축을 상대보다 깊게 팠다. 상대는 prototype 소스
코드는 폭넓게 인용하지만 이미 쓰여진 다른 target architecture 문서(`research/architecture.md`)나 이 repo의
운영 규칙(`AGENTS.md`)은 인용하지 않는다.

두 리뷰를 합치면 우선순위는 다음처럼 재조정된다.

1. (양쪽 수렴, 최우선) Native Qlib bridge × matched-capitalization feasibility spike를 Gate 0으로 승격.
2. (상대 추가, 반영 필요) "선언된 계약 vs 구조적으로 강제된 계약"의 간극을 FrozenRunBundle, baseline
   checkpoint, run/attempt/result identity, publisher crash recovery 네 곳에서 동시에 해소한다. 이를
   §11 표의 새로운 우선순위 1.5번으로 추가한다.
3. (내 발견 유지) Catalog schema breadth와 prototype의 lean-core 원칙 재적용.
4. (양쪽 수렴, 패턴 확장) Onboarding뿐 아니라 StrategyAgent output kind(signal/weight/target/order)도
   "1차 범위를 좁히고 이후 확장" 원칙을 적용한다.
5. (상대 추가, 반영) Point-in-time revision/vintage 모델 보강 — `event_time`/`available_at`/`valid_from-to`/
   `ingested_at`을 데이터 모델에 명시한다.
6. (내 발견 유지 + 상대의 [P1-5]로 보완) Nested child resource limit, DecisionScope cross-dataset 규칙,
   same-branch project-file 편집 충돌을 하나의 "parallel-agent 안전성" 섹션으로 묶어 재정리한다.
7. (경미, 양쪽 문서 다듬기 수준) Version matrix 검증 절차, local extension trust boundary, portable type
   명시성 — 문서에 한두 문단 추가로 해결된다.

## 13. 세 번째 교차검토: 이 문서 자체에 대한 반박을 반영한다

또 다른 agent가 §12의 비교 자체를 다시 검토하고, 이 문서(Claude 리뷰)의 기술적 전제 중 일부가 틀리거나
과장되었다는 평가를 보내왔다. 지적을 코드/PRD 원문으로 재검증한 뒤 위 §2, §3, §6, §7, §8, §11을 직접
수정했다. 이 절은 무엇을 왜 고쳤는지에 대한 변경 로그다.

### 13.1 사실이 틀려서 고친 것

- **§2.3의 "`BaseStrategy`는 bar마다 `TradeDecisionWO` 하나만 반환하므로 baseline endowment와 active
  order를 같은 bar에 나눠 낼 수 있는지가 Qlib API 차원에서 막혀 있을 수 있다"는 주장은 틀렸다.**
  `.venv/Lib/site-packages/qlib/backtest/position.py:390`의 `Position.update_order()`가 `Exchange` fill을
  거치지 않고 `Position`을 직접 mutate할 수 있고, prototype `kwam_qlib_backend/backend.py:1059`의
  `_apply_capitalization()`이 실제로 이 경로로 baseline을 zero-cost 반영한 뒤 active order만 `Exchange`로
  보낸다는 것을 코드로 확인했다. "제출 방법이 없을 수 있다"는 전제는 성립하지 않으므로 §2.3/§2.4를
  다시 썼다. 다만 이 정정이 "spike가 필요하다"는 최종 결론 자체를 바꾸지는 않는다 — 진짜 미검증 사항은
  제출 가능 여부가 아니라 그 direct mutation이 lifecycle hook, portfolio metrics, checkpoint/resume과
  안전하게 맞물리는지이며, 이는 §2.3에 다섯 개의 구체적 질문으로 다시 정리했다.

### 13.2 과장이어서 완화한 것

- **§3.2**: "단일 catalog가 모든 bounded context의 write를 공유하는 것은 §4.2가 경계하는 것과 본질적으로
  같은 종류의 결합"이라는 표현을 완화했다. DuckDB는 read-write 접속을 한 process로 제한하는 것이 공식
  concurrency model이므로([DuckDB concurrency 문서](https://duckdb.org/docs/current/connect/concurrency)),
  단일 publisher는 그 자체로 결함이 아니라 DuckDB를 선택한 이상 필요한 operational coordination이다.
  "여러 catalog가 서로 다른 identity/publication rule을 가지는 semantic 문제"와는 다른 종류이므로 이
  둘을 같은 문제로 묶지 않도록 고쳤다. 권고(짧은 transaction 유지, lean schema)는 그대로 유지했다.
- **§6**: "DecisionScope의 cross-dataset child 규칙이 완전히 미정"이라는 표현을 완화했다. PRD §7.3
  ("Child strategy는 parent가 볼 수 있는 data와 feedback만 볼 수 있다")이 이미 방향을 상당히 분명하게
  제시하므로, 진짜 gap은 "답이 없다"가 아니라 "답을 architecture §10.3이 formal invariant로 명시하지
  않았다"로 다시 정의했다. 구체적 invariant(`child.allowed_dataset_ids ⊆ parent.decision_scope.dataset_ids`
  등)를 추가했다.
- **§7**: "Frozen snapshot 계약과 no-panel 원칙의 긴장/충돌"이라는 프레이밍을 철회했다. Root `AGENTS.md`의
  no-panel 원칙은 "monolithic runtime panel을 만들지 않는다"는 특정 결정이고, qlibx의 "derived
  Parquet"이 반드시 그런 단일 panel을 뜻하지는 않는다 — field-level materialization이나 partitioned
  incremental snapshot으로도 구현할 수 있다. 두 원칙은 실제로 충돌하지 않으며, 남는 문제는 "qlibx가 아직
  materialization 단위를 정하지 않았다"는 명확성 gap으로 재정의했다.
- **§8**: "compatibility matrix"라는 표현을 "compatibility predicate"로 바꿨다. 다섯 개 version 축의
  전체 조합을 정적 matrix로 나열하면 조합 폭발이 생기므로, 각 component가 자신이 지원하는 범위를
  predicate로 선언하고 `project status`가 이를 평가하는 방식이 더 적합하다는 지적을 반영했다.

### 13.3 다시 확인해보니 유효했던 것 (변경 없음)

- §5(child research resource bound)는 독립적으로 유효하다는 평가를 받았다. "limit capability가
  optional"과 "limit 값이 없어 사실상 무제한"을 구분해야 한다는 지적을 반영해 depth/fan-out/budget/
  artifact bytes/cancellation 다섯 축을 명시적으로 추가했다(§5.3).
- §3(catalog lean-core), §4(onboarding phasing), §9(diagram의 domain/infra 혼동)는 이번 재검토에서도
  근거가 유지된다는 평가를 받아 내용을 바꾸지 않았다.

### 13.4 종합

이번 라운드에서 배운 것은 "prototype 코드가 실제로 그 mechanism을 증명했는지"를 내가 가정이 아니라 직접
코드로 다시 확인해야 한다는 점이다 — §2.3의 오류는 Qlib API의 반환 타입과 prototype의 실제 호출 경로를
확인하지 않고 "아마 이럴 것"이라는 추론으로 위험을 서술한 결과였다. 반면 §3, §6, §7, §8에서 지적받은
과장은 모두 "진짜 문제가 없다"가 아니라 "문제를 문서 어디에 위치시켜야 하는지, 얼마나 심각하게 표현해야
하는지"의 calibration 오류였다. 두 종류의 실수를 구분하는 것 자체가 이번 교차검토의 가장 큰 소득이다:
사실 오류는 반드시 코드로 재확인해서 고쳐야 하고, calibration 오류는 결론을 유지하되 서술을 정밀하게
다듬어야 한다.
