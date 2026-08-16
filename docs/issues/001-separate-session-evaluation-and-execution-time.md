# Frequency-agnostic evaluation과 execution 시간 계약을 분리한다

- **Status:** Closed
- **Closed by:** canonical PRD·Architecture와 validation scenario 정렬
- **Product authority:** `docs/vqapr-prd.md` §1.2, §3.1–§3.6, `UC-TIME-002`, §6.3, §14, §16
- **Architecture:** `docs/vqapr-architecture.md` §1–§3, §4.3–§4.4, §5.1, §5.4, §6.2, §8–§14, §16
- **Implementation boundary:** 이 closure는 문서 계약의 완료다. runtime source와 tests 구현은 별도 승인 작업이다.

## 문제

기존 문서는 frozen `ExecutionTable`의 distinct `trade_at`을 StrategyModel callback session의 원천으로 사용했다.
이 구조는 판단 시각과 체결 시각을 혼동할 뿐 아니라 execution input의 빈도가 callback 빈도를 결정하게 한다.

```text
minutely ExecutionTable 390 rows
    잘못된 기존 의미 → Strategy callback 390회
    필요한 의미      → frozen callback agenda가 선언한 횟수만 호출
```

표준 daily-close 사례에서도 StrategyModel은 04:00에 판단하고 15:30에 체결해야 한다.

```text
2024-03-05 15:30  전일 종가 observation이 available해짐
2024-03-06 04:00  StrategyModel callback과 decision
2024-03-06 15:30  execution
```

04:00 callback은 `available_at <= 04:00`인 observation만 읽고 15:30 execution price와 tradability를 볼 수 없어야
한다. 그러나 문제의 범위는 daily session 안의 두 시각에 그치지 않는다. 같은 날짜에 callback이 여러 번 올 수
있고, callback보다 늦은 execution을 기다리는 동안 새 callback이 올 수 있으며, valuation과 monitoring도 독립
cadence를 가질 수 있다.

## 최종 결정

### 1. Component-owned finite OperationAgenda

StrategyModel, Valuation, MonitoringPolicy configuration은 같은 typed finite `OperationAgenda` 형식을 사용하되
각자 독립적인 immutable agenda를 참조한다.

```text
OperationAgenda
- role
- timezone
- ordered occurrences: (occurrence_id, evaluation_time)
- semantic/content identity
- producer/provenance identity
```

이것은 cron, RRULE, live timer, venue calendar 또는 pluggable event source가 아니다. Project가 package 밖에서
모든 timezone-aware instants를 resolve하고 runtime은 frozen finite occurrences만 소비한다.

RunDefinition preflight는 component references를 바꾸지 않고 agenda identities와 inclusive `[start,end]` slices를
freeze한다. Flow는 이를 fixed priority와 stable IDs로 결정적으로 merge한다.

Observation rows와 ExecutionTable rows는 passive input이며 callback, valuation, monitoring occurrence를 만들거나
지우지 않는다. 같은 날짜에 zero, one, many Strategy callbacks가 가능하다.

### 2. Current-occurrence PIT boundary

StrategyModel에는 current occurrence 하나, `available_at <= evaluation_time` View와 permitted Account snapshot만
주입한다. 전체/future agenda, ExecutionTable, selected execution target, execution-time price와 tradability에
도달하는 경로는 없다.

observation row가 callback timestamp와 정확히 일치하지 않아도 callback은 발생한다.

```text
available_at = 04:00:00        보임
available_at = 04:00:00.000001 보이지 않음
```

### 3. Strategy economic payload와 Flow timing metadata

StrategyModel callback은 `NoDecision` 또는 timestamp 없는 economic `PortfolioIntent` payload를 반환한다.
Strategy가 selector-authoritative `decision_time`이나 `effective_after`를 제출하지 않는다.

Flow는 result validation 뒤 current frozen occurrence의 `evaluation_time`을 accepted-intent/evidence의
non-overridable `decision_time` metadata로 stamp한다. public wrapper/class/field 이름은 normative하지 않다.
`effective_after`는 current contract에서 제거하며 FillConvention input이나 compatibility alias로 남기지 않는다.

