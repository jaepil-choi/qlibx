# qlibx Architecture Critical Review

## 1. Review scope와 결론

이 문서는 [`qlibx-architecture-old.md`](qlibx-architecture-old.md)를
[`qlibx-prd.md`](qlibx-prd.md)의 제품 목적에 비추어 검토한 architecture review다.

`qlib-integration-codex/`는 target architecture와 일치해야 하는 기준 구현이 아니다. 이미 여러 기능을
실제로 구현하면서 확인한 결합, 중복, identity, cache, Qlib lifecycle과 publication 문제를 다시 만들지
않기 위한 **경험적 reference**로만 사용했다. 따라서 아래 지적은 “prototype과 다르다”가 아니라
“prototype보다 clean하고 efficient한 upgrade가 되려면 target architecture에서 무엇을 더 명확히
결정해야 하는가”에 초점을 둔다.

초안 작성 후 같은 목적의 [`critical-review-on-architecture-claude.md`](critical-review-on-architecture-claude.md)와
상호 비교하고, 양쪽이 인용한 prototype 및 설치된 pyqlib 0.9.7 source를 다시 확인했다. 이 개정본은
독립적으로 수렴한 지적을 우선하고, 상대 리뷰에서 새로 확인한 child-resource/catalog/versioning 문제를
반영하며, 초안의 과도한 표현은 본문에서 바로잡는다.

전체 판정은 **방향에는 동의하지만 구현 착수 전 P0 contract를 보완하는 조건부 승인**이다.

현재 architecture의 강점은 분명하다.

- Qlib을 execution/accounting authority로 두고 두 번째 backtester를 만들지 않는다.
- Package와 user project, control plane과 data plane, economic intent와 physical implementation을
  분리한다.
- Stored alpha를 재실행 없이 ensemble/report하는 것을 public behavior로 둔다.
- Worker와 publisher를 분리하고 immutable artifact를 publication boundary로 둔다.
- Optimizer를 작은 port와 독립 validator로 제한한다.
- Prototype의 package 이름, custom scheduler와 project-specific research code를 그대로 이식하지 않는다.

반면 현재 문서는 좋은 원칙을 넓게 선언했지만, 가장 위험한 경계의 operational contract가 아직
결정되지 않았다. 이 상태로 package tree부터 구현하면 prototype의 복잡성이 더 정돈된 directory
이름 아래에서 재생될 가능성이 높다.

가장 먼저 고쳐야 할 사항은 다음 다섯 가지다.

1. `FrozenRunBundle`과 content-addressed component snapshot이라는 선언을 **실제로 실행할 config/code
   bytes와 loader contract**로 구체화해야 한다.
2. Qlib은 fill의 유일한 execution authority로 유지하되, matched-capitalization의 baseline state는 Qlib
   account와 함께 atomic하게 checkpoint되는 authoritative compatibility state로 계약해야 한다.
3. Point-in-time data는 단순 availability lag가 아니라 revision/vintage를 포함한 temporal model이
   필요하다.
4. Run attempt, reusable result, artifact record와 content blob identity를 분리해야 한다.
5. Native Qlib lifecycle과 matched-capitalization을 연결할 최소 hook을 feasibility spike로 먼저
   증명해야 한다.

---

## 2. 반드시 유지할 architecture 결정

### 2.1 Qlib을 execution/accounting kernel로 사용하는 결정

