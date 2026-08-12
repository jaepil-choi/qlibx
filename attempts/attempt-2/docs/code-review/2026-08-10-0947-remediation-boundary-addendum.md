# 2026-08-10 09:47 Remediation simplification addendum

Reviewer: Codex
Reviewed source commit: `98bdfba`
Current documentation commit: `e3bda99`
Canonical product contract: `docs/qlibx-prd.md`
Compared note: `docs/code-review/2026-08-10-1430-ideal-remediation-analysis.md`

## 0. 범위와 사용자 결정

이 문서는 Claude가 작성한 ideal-remediation 문서를 수정하거나 대체하지 않는다. 그 문서는 그대로 두고,
이 addendum은 사용자가 추가로 확정한 두 원칙만 반영한다.

1. Runtime 단계와 추상화를 불필요하게 늘리지 않는다.
2. Exchange 교체 가능성은 product goal이다. `KrxExchange`와 `AcademicExchange`는 분리하되 공통
   `BaseExchange`를 둔다.

이전 addendum에서 제안했던 TriggerPolicy, cursor 기반 별도 execution-feedback stream, 두 단계의 범용
pipeline, 공용 recovery journal은 현재 범위에 비해 복잡하다. 이 문서에서는 제거한다.

## 1. 목표 구조 — 네 덩어리만 유지한다

```text
1. Strategy
   bounded data + current Account + prior feedback
   -> DecisionIntent

2. ExecutionPreparation
   DecisionIntent + execution-time Account/market data
   -> executable request + constraint findings

3. BaseExchange
   KrxExchange 또는 AcademicExchange
   -> ExecutionResult

4. Commit and Feedback
   physical Fill만 Account에 commit
   ExecutionResult는 다음 Strategy에 feedback
```

세부 계산 함수는 여러 개일 수 있지만 public/runtime 단계로 각각 승격하지 않는다. 예를 들어 portfolio
construction, constraint adjustment와 validation은 `ExecutionPreparation` 내부의 순수 함수 호출이다.
각 함수를 독립적인 `DecisionStage` plugin으로 만들지 않는다.

이 구조에 쓰이는 패턴은 세 개면 충분하다.

- **IoC**: runtime이 Strategy와 Exchange를 호출한다. Strategy가 runtime을 지휘하지 않는다.
- **Strategy pattern**: `BaseExchange`의 concrete implementation을 선택한다.
- **Functional core / imperative shell**: 계산 함수는 값을 반환하고, Flow만 artifact 발행과 Account commit
  순서를 소유한다.

## 2. Constraint — stage list 대신 preparation 하나

### 2.1 단순한 책임 경계

Constraint를 Strategy 내부에 넣지 않는다는 기존 결론은 유지한다. Original intent를 보존하려면 constraint는
Strategy 다음에 있어야 한다.

다만 `construct -> adjust -> validate`를 각각 runtime plugin stage로 만들 필요는 없다. 하나의
`ExecutionPreparation`이 기존 pure operation을 정해진 순서로 호출한다.

```text
ExecutionPreparation.prepare(intent, execution_view, account)
  1. 필요한 경우 physical target으로 변환
  2. optional constraint policy가 있으면 best-effort 조정
  3. 같은 candidate를 독립 validation
  4. executable Exchange request 생성
  5. preparation result와 finding 반환
```

순서는 고정한다. User-configurable stage ordering이나 generic `DecisionStage[]`는 만들지 않는다. Constraint를
선택하지 않은 profile은 2번과 3번을 건너뛰며 benchmark dataset도 요구하지 않는다.

### 2.2 평가 시점

Preparation은 **execution event 시점**에 수행한다. Current constraint contract에는 price, lot size,
current quantity, capital과 Account identity가 필요하기 때문이다. Next-open 실행의 경우 전일 decision 시점에는
다음 날 open price가 아직 허용된 정보가 아니다.

```text
15:30 DecisionIntent 생성
다음 날 09:00 current Account + permitted open price + PIT benchmark 조회
             -> prepare -> Exchange
```

Decision 시점에는 immutable intent까지만 만든다. 이것은 단계를 늘리는 것이 아니라 미래 가격 사용을 막기
위한 한 개의 명확한 경계다.

### 2.3 Validation breach에 대한 확정 결정

사용자 결정대로 validation breach는 typed finding으로 기록하고 execution은 계속한다. Profile switch는 두지
않는다.