### 4. Intent-derived exact execution target

`FillConvention`은 Flow-stamped decision time과 frozen execution input으로 strictly-later exact target 하나,
snapshot selector, trade-price binding과 convention identity를 결정한다.

```text
04:00 callback + same-day close → 15:30 exact snapshot
04:00 callback + next open      → next eligible 09:00 exact snapshot
```

- `execution_time > decision_time`
- target은 inclusive `[start,end]` 안에 있다.
- equality override와 다른 row/column fallback은 없다.
- target은 `PortfolioIntent`가 생긴 뒤에만 resolve한다.
- `NoDecision`에는 execution row가 필요 없다.
- “decision이 속한 execution session”과 `offset_sessions`는 target authority가 아니다.

### 5. Atomic callback acceptance

Economic intent가 반환되면 Flow는 다음을 한 acceptance boundary로 stage한다.

1. economic payload validation
2. decision-time stamp
3. exact target resolution
4. causality, horizon, timezone와 provenance validation
5. Model state, decision evidence와 latest pending pointer commit

missing target, `target <= decision_time`, `target > end`, naive/inconsistent timezone, invalid intent/provenance에서는
해당 callback의 새 Model state, decision evidence, pending pointer, Account와 execution state를 commit하지 않는다.
이전 pending intent, committed authority와 immutable evidence는 유지한다.

`NoDecision`은 성공한 invocation으로 Model state를 commit하고 existing pending intent를 유지한다.

### 6. Latest accepted intent wins

한 Strategy·Account에는 accepted pending intent 하나만 있다. 새 accepted intent는 target resolution 뒤 previous
pending pointer를 교체한다.

```text
09:00 intent → 15:30 target
10:00 intent → 15:30 target
15:30 execution은 10:00 accepted intent만 소비
```

두 decision trace는 모두 남지만 별도 `SUPERSEDED` state, fill 또는 artifact는 만들지 않는다.

### 7. Fixed same-instant order

동일 instant의 최소 priority는 다음과 같다.

```text
1. previously accepted due execution
2. fill commit → execution-required valuation → feedback
3. Strategy callbacks (stable occurrence ID order)
4. independent valuation
5. independent monitoring
```

이전 pending execution과 later callback이 같은 instant이면 callback은 committed fill과 actual Account state를 본다.
Originating callback의 same-time execution은 strict `>` 때문에 금지된다.

### 8. Inclusive run horizon

`RunDefinition.start/end`는 모든 processed callback, execution, valuation, monitoring chain의 inclusive hard boundary다.
`end` instant의 due chain은 완료한다. `end` 밖 target은 callback atomic failure이고 successful finalization에는 pending
intent가 없다. Pending intent를 다음 run으로 이월하지 않는다.

## `UC-TIME-002`

`UC-TIME-002`는 다음 observable behavior를 하나로 추적한다.

- component-owned independent finite agendas
- execution-row-independent callback production
- current-occurrence PIT access
- Strategy economic payload와 Flow-stamped timing metadata 분리
- strictly-later exact execution target
- latest pending replacement
- callback atomic failure
- fixed same-instant priority
- inclusive run horizon과 empty-pending finalization
- deterministic replay evidence

## Superseded된 초기 해법

다음 daily-only 설계는 current contract가 아니다.

- `ExecutionTable.trade_at`이 session anchor와 callback 순서를 공급한다.
- `SessionTimeline(session_date, evaluation_time, execution_time)` 하나가 callback과 execution을 일대일로 묶는다.
- 모든 potential callback에 execution target을 preflight에서 요구한다.
- `previous.execution_time <= next.evaluation_time`으로 다음 callback 전 execution 완료를 강제한다.
- execution session이 없는 날짜의 callback과 한 날짜의 복수 callback을 비목표로 둔다.
- `StrategyModel.callback_time()` 하나로 전체 cadence를 표현한다.
- `PortfolioIntent.decision_time`과 `effective_after`를 Strategy가 제출한다.
- `FillConvention.offset_sessions`가 decision session을 기준으로 target을 고른다.