[`qlibx-architecture-old.md` §4.1](qlibx-architecture-old.md#41-하나의-execution-authority)의 방향이 맞다.
Order, fill, cost, position, cash와 NAV는 Qlib lifecycle에서 확정되어야 한다. Requested target이나
qlibx가 별도로 계산한 signed quantity를 realized state로 승격해서는 안 된다.

Prototype의
[`QlibClosedLoopBackend`](../../qlib-integration-codex/kwam_qlib_backend/backend.py)는 Qlib
`Account`와 `Exchange`를 사용하면서도 별도 date loop가 execution 순서까지 소유하면 backend 하나가
매우 커지고 두 번째 scheduler가 된다는 것을 보여준다. 반대로
[`QlibPeerMomentumStrategy`](../../qlib-integration-codex/peer_momentum_runtime/strategy.py)는
`BaseStrategy.generate_trade_decision()`과 `post_exe_step()` 안에서 online decision과 confirmed
feedback을 연결해야 native lifecycle이라고 부를 수 있음을 보여준다.

Target은 후자의 lifecycle을 유지하되 project-specific signal/portfolio logic을 Qlib subclass 안에
직접 넣지 않는 bridge가 되어야 한다.

### 2.2 Stored result를 module integration point로 사용하는 결정

Alpha, ensemble, portfolio, backtest와 reporting identity를 분리한 것은 중요하다. Backtest cost만
바뀌었는데 alpha를 다시 계산하거나, report renderer가 바뀌었는데 strategy를 다시 실행하는 구조를
막는다.

Prototype의
[`run_strategy_batch()`](../../qlib-integration-codex/qlib_extended/runner.py),
[`build_ensemble()`](../../qlib-integration-codex/qlib_extended/ensemble.py),
[`create_report()`](../../qlib-integration-codex/qlib_extended/reporting.py)는 이 behavior가 실제
workflow를 단순하게 만든다는 것을 증명했다. qlibx는 이 public behavior를 유지해야 한다.

### 2.3 Optimizer를 execution과 분리하는 결정

Signal selection, continuous portfolio optimization, integer lot과 actual fill은 서로 다른 문제다.
Optimizer가 Qlib execution을 대신하거나 strategy마다 clipping rule을 복제하지 않도록
`OptimizationProblem -> OptimizationResult`와 independent validation으로 제한한 방향이 맞다.

### 2.4 Worker와 publisher를 분리하는 결정

Worker가 큰 payload를 자기 staging에 만들고 publisher만 shared catalog를 짧게 갱신하는 구조는
DuckDB single-writer 특성과 병렬 연구 요구를 함께 만족시키기 위한 합리적인 선택이다. 다만 이 원칙을
실제 crash-recovery protocol까지 구체화해야 한다는 지적은 아래 P1-4에 적었다.

### 2.5 General framework와 project research를 분리하는 결정

Peer momentum, 조직별 benchmark와 research report builder를 reusable package에서 제외하는 판단이
맞다. Prototype에서 general runtime과 project research script가 한 distribution에 모이면서 큰
script와 compatibility surface가 누적된 점을 반복해서는 안 된다.

---

## 3. Critical findings

## [P0-1] FrozenRunBundle의 목표가 executable freeze를 구조적으로 강제하지 않는다

### 문제

[`qlibx-architecture-old.md` §7.1](qlibx-architecture-old.md#71-frozen-run-bundle)은 effective config,
dataset snapshot ID와 implementation identity를 동결한다고 선언하고, §12.1은 content-addressed
dataset/component snapshot만 worker에 전달한다고 한 단계 더 명시한다. 따라서 architecture가 executable
freeze를 전혀 생각하지 않은 것은 아니다. 남은 문제는 이 목표가 canonical bundle field, source-bundle
format과 loader rule로 번역되지 않았다는 점이다. **Identity를 기록하는 것과 worker가 실제로 immutable한
code/config bytes를 실행하는 것은 다르다.**

Mutable project path를 worker에게 넘기고 worker가 module을 import하면, 시작 후 file이 바뀌었을 때
manifest에는 이전 hash가 남고 실제 실행은 새 code를 사용할 수 있다. Import cache, editable install,
transitive local import와 non-Python resource까지 고려하면 단일 callable file hash만으로는 충분하지
않다.

Prototype의 [`build_plan()`](../../qlib-integration-codex/qlib_extended/planning.py)은 config와
callable fingerprint를 먼저 계산하지만,
[`_compute_strategy()`](../../qlib-integration-codex/qlib_extended/runner.py)는 worker에서 mutable
config path를 다시 읽고 module을 다시 import한다. 실제
[`load_project_config()`](../../qlib-integration-codex/qlib_extended/config.py)는 매 호출마다 YAML
file을 다시 읽는다. 이것은 architecture가 배제하려는 failure mode가 실제로 존재한다는 증거다. Target의
방향은 맞지만 현재 `FrozenRunBundle` contract만으로는 같은 구현을 구조적으로 막지 못한다.

### 영향

- 같은 run fingerprint가 서로 다른 code를 실행할 수 있다.
- Shared branch에서 다른 agent의 edit가 running worker에 섞일 수 있다.
- “같은 input의 verified cache hit”라는 주장을 신뢰할 수 없다.
- Resume 시 이전 implementation을 복원하지 못할 수 있다.

### 필수 개선

`FrozenRunBundle`을 manifest가 아니라 **self-contained execution descriptor**로 정의한다.

- Resolved config는 canonical JSON bytes로 저장하고 worker는 source YAML을 다시 읽지 않는다.
- Project-local component는 immutable source bundle, wheel 또는 content-addressed tree로 snapshot한다.
- Bundle에는 entry point, transitive project-local source digest, dependency lock/environment
  fingerprint와 resource file digest가 들어간다.
- Worker는 mutable module path가 아니라 frozen component bundle을 load한다.
- Process start method와 import isolation을 contract test에 포함한다.
- Resume은 original bundle이 존재하고 검증될 때만 허용한다.

첫 version에서는 arbitrary transitive import graph를 완벽히 추론하려 하지 말고, explicit component
root 아래 source tree와 declared resource를 통째로 snapshot하는 편이 더 안전하고 단순하다.

## [P0-2] Matched-capitalization에는 joint accounting checkpoint가 필요하다

### 문제

Architecture가 Qlib을 유일한 execution authority로 두는 것은 맞다. Market fill과 realized composite
position을 확정하는 주체는 계속 Qlib이어야 한다. 다만 baseline sidecar를 단순 diagnostic처럼 읽어서는
안 된다. Signed active quantity는 다음 두 상태가 모두 있어야만 복원된다.

```text
A = C - B

C = Qlib composite quantity
B = qlibx baseline quantity
```

`B`, baseline cash, activation/top-up/release event가 유실되거나 Qlib checkpoint와 시점이 다르면 `A`를
복원할 수 없다. 즉 sidecar는 두 번째 execution engine이나 fill ledger는 아니지만
**signed-accounting 관점의 authoritative compatibility state**다. Read-only projection인 것은 `A`이며,
`B`와 baseline cash/event journal 자체는 projection이 아니다.

Prototype의
[`backend.py`](../../qlib-integration-codex/kwam_qlib_backend/backend.py)가 baseline quantity/cash,
capitalization event, composite account와 resume state를 한 loop 안에서 함께 관리하게 된 이유도
이 원자성 때문이다.

### 영향

- Qlib account update는 성공했지만 sidecar checkpoint가 실패하면 signed state가 손상된다.
- Resume 시 Qlib account와 baseline event sequence가 다른 시점일 수 있다.
- Publisher crash recovery만으로 execution checkpoint의 atomicity를 보장할 수 없다.
- “Qlib account만 authoritative”라는 표현이 실제 failure model을 가린다.

### 필수 개선

Architecture 문구를 다음처럼 명확히 해야 한다.

> 일반 long-only execution에서 Qlib account가 유일한 authoritative state다.  
> Matched-capitalization mode에서는 Qlib composite account와 qlibx capitalization journal이 하나의
> versioned compatibility checkpoint를 이룬다. Signed view는 이 둘에서 계산되는 projection이다.

그리고 다음 invariant를 canonical contract로 추가한다.

- Qlib account checkpoint ID와 capitalization journal checkpoint ID는 하나의 execution step ID를
  공유한다.
- Checkpoint publish 전후 crash에 대한 recovery state machine이 있다.
- Activation/release는 idempotency key를 가진다.
- Resume 전에 `C >= 0`, `B >= 0`, cash/NAV neutrality와 event sequence를 모두 reconcile한다.
- Sidecar만 있거나 Qlib checkpoint만 있는 상태를 complete로 보지 않는다.

이 복잡성을 수용하지 않으려면 matched-capitalization을 first release의 core execution mode가 아니라
명시적인 experimental compatibility capability로 늦추는 것이 더 정직하다.

## [P0-3] Native Qlib bridge의 핵심 feasibility가 “review item”으로 남아 있다

### 문제

Architecture는 native Qlib scheduler를 유일한 production path로 확정하면서도
[`qlibx-architecture-old.md` §18](qlibx-architecture-old.md#18-review가-필요한-선택)에서
matched-capitalization을 연결할 최소 adapter hook과 지원 Qlib version을 미결정으로 둔다.

이 항목은 naming이나 directory default와 같은 후순위 선택이 아니다. 다음 전체 구조를 바꿀 수 있는
architecture-critical uncertainty다.

- Capitalization을 어느 Qlib lifecycle point에서 적용할지
- Qlib account/position mutation을 public API만으로 할 수 있는지
- Checkpoint와 resume을 어디서 intercept할지
- Current holding이 StrategyAgent와 optimizer에 전달되는 시점
- Order/fill observer가 partial fill과 cost를 어느 callback에서 확정할지

설치된 pyqlib 0.9.7 source를 확인하면 `BaseStrategy.generate_trade_decision()`은
`BaseTradeDecision | Generator`를 허용하고 nested executor도 존재한다. 또한 prototype의 baseline
activation은 exchange fill을 두 번 요청하는 방식이 아니라 Qlib `Position.update_order()`로 quantity와
matching cash를 zero-cost로 먼저 반영한 뒤 composite order를 한 번 제출하는 방식이다. 따라서 핵심
불확실성은 “한 bar에 decision을 두 번 낼 수 있는가”가 아니다. Direct account mutation을 어느 lifecycle
point에서 수행할지, Qlib accumulated metrics를 왜곡하지 않는지, capitalization journal과 checkpoint를
원자적으로 묶을 수 있는지가 실제 검증 대상이다.

### 영향

이 bridge가 불가능하거나 private Qlib internals에 강하게 의존하면 execution port, checkpoint schema,
StrategyAgent result, supported Qlib version과 acceptance test가 모두 바뀐다. 다른 bounded context를
먼저 구현할수록 재작업 범위가 커진다.

### 필수 개선

본 구현 전에 작은 executable spike와 ADR을 만든다.

1. Qlib `BaseStrategy` lifecycle에서 bounded decision을 호출한다.
2. Qlib-confirmed partial fill을 다음 decision에서 읽는다.
3. One-bar baseline activation과 actual underlying `SELL`을 수행한다.
4. 중간 checkpoint 후 resume하여 uninterrupted run과 동일한 observable result를 만든다.
5. Public 또는 허용된 stable Qlib hook만 사용했는지 기록한다.

이 spike가 통과하기 전에는 `adapters/qlib/matched_capitalization.py`의 final shape를 고정하지 않는다.

## [P0-4] Point-in-time contract가 revision/vintage data를 표현하기에 부족하다

### 문제

PRD는 quarterly data, economic calendar와 text data까지 point-in-time으로 다루려 한다. Architecture의
`observation time`, `availability lag`, `as_of`와 bounded lookback만으로는 수정 공시, consensus revision,
늦게 정정된 재무제표와 과거 시점에 알려졌던 미래 event schedule을 정확히 표현하기 어렵다.

최소한 다음 시간은 서로 다를 수 있다.

- `event_time`: 경제적 사건이나 measurement가 속한 시간
- `available_at`: strategy가 처음 관측 가능해진 시간
- `valid_from` / `valid_to`: 해당 version이 known truth였던 구간
- `ingested_at`: qlibx snapshot에 들어온 시간
- `decision_time`: strategy가 판단하는 시간

Dataset-level `availability_lag`는 모든 row가 같은 공개 규칙을 따를 때만 충분하다. Revised data는
row-level version과 availability가 필요하다.

### 영향

- Snapshot은 재현되지만 당시에는 존재하지 않았던 revised value를 사용할 수 있다.
- “no look-ahead audit 통과”가 실제 point-in-time correctness를 의미하지 않을 수 있다.
- Child lookback 제한을 지켜도 parent data 자체가 future revision을 포함할 수 있다.

### 필수 개선

Data domain에 versioned `TemporalSemantics`를 추가한다.

- Required clock field와 timezone
- Event time, available-at와 optional revision/vintage key
- As-of selection rule과 tie-breaking rule
- Calendar/session boundary와 decision cutoff
- Late arrival와 correction policy
- Snapshot이 raw latest view인지 point-in-time history인지

`DatasetSnapshot(as_of=...)`은 단순 metadata가 아니라 해당 selection rule으로 materialize된 immutable
content를 가리켜야 한다. Daily OHLCV처럼 revision이 없는 profile은 이 일반 contract의 단순한
specialization으로 둔다.

## [P0-5] Run, result, artifact와 content identity가 아직 충돌한다

### 문제

Architecture는 다음을 구분한다.

- Definition ID
- Run ID: immutable execution attempt
- Run fingerprint: idempotency/cache identity
- Artifact ID: schema와 payload content identity

좋은 출발이지만 lifecycle 설명과 publication behavior를 함께 보면 다음이 불명확하다.

- Cache hit 요청은 새 run attempt인가, 기존 run을 반환하는가?
- Failed retry는 같은 fingerprint를 가지면서 어떻게 별도 attempt로 남는가?
- 같은 payload를 서로 다른 run이 만들면 artifact ID는 같은가?
- Artifact envelope에 producer run과 parent lineage가 들어가는데 artifact ID가 content identity라면
  lineage 차이가 ID에 포함되는가?
- 동일 blob을 deduplicate하면서 run별 provenance를 어떻게 보존하는가?

Prototype에서는 deterministic `run_id`가 reusable result identity와 execution instance identity 역할을
동시에 맡아 단순한 cache에는 편리했지만, failed attempt와 retry를 표현하기 어렵다는 교훈이 있었다.

### 필수 개선

다음 다섯 개를 명시적으로 분리하는 편이 가장 단순하다.

| 개념 | 권장 identity | 의미 |
| --- | --- | --- |
| Definition | stable semantic ID + version | dataset/component/strategy의 이름과 계약 |
| Invocation | ULID/UUID | user/agent가 요청한 한 번의 use case |
| Attempt | ULID/UUID | 실제 worker 실행, retry마다 새로 생성 |
| Result key | deterministic fingerprint | 같은 frozen input의 verified result 재사용 key |
| Blob | content digest | 실제 JSON/Parquet/Arrow bytes deduplication |

`ArtifactRecord`는 run/attempt, role, schema, semantics와 blob digest를 연결하는 provenance record다.
Artifact record ID와 blob digest를 같게 만들지 않는다.

Cache hit는 새 invocation이 기존 verified result를 참조하는 event이며 worker attempt를 만들지 않아도
된다. Failed attempt는 같은 result key를 가질 수 있지만 complete result slot을 점유하지 않는다.

---

## 4. High-priority findings

## [P1-1] Stage와 artifact materialization 단위가 정의되지 않았다

### 문제

Architecture가 모든 transform을 반드시 physical artifact로 저장한다고 명시한 것은 아니다. 문제는
“stage가 끝나면 artifact로 저장한다”는 원칙에서 stage의 단위가 정의되지 않았다는 점이다. Rank, clip,
decay, align 같은 작은 transform이나 adaptive StrategyAgent의 per-bar child evaluation까지 stage로
해석하면 Parquet, manifest와 catalog row가 계산량보다 더 빨리 증가할 수 있다.

반대로 아무 것도 materialize하지 않으면 stored-result reuse와 audit requirement를 잃는다. 현재 문서는
두 극단 사이의 기준을 정하지 않는다.

### 개선안

Artifact boundary를 세 등급으로 나눈다.

1. **Canonical**: use case의 public output, downstream reuse 대상, promotion evidence
2. **Checkpoint**: resume/recovery에 필요한 runtime state
3. **Diagnostic record**: 사용자가 명시적으로 선택한 intermediate output

Research graph 내부 node는 기본적으로 ephemeral이다. 다음 조건 중 하나일 때만 canonical 또는 cached
artifact로 materialize한다.

- 다른 run이 직접 참조하는 named output
- 계산 비용이 정한 threshold를 넘는 node
- explicit cache policy가 있는 pure node
- causality, optimizer 또는 reconciliation audit에 필요한 evidence

Fused execution을 허용하되 manifest에는 node definition과 lineage를 남긴다. “Artifact가 API”와
“모든 intermediate가 file”을 같은 뜻으로 사용하지 않아야 한다.

## [P1-2] Static research graph와 stateful StrategyAgent의 관계가 충분히 명확하지 않다

### 문제

Architecture는 static reusable computation을 typed graph로, decision-time child evaluation을 bounded
runtime tree로 분리한다. 방향은 맞지만 두 모델 사이의 bridge가 없다.

- Graph output이 어느 시점에 StrategyAgent subscription으로 들어가는가?
- Online adaptive strategy가 만든 bar별 signal은 reusable alpha artifact인가?
- Stored ensemble은 static alpha만 받는가, adaptive strategy의 realized decision series도 받는가?
- Child evaluation의 definition, input과 선택되지 않은 result를 어느 수준까지 기록하는가?

Prototype의
[`research_graph.py`](../../qlib-integration-codex/kwam_qlib_backend/research_graph.py)는 graph,
dataset dependency, cache와 catalog 책임을 한 abstraction에 계속 추가하면 빠르게 커질 수 있음을
보여준다.

### 개선안

두 contract를 분명히 분리한다.

- `ComputePlan`: side-effect-free batch DAG, immutable artifact를 만든다.
- `DecisionProgram`: Qlib clock에서 state와 confirmed feedback을 소비한다.

`DecisionProgram`은 `ComputePlan` artifact를 read-only input으로 구독할 수 있다. 반대로 online decision
history를 reusable alpha로 publish하려면 run 종료 후 별도의 canonicalization step을 거친다. Runtime
child 결과는 기본적으로 run-local diagnostic이고, promoted output만 별도 artifact가 된다.

## [P1-3] StrategyAgent output을 signal, weight, physical target, order까지 하나로 열어두면 경계가 무너진다

### 문제

서로 다른 output을 허용하는 것은 유연하지만 각 output은 우회하는 layer가 다르다.

- `signal`은 transform, sizing과 portfolio construction이 필요하다.
- `active_weight`는 ensemble/portfolio validation이 필요하다.
- `physical_target`은 optimizer를 이미 수행했다는 뜻이다.
- `order`는 portfolio construction과 target-to-order policy까지 우회한다.

이를 모두 하나의 StrategyAgent contract로 받으면 execution bridge가 runtime type에 따라 네 개의
pipeline을 조립해야 하고, cost/constraint/lineage가 output kind마다 달라진다.

### 개선안

PRD가 장기적으로 signal, weight, physical target과 order를 모두 허용하는 방향은 유지한다. 다만 첫
release의 default research profile은 `signed_signal`과 `signed_active_weight`로 좁힌다. 이미 physical
target을 만드는 전략은 별도 `PortfolioPolicy` profile로, order를 직접 만드는 고급 사용은 별도
`ExecutionStrategy` contract로 분리하여 각 profile이 우회하는 validation layer를 명시한다.

이후 실제 use case와 acceptance가 생길 때 supported profile을 확장한다. 이는 PRD capability를 삭제하는
것이 아니라 release sequencing을 좁히는 제안이다. “Strategy가 무엇이든 반환할 수 있다”보다 “각 public
pipeline이 어떤 단계를 반드시 통과하는가”가 더 중요한 contract다.

## [P1-4] Catalog를 rebuildable index라고 부르기에는 durable source가 불완전하다

### 문제

Architecture는 artifact manifest와 content hash를 durable evidence로 두고 catalog를 rebuildable
index라고 설명한다. 그러나 proposal, failed attempt, decision, supersede relation, reviewer와 stale
update version 같은 control-plane entity는 payload artifact manifest만으로 복구되지 않는다.

또한 worker artifact directory의 atomic install과 DuckDB transaction은 하나의 filesystem/database
transaction이 아니다. Prototype
[`RunCatalog.publish()`](../../qlib-integration-codex/qlib_extended/store.py)은 artifact directory를
먼저 install하고 DuckDB에 insert하므로 그 사이 crash window가 생긴다. Target architecture가 recovery를
언급한 것은 맞지만 durable authority가 무엇인지 정하지 않았다.

### 개선안

둘 중 하나를 명시적으로 선택한다.

1. DuckDB가 authoritative control-plane database이고 backup/migration을 제공한다.
2. Immutable append-only control event와 artifact manifest가 authoritative source이고 DuckDB는 그
   projection이다.

“Rebuildable”을 유지하려면 두 번째가 더 일관적이다. Proposal, attempt transition, publish, decision과
supersede도 immutable event로 남아야 한다. Publisher는:

```text
stage payload
-> verify
-> write publish intent
-> atomic artifact install
-> append commit event
-> update DuckDB projection
```

순서를 가져야 하며 각 중간 상태의 recovery action을 정의해야 한다.

Catalog projection 자체도 lean해야 한다. Prototype의
[`research/architecture.md` §8](../../qlib-integration-codex/research/architecture.md#8-lean-alpha-pool)이
`runs`, long-form `metrics`, `members`만 core table에 두고 pair correlation, crossing matrix와 상세
provenance를 artifact로 뺀 교훈을 재사용한다. qlibx의 entity 범위가 더 넓더라도 다음을 구분해야 한다.

- Hot-path core: identity, status, parent link, artifact location, CAS version
- Durable evidence: immutable manifest와 control event
- Derived view/cache: comparison, orthogonality matrix, nearest-neighbor와 heavy diagnostics

하나의 catalog를 사용하는 것과 모든 개념을 넓은 core table로 저장하는 것은 같은 결정이 아니다.

## [P1-5] Same-branch parallelism 보장이 project source edit conflict까지 해결하지는 못한다

### 문제

Frozen input과 isolated staging은 running job과 generated artifact를 보호한다. 하지만 두 agent가 같은
strategy YAML, local Python file, `AGENTS.md` managed block을 동시에 수정하는 문제는 해결하지 않는다.

PRD의 “한 repository와 한 branch에서 병렬 연구”가 file edit까지 자동으로 안전하다고 읽히면 제품이
보장할 수 없는 범위를 약속하게 된다.

### 개선안

보장 범위를 분리한다.

- qlibx가 보장: session workspace, frozen run, generated state, publication, catalog CAS
- qlibx가 감지: project config/local component의 expected-content hash가 달라진 stale write
- qlibx가 보장하지 않음: arbitrary user source의 semantic merge

Mutation command는 read 시점 content hash를 plan에 넣고 apply 시 compare-and-swap한다. 충돌하면 새
내용을 덮어쓰지 않고 revised plan을 요구한다. Session별 proposal file을 먼저 만들고 shared canonical
config update는 짧은 publish step으로 제한하는 것도 좋다.

## [P1-6] Extension point별 contract와 공통 component identity 사이의 최소 공통 규격이 필요하다

### 문제

모든 extension에 하나의 base class나 global registry를 강제하지 않겠다는 결정은 타당하다. 그러나
공통 identity까지 없으면 frozen bundle, config validation, lineage, help discovery와 cache가 각
extension point마다 다시 구현된다.

### 개선안

Lifecycle interface는 extension point별로 유지하되 모든 component reference에 다음 최소 envelope를
공통 적용한다.

```text
component_kind
contract_name + contract_version
semantic_id
implementation_ref
implementation_digest
config_schema
declared_resources
capabilities
```

이는 global plugin framework가 아니라 identity와 resolution을 위한 작은 공통 contract다. Resolver는
explicit reference만 load하고, extension point가 자기 input/output protocol을 소유한다.

## [P1-7] Data registration output과 Qlib data plane 연결 방식이 덜 정의되어 있다

### 문제

Architecture는 validated derived Parquet과 `qlib_materializer.py`를 제안하지만, native Qlib backtest가
calendar, instrument, quote field와 expression provider를 어떻게 소비할지는 확정하지 않는다.

Qlib ML의 `StaticDataLoader`에 pandas data를 넣는 것과 Qlib backtest `Exchange`가 market data를
구독하는 것은 다른 integration path다. “Parquet을 만들었다”만으로 native Qlib schedule/exchange가
그 data를 사용한다고 볼 수 없다.

### 개선안

첫 release에서 지원할 `ExecutionDataProfile`을 하나 고정한다.

- Calendar와 instrument lifecycle
- Execution/valuation price
- Position unit factor
- Volume와 limit/suspension field
- Instrument type, lot와 cost mapping
- Research universe와 execution tradability의 별도 source
- Qlib provider/materializer 또는 custom quote adapter 중 선택한 연결 방식

Registration의 bounded smoke는 Parquet read만 하지 말고 작은 Qlib `Exchange`가 해당 profile을 실제로
subscribe하고 한 bar를 실행하는 데까지 포함해야 한다.

## [P1-8] Reporting output의 provenance 정책을 명시해야 한다

### 문제

Architecture는 report-local calculation과 final output을 canonical research lineage에 등록하지
않는다고 한다. Research identity를 오염시키지 않겠다는 목적은 맞고, 모든 report를 catalog entity로
만들 필요도 없다. 다만 reproducible report나 hash-based render cache를 product behavior로 제공한다면
HTML/image/document가 어떤 stored input, analysis version과 renderer version에서 나왔는지는 별도
output manifest에서 확인할 수 있어야 한다.

### 개선안

필요한 report에 한해 `research artifact`와 `derived presentation output`을 구분한다.

- Report output은 alpha promotion이나 upstream cache identity에 영향을 주지 않는다.
- 대신 report run record가 input artifact IDs, analysis definitions, renderer identity와 output blob
  digest를 가진다.
- Temporary plot data는 저장하지 않아도 되지만 final output과 typed analysis result는 선택적으로
  재사용할 수 있다.

이 기록은 canonical research catalog에 들어갈 필요가 없으며 report output 옆의 manifest로 충분할 수
있다. “Reporting은 새 research evidence를 만들지 않는다”와 “report output은 provenance가 없다”를
같은 뜻으로 사용하지 않아야 한다.

## [P1-9] Nested child research의 data와 resource boundary를 강제해야 한다

### 문제

Architecture §6.3은 child-research resource limit을 optional로 두지만 PRD §7.3은 nested request가
resource limit을 명시한다고 요구한다. Parent보다 늦은 data를 보지 않는다는 rule은 계산량을 제한하지
않는다. Recursive child tree가 depth/fan-out 제한 없이 실행되면 한 StrategyAgent가 parallel session의
CPU, memory와 artifact storage를 소진할 수 있다.

Dataset scope도 prose의 의도와 machine-checkable contract 사이에 간극이 있다. PRD는 child가 해당
decision에서 parent가 볼 수 있는 data만 본다고 하므로 product intent는 “새 dataset 구독 불가”에 가깝다.
하지만 `DecisionScope`가 dataset set을 포함하는지와 child definition dependency를 언제 검증하는지는
명시되지 않았다.

### 개선안

- Default-on maximum depth, fan-out/child count, wall time, memory와 artifact-byte budget을 둔다.
- Cancellation과 timeout을 descendant에 전파한다.
- `child.dataset_ids ⊆ parent.scope.dataset_ids`를 compile/run 전 검증한다.
- Child만 사용하는 dataset도 parent definition의 transitive dependency union에 미리 선언한다.
- `child.available_at <= parent.available_at`과 dataset별 lookback upper bound를 함께 검증한다.
- Unbounded child fan-out을 architecture drift guardrail에 추가한다.

---

## 5. Medium-priority findings

## [P2-1] Package-by-layer 구조가 use case 변경을 너무 넓게 퍼뜨릴 수 있다

제안된 package tree는 clean architecture를 잘 드러내지만 작은 기능 하나가 `domain/`, `ports/`,
`application/`, `adapters/`, `schemas/`에 걸쳐 여러 파일을 만들게 될 수 있다. Prototype의 긴 파일을
피하려다 반대로 추적하기 어려운 thin wrapper가 많아질 위험이 있다.

첫 구현은 directory topology보다 dependency rule을 우선한다.

- 외부 경계가 실제로 교체되는 곳에만 port를 만든다.
- 두 번째 implementation이 없는 내부 deterministic function에는 port를 만들지 않는다.
- Data registration, run/publish, execution 같은 vertical use case의 관련 contract를 가까이 둔다.
- Architecture test는 file size보다 forbidden dependency와 public behavior를 검사한다.

## [P2-2] Snapshot content hashing의 비용 모델이 없다

대형 dataset 전체를 run planning 때마다 byte hash하면 cache 확인 자체가 비싸진다. 반대로 path, mtime와
row count만 쓰면 silent mutation을 잡지 못한다.

Dataset snapshot은 immutable partition manifest를 가져야 한다.

- Partition별 content digest
- Canonical schema digest
- Ordered partition manifest digest가 snapshot ID
- Append-only source의 incremental snapshot 생성
- Full rehash가 필요한 조건과 trust boundary

Worker는 snapshot 전체를 복사하지 않고 immutable partition reference를 받는다.

## [P2-3] Portable format의 v1 boundary를 한 곳에서 규범적으로 선언해야 한다

초안은 PRD가 recordable Python type을 제한하지 않는다는 문장과 architecture의 JSON/Parquet 기본
format이 충돌한다고 평가했지만 이는 과장이다. PRD §12.3 자체가 initial portable format으로 JSON과
Parquet/Arrow를 명시하고, architecture는 새 payload type에 serializer/loader contract를 요구한다. 두
문서는 이 지점에서 충돌하지 않는다.

남은 개선은 같은 rule을 machine-readable artifact schema의 단일 source of truth로 만드는 정도다.
Unsupported object는 fail-fast하고, Pickle과 arbitrary Python object serialization은 portability,
security와 long-term compatibility 때문에 canonical artifact로 허용하지 않는 편이 좋다. 이 항목은
architecture gap이 아니라 minor clarification이다.

## [P2-4] Stochastic StrategyAgent의 cache와 reproducibility policy가 필요하다

PRD는 deterministic StrategyAgent를 기본으로 하면서 stochastic LLM 또는 random output의 예외를
허용한다. Declared seed로 통제되지 않는 component는 deterministic result cache를 사용할 수 없다.

Component capability에 `deterministic`, `seeded`, `external_nondeterministic`을 선언하게 하고:

- deterministic/seeded만 result-key cache를 허용한다.
- external nondeterministic은 attempt마다 새 result를 만든다.
- provider response나 external evidence를 재사용하려면 그것을 frozen input artifact로 먼저 capture한다.

## [P2-5] Agent onboarding은 core runtime과 release sequencing을 분리할 필요가 있다

Agent-facing documentation과 skill generation은 제품 차별점이지만 data/run/artifact/execution contract가
안정되기 전에 generator를 만들면 unstable interface를 문서와 template에 중복 고정하게 된다.

Prototype에는 managed instruction block, `SKILL.md` generator, versioned error lookup을 구현한 선례가
없다. 따라서 이 영역은 기존 mechanism의 재구성이 아니라 신규 subsystem 개발이다. 일정과 acceptance를
execution/catalog migration과 같은 위험군으로 계산하지 않아야 한다.

초기에는 versioned installed docs와 machine-readable schema를 source of truth로 만들고, instruction
managed block과 skill generator는 그 resource를 얇게 참조하게 한다. Contract duplication을 피해야
upgrade 비용이 작아진다.

## [P2-6] Local extension은 trusted code라는 security boundary를 명시해야 한다

Explicit module/file reference는 accidental discovery를 막지만 arbitrary local Python code 자체를
sandbox하지는 않는다. qlibx가 local extension을 안전하게 검증한다는 표현은 schema/contract
compatibility 검증을 뜻할 뿐 malicious side effect 방지를 뜻하지 않는다.

첫 release가 local extension을 trusted project code로 취급한다면 그렇게 명시한다. 별도 process,
filesystem/network restriction과 dependency isolation을 제공하지 않는 한 security sandbox를 암시하지
않아야 한다.

## [P2-7] Version compatibility는 독립 version 선언만으로 검증되지 않는다

Architecture §15는 package, project config, dataset/artifact schema, extension contract와 Qlib adapter
version을 독립 관리한다. 그러나 `project status`가 어떤 조합을 supported, readable-only,
migration-required 또는 incompatible로 판단할지는 정의하지 않는다.

전체 Cartesian compatibility matrix를 수동 관리하기보다 component별 range/predicate를 선언한다.

```text
package supports project_schema >=2,<4
artifact_reader supports artifact_schema in {1,2}
extension requires strategy_contract ==2
qlib_adapter supports pyqlib ==0.9.7
```

Project status와 run planning이 이 predicate를 실행 전에 평가하고 structured error와 migration action을
반환해야 한다.

## [P2-8] Hexagonal diagram에서 domain plug-in과 infrastructure adapter를 구분해야 한다

현재 diagram은 built-in component는 domain contract로, project-local extension은 outbound port로만
향하는 것처럼 보인다. 그러나 StrategyAgent, transform과 analyzer는 domain-facing algorithm plug-in이고
Qlib, DuckDB와 filesystem은 infrastructure adapter다.

Lifecycle contract는 extension point별로 두되 diagram에서는 다음을 분리한다.

```text
built-in / project algorithm -> domain extension contract
Qlib / DuckDB / filesystem   -> outbound infrastructure port
```

이는 package 구조 변경보다 문서 정확성 문제지만, `ComponentRef` resolver와 실제 plug-in protocol을
혼동하지 않게 한다.

---

## 6. 더 clean하고 efficient한 target shape

현재 hexagonal direction을 유지하되 “모든 domain마다 layer 하나씩”보다 네 개의 작은 kernel을 먼저
완성하는 편이 좋다.

```text
Contract kernel
  temporal dataset · component ref · run/result identity · artifact schema

Runtime kernel
  freeze · worker execution · checkpoint · verify · publish · recovery

Research capabilities
  compute plan · StrategyAgent · alpha · ensemble · portfolio

Adapters
  Parquet/DuckDB · Qlib · optimizer · renderer · local component resolver
```

여기서 StrategyAgent/transform/analyzer implementation은 `Research capabilities`가 소유한 domain extension
contract를 구현하고, local component resolver만 infrastructure adapter에 속한다. Local algorithm 자체를
outbound infrastructure port로 취급하지 않는다.

Application use case는 이 kernel을 조립한다.

```text
public API / CLI
-> use-case command
-> frozen invocation
-> worker result in isolated staging
-> verification
-> immutable publication
-> small public result
```

Port는 최소한 다음 외부 경계에만 우선 도입한다.

- Dataset snapshot reader
- Component resolver
- Artifact/blob store와 catalog/event store
- Portfolio optimizer
- Execution engine
- Renderer

Rank, decay, exposure calculation처럼 package 내부 deterministic operation까지 port로 만들 필요는 없다.

---

## 7. 권장 implementation 순서

## Gate 0 — Architecture feasibility

Codebase scaffold보다 먼저 다음 spike를 통과시킨다.

1. Native Qlib one-bar/partial-fill/next-feedback bridge
2. Matched-capitalization activation, actual SELL, checkpoint/resume
3. Mutable source edit 중에도 frozen component bundle로 동일 결과 실행
4. Artifact install과 catalog update 사이 crash recovery

이 네 항목은 package 구조를 바꿀 수 있으므로 실패를 빨리 확인해야 한다.

## Gate 1 — Contract와 storage kernel

- Temporal dataset/schema
- Definition/invocation/attempt/result/blob identity
- Frozen component bundle
- Artifact record와 immutable blob
- Publisher state machine과 lean catalog projection
- Version compatibility predicate와 project-status validation

아직 research graph나 onboarding generator를 만들지 않는다.

## Gate 2 — 가장 작은 vertical slice

```text
registered daily data
-> fixed StrategyAgent
-> signed alpha
-> immutable publish
-> stored artifact report
```

이 slice에서 no-look-ahead, local extension, cache hit, failed attempt와 raw artifact reload를 검증한다.

## Gate 3 — Qlib closed loop

```text
stored/online active intent
-> portfolio policy
-> physical target
-> native Qlib execution
-> confirmed feedback
-> checkpoint/resume
```

Long-only path를 먼저 완성하고 matched-capitalization은 Gate 0 결과에 따라 같은 release 또는 다음
release로 결정한다.

## Gate 4 — Research operating system

- Proposal/decision/orthogonality
- Static compute plan과 cache
- Stored ensemble
- Parallel session과 publisher recovery
- Default-on child depth/fan-out/resource budget과 dataset-subset validation
- Project file stale-write detection
- Nearest-neighbor context

## Gate 5 — Agent product surface

- Task help와 schema discovery
- Instruction managed block
- Skill generation
- Extension scaffold

이 순서는 agent experience를 덜 중요하게 본다는 뜻이 아니다. Agent에게 노출할 contract를 먼저
안정화하여 generated instruction이 implementation 변화에 끌려다니지 않게 한다는 뜻이다.

---

## 8. Architecture 문서에 바로 반영할 수정 목록

구현 전에 [`qlibx-architecture-old.md`](qlibx-architecture-old.md)에 다음 결정을 추가하는 것을 권장한다.

1. `FrozenRunBundle`에 canonical config bytes와 executable component bundle을 포함한다.
2. `Run ID`를 invocation/attempt/result key로 분리하고 artifact record와 blob digest를 분리한다.
3. Dataset `TemporalSemantics`에 event time, available-at, revision/vintage와 as-of rule을 추가한다.
4. 첫 `ExecutionDataProfile`과 Qlib provider/quote 연결 방식을 고정한다.
5. Matched mode에서 composite account와 capitalization journal이 joint authoritative checkpoint임을
   명시한다.
6. Native Qlib bridge spike를 architecture gate로 올리고 지원 Qlib version/hook ADR을 요구한다.
7. Canonical/checkpoint/diagnostic artifact의 materialization policy를 추가한다.
8. `ComputePlan`과 stateful `DecisionProgram`의 관계를 정의한다.
9. PRD의 output capability는 유지하되 V1 default profile을 좁히고 physical target/order profile의
   validation boundary를 분리한다.
10. Catalog의 durable authority가 DuckDB인지 immutable event journal인지 선택하고, core table과 heavy
    derived view/cache를 분리한다.
11. Same-branch 보장을 generated state와 publication에 한정하고 project file stale-write detection을
    추가한다.
12. Extension point별 lifecycle은 분리하되 공통 `ComponentRef` envelope를 둔다.
13. Reproducible/cacheable report에만 non-research output manifest를 두는 정책을 정한다.
14. Stochastic component의 cache policy와 local extension trust boundary를 명시한다.
15. Nested child의 dataset-subset rule과 default-on depth/fan-out/resource budget을 추가한다.
16. Package/config/artifact/extension/Qlib adapter version의 compatibility predicate와 project-status 검증을
    정의한다.
17. Hexagonal diagram에서 domain algorithm plug-in과 infrastructure adapter를 분리한다.

---

## 9. 다른 agent 리뷰와의 교차검증에서 채택하거나 기각한 항목

### 채택하여 본문에 통합한 항목

- Native Qlib lifecycle과 matched-capitalization 결합을 Gate 0으로 올린다.
- Catalog는 하나로 유지하되 lean core, immutable evidence와 heavy derived view/cache를 구분한다.
- Onboarding은 prototype 선례가 없는 신규 subsystem이므로 core contract 이후로 분리한다.
- Nested child resource limit을 optional이 아닌 default-on contract로 바꾼다.
- Child dataset scope를 parent scope의 부분집합으로 machine-check한다.
- Independent version 축에 runtime compatibility predicate를 추가한다.
- Domain algorithm plug-in과 infrastructure adapter를 diagram에서 구분한다.

### Fact-check 후 표현을 수정하거나 기각한 항목

- `BaseStrategy`가 무조건 bar당 하나의 `TradeDecisionWO`만 반환하므로 baseline endowment와 market order를
  두 번 제출할 수 없다는 설명은 정확하지 않다. pyqlib 0.9.7에는 generator/nested decision 경로가 있고,
  prototype의 capitalization은 exchange fill이 아니라 direct `Position` state update다. Spike의 필요성은
  유지하되 검증 대상은 lifecycle, metrics와 checkpoint atomicity로 고쳤다.
- qlibx derived Parquet과 이 repository의 `backtest_panel.parquet` 제거 원칙은 직접 충돌하지 않는다.
  후자는 특정 monolithic panel을 runtime contract에서 제거한 project 결정이고, qlibx snapshot은 partition,
  field별 materialization 또는 source/query manifest가 될 수 있다. 따라서 별도 architecture risk로 추가하지
  않는다.
- PRD의 unrestricted recordable type과 architecture의 JSON/Parquet default가 충돌한다는 초안 평가는
  철회한다. PRD가 initial portable format을 이미 JSON/Parquet/Arrow로 제한하고 있다.
- 하나의 DuckDB publisher가 write를 serialize하는 것은 여러 catalog가 서로 다른 identity/publication
  rule을 갖는 문제와 같지 않다. Single publisher는 의도된 operational coordination이며, 해결책은 catalog를
  다시 나누는 것이 아니라 transaction과 core projection을 작게 유지하는 것이다.

### 통합 우선순위

| 순서 | 결정 |
| --- | --- |
| 1 | Native Qlib × matched-capitalization feasibility와 joint checkpoint spike |
| 2 | Frozen executable bundle, identity와 publisher recovery를 구조적으로 강제하는 contract |
| 3 | Revision/vintage temporal model과 실제 Qlib `ExecutionDataProfile` |
| 4 | Lean catalog projection, immutable evidence와 derived diagnostics 분리 |
| 5 | StrategyAgent output profile과 child data/resource boundary를 좁힌 첫 vertical slice |
| 6 | Same-branch stale-write, version compatibility와 extension trust boundary |
| 7 | Core contract 안정화 후 onboarding/skill subsystem |

---

## 10. 최종 평가

`qlibx-architecture-old.md`는 prototype을 단순 재포장하는 문서가 아니다. Qlib execution authority,
stored-result reuse, point-in-time access, parallel publication과 project-local extension을 하나의 제품
방향으로 묶었다는 점에서 좋은 upgrade 설계다.

현재 가장 큰 위험은 capability 부족이 아니라 **한 번에 너무 많은 capability를 일반화하면서 핵심
state와 identity 경계가 아직 문장 수준에 머물러 있다는 것**이다. 특히 frozen execution,
matched-capitalization checkpoint, temporal revision, identity와 publication recovery는 구현 중
세부사항으로 해결할 수 있는 문제가 아니다. 이 네 영역은 package 전체의 dependency와 persisted
schema를 결정한다.

두 독립 리뷰의 교차검증에서 가장 중요한 교훈은 **올바른 원칙을 선언한 것과 그 원칙을 구현이 우회할 수
없도록 구조적으로 강제한 것은 다르다**는 점이다. 반대로 repository의 다른 문서와 다르다는 이유만으로
일반 framework의 설계를 충돌로 간주해서도 안 된다. Target contract, prototype evidence와 project-local
운영 규칙의 지위를 구분해 판단해야 한다.

따라서 권장 판단은 다음과 같다.

- Architecture direction: 승인
- Package tree: provisional
- Data/run/artifact contracts: P0 수정 후 승인
- Native Qlib + matched-capitalization path: spike 통과 전 미승인
- Research graph, onboarding과 broad extension set: core vertical slice 이후 구현

이 순서로 진행하면 `qlibx`는 prototype의 capability를 잃지 않으면서도, 여러 runner/catalog/runtime이
다시 생기는 것을 막고 더 작은 public contract와 더 강한 reproducibility를 가진 제품이 될 수 있다.