이 경우 current field name인 `eligible`은 의미가 맞지 않는다. `eligible=False`인데 항상 실행하면
“실행 가능 여부”가 아니기 때문이다. 구현 시 validation result를 `compliant` 또는 `passed`로 표현하고,
PRD의 “severity와 override는 future work” 문장도 이 advisory-validation 결정과 맞게 정정해야 한다.

단순한 결과 계약은 다음과 같다.

```text
prepare 계산 불가능         -> OperationError, Exchange 호출 없음
constraint breach           -> COMPLETE + finding, Exchange 호출
Exchange가 실제로 처리 못함 -> ExecutionResult diagnostic
```

Monitoring은 별개다. HOLD 날 가격 변화로 actual Account가 cap을 넘은 경우는 pre-execution validation이 아니라
standalone actual-account monitoring이 기록한다.

## 3. Exchange — goal이며 공통 Base class를 둔다

### 3.1 공통점과 차이점

`KrxExchange`와 `AcademicExchange`는 모두 Exchange지만 경제적 의미는 다르다.

- `KrxExchange`: physical order, cash, holding, lot, fee를 사용하고 실제 simulated Fill을 만든다.
- `AcademicExchange`: signed/fractional target을 zero-friction hypothetical state로 계산한다.

두 구현을 하나로 합치거나 Academic을 KRX 규칙에 맞추지 않는다. 공통 base는 lifecycle과 호출 모양만
정의하고, 계산 semantics는 subclass가 소유한다.

### 3.2 최소 Base class

두 current `match_batch()` signature를 억지로 동일한 긴 keyword 목록으로 만들지 않는다. 각 Exchange 전용
frozen request DTO를 사용하고 generic ABC로 묶는다.

```python
RequestT = TypeVar("RequestT")
ResultT = TypeVar("ResultT")

class BaseExchange(ABC, Generic[RequestT, ResultT]):
    exchange_id: str

    @abstractmethod
    def match_batch(self, request: RequestT) -> OperationOutcome:
        """Return the Exchange-specific typed result without mutating Account."""

class KrxExchange(BaseExchange[KrxBatchRequest, KrxMatchResult]):
    ...

class AcademicExchange(BaseExchange[AcademicBatchRequest, AcademicMatchResult]):
    ...
```

Base class가 소유할 것은 다음뿐이다.

- stable `exchange_id`
- immutable request를 받는 `match_batch()` lifecycle
- typed `OperationOutcome` 반환
- Account를 직접 변경하지 않는다는 규칙

`add_instrument`, lot rounding, fee, cash clipping, signed weight와 hypothetical NAV는 공통 base에 올리지 않는다.
한 subclass에만 필요한 기능이기 때문이다.

### 3.3 Composition

```text
QlibxProject.run_daily()    -> KrxExchange
QlibxProject.run_academic() -> AcademicExchange
```

각 public flow는 계속 분리한다. `BaseExchange`가 생긴다고 daily와 academic flow를 합치지 않는다.
향후 새 Exchange를 추가할 때 subclass와 해당 profile wiring을 추가한다. 지금은 plugin registry나 arbitrary
class-path loading까지 만들지 않는다.

### 3.4 검증 기준

- 두 Exchange가 모두 `BaseExchange` subclass다.
- 두 구현은 각자 typed request/result를 유지한다.
- 동일 frozen request는 동일 result를 만든다.
- Exchange는 Account나 StrategyMemory를 직접 변경하지 않는다.
- Exchange ID와 config fingerprint가 execution artifact에 기록된다.
- Academic result를 physical Fill이나 actual Account state로 표시하지 않는다.

## 4. Lookback — 확정된 두 종류만 구현한다

사용자가 확정한 `rows`와 `calendar`만 둔다. sessions/trading-day lookback은 만들지 않는다.

```python
class RowsLookback:
    rows: int

class CalendarLookback:
    years: int = 0
    months: int = 0
    days: int = 0
    calendar_timezone: str
```

`ComponentRequirement.lookback`이 exact window를 선언하고 View가 강제한다. 별도의 maximum authority와
query-time lookback을 동시에 만들지 않는다.

- `rows`: PIT gate를 통과한 행을 instrument별 `available_at` 내림차순으로 N개까지 반환한다.
- `calendar`: local calendar date를 이동해 만든 start와 `as_of` 사이의 `available_at`을 반환한다.
- 둘 다 전체 history를 먼저 읽고 pandas에서 자르지 않고 Store query에 반영한다.
- 부족한 행은 있는 만큼 반환하고 `AccessRecord`에 요청량과 실제량을 기록한다.