04:00→15:30 사례 자체는 여전히 유효한 validation fixture지만 framework scope를 daily로 제한하지 않는다.

## Acceptance criteria

### 문서 closure criteria — 완료

- [x] PRD가 component-owned agendas, passive data rows, Flow timing stamp, FillConvention target, pending
      replacement, fixed priority, horizon과 replay 조건을 `UC-TIME-002`로 정의한다.
- [x] Architecture가 같은 authority와 failure atomicity를 design contract, Flow state machine, evidence,
      preflight, traceability와 validation scenarios에 일관되게 반영한다.
- [x] 이 issue가 superseded daily-only contract와 current frequency-agnostic contract를 구분한다.
- [x] 세 canonical docs가 runtime source/tests 구현을 별도 작업으로 남긴다.

### Runtime implementation acceptance — 별도 작업, 미완료

- [ ] daily observation + intraday callbacks와 minutely observation + daily callback이 같은 contract로 실행된다.
- [ ] execution row density가 callback occurrence 집합·시각·순서를 바꾸지 않는다.
- [ ] callback 없는 시각에도 valuation과 monitoring이 발생한다.
- [ ] observation row가 callback timestamp에 없어도 callback이 발생하고 PIT equality/microsecond 경계가 맞다.
- [ ] 서로 다른 IANA zone의 같은 instant가 UTC ordering에서 일치하고 venue-local date selector는 UTC date가
      다른 경계에서도 올바른 local date를 사용한다.
- [ ] DST ambiguous/nonexistent local time은 explicit offset/fold 없이 artifact 생성 전에 거부된다.
- [ ] Strategy에는 current occurrence만 보이고 execution/future agenda 접근 경로가 없다.
- [ ] Flow가 accepted-intent/evidence decision time을 stamp하고 Strategy timing override를 거부한다.
- [ ] FillConvention이 strictly-later in-range exact target 하나만 선택한다.
- [ ] no-target, equality, after-end와 invalid provenance가 callback 전체를 atomic하게 rollback한다.
- [ ] accepted replacement, failed replacement, `NoDecision` pending 유지가 각각 계약대로 동작한다.
- [ ] same-instant due execution과 feedback이 later callback보다 먼저 commit된다.
- [ ] successful finalization에는 pending intent가 없다.
- [ ] agenda/slice, occurrence/evaluation time, Flow-stamped decision time/cutoff, intent identity, selected target,
      FillConvention/snapshot, consumed pending identity와 Account versions가 evidence에 남는다.
- [ ] complete frozen inputs가 같으면 full trace가 같고, row-density 비교는 selector-relevant inputs가 같은
      controlled case에서만 full-trace equivalence를 요구한다.

## 비목표

- cron/RRULE/frequency expression expansion
- live wall-clock timer와 data-arrival callback
- venue holiday/calendar inference와 별도 calendar provider
- pluggable general scheduler/event-source framework
- future agenda를 StrategyModel에 노출
- 여러 pending intent queue, cancellation, expiry와 run 간 recovery
- 별도 `SUPERSEDED` artifact
- MVP partial fill, child orders, TWAP/VWAP/pacing 또는 minutely execution algorithm
- public class/module/signature 고정

## Closure evidence

- PRD가 `UC-TIME-002`를 normative product contract와 use-case index에 정의한다.
- Architecture가 OperationAgenda authority, deterministic Flow merge, Strategy/Flow timestamp ownership,
  FillConvention target, pending replacement, failure atomicity, run horizon과 traceability/checklist를 정렬한다.
- Architecture current normative text에서 ExecutionTable/session stream/SessionEvent가 callback authority인 경로와
  Strategy-controlled `effective_after`가 제거됐다.
- 이 issue의 closure는 canonical docs + validation scenario alignment다. runtime source, tests와 package behavior는
  별도 approved implementation task 전까지 이 contract를 구현한 것으로 간주하지 않는다.