Dataset 전체 `available_at_min`만으로 종목별 coverage를 사전 판정하지 않는다. 종목이 아예 0행이면 declared
universe 없이 부족 종목을 알아낼 수도 없다. 따라서 lookback 자체는 조회 범위만 책임지고, 계산에 필요한
최소 관측치 판단은 Strategy의 경제적 규칙으로 둔다.

동일 `available_at`이 여러 행에 존재할 수 있으므로 rows 선택의 deterministic tie-break는 registered logical
key를 사용한다. `CalendarLookback`은 years/months/days 중 적어도 하나가 양수여야 한다.

## 5. Execution feedback — 현재 scope의 최소 fix

Zero-dealt 결과를 `Fill`로 만들거나 Account journal에 넣지 않는다. Existing `ExecutionEvidence`가 이미 orders,
fills와 diagnostics를 보존하므로 StrategyView에 직전 execution result를 노출한다.

```python
StrategyView.latest_execution_result() -> ExecutionEvidence
```

- dealt quantity 0과 `LOT_ROUNDING`, cash/holding clipping reason이 보인다.
- Account cash/position은 실제 Fill이 없으면 변하지 않는다.
- StrategyResult는 해당 execution artifact access를 lineage에 기록한다.

별도 execution cursor/stream은 현재 구현하지 않는다. 대신 current daily profile이 한 Strategy decision 사이에
소비해야 할 execution result를 하나로 한정한다는 전제를 문서와 run validation에 명시한다. Multiple venue,
sliced order, 여러 execution 사이에 decision이 없는 lifecycle을 지원할 때 feedback batch를 추가한다.

## 6. Cadence와 recovery — 현재 구조를 유지한다

### Cadence

현재 `DailySimulationSpec.decision_times`를 유지한다. Strategy-owned `schedule()`이나 별도 TriggerPolicy 계층은
추가하지 않는다. Entry/exit 조건은 같은 decision callback에서 `HOLD`/`TARGET`으로 표현한다.
새 trigger 종류가 실제로 필요해질 때 scheduler contract를 다시 검토한다.

### Recovery

Daily와 Academic은 checkpoint shape가 다르므로 공통 `DurableRunJournal`을 만들지 않는다. Daily recovery가
읽기 어렵다면 Daily 전용 helper/class로만 추출한다. Academic recovery는 현재 구현을 유지한다. 공통 코드가
실제로 반복될 때만 작은 helper를 추출한다.

## 7. 단순화된 구현 순서

| 순서 | 작업 | 범위 |
|---|---|---|
| 1 | Current-support map, module map, architecture 정정 | 문서만 |
| 2 | `BaseExchange` + 두 concrete subclass | flow는 합치지 않고 run-level dependency로 주입 |
| 3 | single `ExecutionPreparation` + constraint | pass-through parity 후 prepare 내부 고정 순서로 연결 |
| 4 | normalized Parquet + `rows`/`calendar` lookback | 신규 registration snapshot, 기존 registration explicit reindex |
| 5 | StrategyResult v3 + latest execution feedback | exact dataset/execution access를 한 번의 schema cut으로 통합; v1/v2 reader 제거 |
| 6 | `QlibxProject` facade 보강 | existing flow를 감싸고 sample을 facade로 이동 |
| 7 | directory 이동 | specs/view/execution semantic path로 즉시 전환; shim 없음 |

Recovery refactor는 위 순서의 필수 선행 단계가 아니다. `ExecutionPreparation`이 artifact를 추가할 때 current
recovery publication 계약에 필요한 최소 변경만 하고, 먼저 거대한 공용 journal을 만들지 않는다.

## 8. 최종 구조

```text
QlibxProject
  -> Strategy.run(StrategyView)
  -> DecisionIntent
  -> ExecutionPreparation.prepare(...)
  -> BaseExchange.match_batch(...)
       |- KrxExchange
       `- AcademicExchange
  -> ExecutionResult
  -> physical Fill만 Account.commit
  -> latest ExecutionEvidence를 다음 StrategyView에 제공
```

이 구조는 사용자의 mental model과 직접 대응한다. Strategy가 목표를 만들고, preparation이 실행 후보를
정리하며, 선택한 Exchange가 결과를 계산하고, actual Fill만 Account에 반영된 뒤 다음 Strategy가 feedback을
본다. 각 책임은 분리되어 있지만 runtime 단계 수와 확장 abstraction은 최소로 유지한다.