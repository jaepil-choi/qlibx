# 네 개의 읽는 자, 하나의 루프, 그리고 없는 모양 — 2026-09-08

## 범위와 근거

기준 HEAD `2fad4ed0`(브랜치 `develop`, working tree clean). `src/vqapr` 33,813줄.

오너의 문제 제기 셋에서 나왔다.

1. *"DataModel, StrategyModel, Constraint, Exchange는 전부 data가 feed되고 그것을 읽어 판정을 내리는
   같은 종류의 객체인데 흩어져 있다. 예전에 Occurrence Flow로 통일하려던 흔적이 보인다. EventLoop
   같은 이름이 맞고, 클래스 이름에 그것이 쓰는 패턴을 크게 박아 넣는 편이 직관적이다."*
2. *"domain/에 개념이 충분한지 모르겠다. feed되는 데이터는 2d wide panel(열이 종목)이거나 long
   dataset인데 그 model/domain이 정의되어 있지 않다."*
3. *"design pattern · software architecture 관점에서 OOP적으로 다시 refactoring·redesign하는 데 필요한
   것을 검토하자. fast development stage라 breaking change는 허용하고, 나중의 code audit과
   scalability를 고려해 설계한다."*

**감사한 것:** 네 확장점의 계약 전문(`authoring.py`, `calls.py`, `exchange/venue.py`), 그 넷을 부르는
자리 전문(`flow/callback.py` `dispatch`, `flow/datamodel.py` `DataModelPhase`, `flow/execution.py`
`execute_due`, `flow/valuation.py` `value_due`, `constraints/evaluation.py`), 척추(`flow/loop.py`,
`flow/simulation.py`), 조립(`flow/orchestration.py` `_run_strategy`, `FlowContext`), 데이터 평면
(`data/panel.py`, `data/windows.py`, `data/store.py` 시그니처, `Grain`), `domain/` 전체 심볼 목록,
`public.py`, 저자가 실제로 쓰는 파일(`agent/sample/reversal_5d.py`, `agent/sample/exchange.py`),
그리고 트리 전체에 대한 grep 계수(아래 §5). 오너 판정 문서는 PRD §2.3, 아키텍처 §1·§2·§8·§10,
`the-panel-the-surface-and-the-run.md` §2를 읽었다.

**감사하지 않은 것:** 함수 본문의 의미 대부분, 테스트, `cli/`·`report/`·`workspace.py`·
`declarations.py`(5,900줄 — 제품 표면이며 이 리뷰의 질문 밖), 성능. **이 문서는 배치와 계약의 문제만
다루고 동작 결함은 다루지 않는다.** 아래 어느 항목도 버그가 아니다.

같은 날의 두 리뷰가 이미 다룬 것은 반복하지 않고 가리킨다 —
[`flow/`와 `evidence/` 구조](2026-09-08-flow-and-evidence-structure.md)(kind축·phase축 혼재,
`OccurrenceFlow`의 무타입, `record.py` 승격, `evidence/` 해소)와
[아젠다의 role](2026-09-08-the-agenda-carries-a-role-nobody-chose.md)(DataModel run의
`STRATEGY_CALLBACK`, 죽은 우선순위·provenance).

---

## 0. 한 장

오너의 세 진술은 전부 참이고, 셋이 **하나의 부재**를 다른 쪽에서 보고 있다.

```text
[이름 없는 패턴]  선언한다 → 프레임워크가 그 시각의 bounded view를 먹인다 → 판정 하나를 돌려준다
                   ↑ 네 확장점이 이 한 패턴을 네 가지 철자로 쓴다                       (§1)
                   ↑ 이 패턴을 도는 루프는 있는데 이름도 타입도 없다                     (§2)
                   ↑ "먹이는 것"의 모양(wide / long / cross-section / series)에 타입이 없다 (§3)
```

- **§1** 넷 중 셋은 같은 선언·같은 view·같은 mixin을 쓰고도 base가 다르고(`Model` 둘, `Constraint`
  하나, `Protocol` 하나), 넷째(`Exchange`)는 선언 어휘 자체가 다르다. 부르는 쪽도 넷이 다르다:
  phase 객체 둘, 자유 함수 하나, venue 자신 하나. 등록부에는 이미 이름이 있다 —
  `ComponentKind`는 정확히 이 넷을 센다 — **클래스만 없다.**
- **§2** `OccurrenceFlow`는 정적 아젠다와 실행 중 발행되는 due 항목을 `(utc, priority, id)`로 병합하는
  **이산 사건 시뮬레이션 루프**다. 오너가 부른 이름 `EventLoop`가 맞다. 조여야 할 것은 이름보다 그
  루프가 사건·핸들러·결과를 **타입으로** 나르게 하는 것이고, 그러면 두 kind의 비대칭이 배치에서
  드러난다(앞 리뷰 §3).
- **§3** 데이터 모양은 다섯인데 타입이 있는 것은 하나 반이다. wide 2d는 `Panel`(Arrow)이 있고, long은
  `Observation`이 **`authoring.py`에** 있고, **cross-section·series·계정 history의 2d는 타입이
  없다** — `Mapping[str, Decimal]` 58곳, `Mapping[str, object]` 49곳, `tuple[object, ...]`. 저자가
  받는 것도, 돌려주는 것도(`target_weights`, `ConstraintBounds`, `MarkBatch`) 전부 그 dict다.
- **§5** 그 부재를 메우는 것이 손이다: `isinstance` 585곳, `object.__setattr__` 62곳, `-> object` 30곳,
  검증 체계 둘(pydantic 7모듈, dataclass+`__post_init__` 나머지), 타입 검사기는 게이트에 없다.

**결론은 하나다. 패턴에 이름을 주면 나머지가 그 이름을 따라 자리를 잡는다.** 순서는 §7.

---

## 1. 네 개의 읽는 자, 네 가지 철자

`ComponentKind`(`extension/component.py:29`)는 `DATA_MODEL · STRATEGY_MODEL · CONSTRAINT · EXCHANGE`
넷이다. 등록·fingerprint·conformance·scaffold는 이미 이 넷을 **한 종류**로 다룬다. 런타임 계약은
그렇지 않다.

| | DataModel | StrategyModel | Constraint | Exchange |
|---|---|---|---|---|
| **base** | `Model(ABC)` | `Model(ABC)` | `Constraint(ABC)` — Model 아님, `memory` 없음 | `Exchange(Protocol)` |
| **읽기 선언** | `Model.inputs()` | `Model.inputs()` | `Constraint.inputs()` — `Model`의 것을 **그대로 복사** (`authoring.py:1133–1152`) | `execution_requirements()` → `ExecutionFieldRequirement` — **다른 타입 계열** |
| **먹이는 것** | `DataModelContext(window)` | `StrategyModelContext(occurrence, window, account, bounds, history)` | `ConstraintContext(window, instruments)` | `ExactExecutionSnapshot` + `AccountSnapshot` + `OrderBatch` — **Call 객체 없음** |
| **view의 성질** | `ModelWindow`(lookback 창) | `ModelWindow` | `ModelWindow` **둘** — callback 시각용, fill 시각용(`constraint_window_at`) | **점 조회** (`scan.exact_execution_snapshot`) |
| **콜백** | `compute(call) -> Rows` | `decide(call) -> Hold \| Rebalance` | `project(call) -> ConstraintBounds` · `monitor(call, account, bounds) -> ConstraintFinding` | `execute(orders, account, snapshot) -> FillBatch` |
| **부르는 자** | `DataModelPhase.dispatch` | `CallbackPhase.dispatch` | `constraints/evaluation.py`의 **자유 함수** ← `CallbackPhase`·`ValuationPhase` 둘이 부름 | `ExecutionPhase.execute_due` |
| **반환 게이트** | `validated_output` | `_raise_callback_return_type` + `validate_economic_intent` | `evaluation.py`의 `isinstance` | **venue 자신**(`accepted_requests` · `validate_requests`) |
| **로더** | `load_data_model` | `load_strategy_model` | `load_constraint` + id 대조 | `load_exchange` + `execute` 오버라이드 거부 |
| **프레임워크 주입 경로** | — | 콜백마다 `strategy.recorder =` 대입 | `window.for_consumer(id)` view | `object.__setattr__(venue, "_registry", …)` (`flow/execution.py:313`) |

읽을 것은 세 줄이다.

**① 셋은 이미 같다.** DataModel·StrategyModel·Constraint는 `inputs()` 한 선언, `requirements_for` 한
fan-out, `_DeclaredReads` 한 mixin(`calls.py:107` — *"all three roles read the same way -- that
sameness is the point"*)을 쓴다. 다른 것은 base 이름과 콜백 이름뿐이다. `Constraint`가 `Model`
바깥에 있는 이유는 docstring이 적었다 — *"`Model` carries `memory`, and a constraint is a stateless
predicate"*. 그 이유는 타당하지만 결론이 틀렸다: **memory가 있는 것과 읽기를 선언하는 것은 다른
축**이고, 지금은 두 축을 상속 하나로 접느라 `inputs()`·`requirements()`를 복사했다.

**② 넷째는 같은 패턴을 다른 어휘로 쓴다.** Exchange도 *선언하고*(`execution_requirements`) *먹이를
받고*(`ExactExecutionSnapshot`) *판정한다*(`FillBatch`). 다른 것은 창이 아니라 **점**이라는 grain
하나다. 그런데 선언은 `DataRequirement`가 아니라 `ExecutionFieldRequirement`이고, 먹이는 `Call`이
아니라 인자 셋이며, 프레임워크가 넣어 줘야 하는 roster는 `object.__setattr__`로 private 필드에
꽂힌다. 앞 리뷰 §7이 *"근거는 타당하지만 결론 내지 않는다"*고 남긴 자리가 이것인데, **원인은 Exchange가
Call을 받지 않는다는 것**이다. Call이 있으면 registry는 그 안에 실려 오고 venue는 아무것도 저장할
필요가 없다.

**③ 부르는 자가 넷 다 다르다.** `DataModelPhase`와 `CallbackPhase`는 phase 객체, Constraint는 자유
함수 셋(`project_constraints` · `merged_constraint_bounds` · `evaluate_constraints`)을 phase 둘이
따로 부르고, Exchange는 phase 안에서 직접 호출된다. 같은 패턴의 네 인스턴스를 부르는 코드가 넷이면
**"컴포넌트 하나를 부른다"는 것이 무엇인지가 어디에도 적혀 있지 않다** — 로더가 arity로 검사하는 것
(`_validate_callback_signature`), phase가 `isinstance`로 검사하는 것, 그리고 아무도 검사하지 않는 것이
섞인다.

### 이름은 이미 있다

오너가 *"패턴 이름을 클래스에 박자"*고 했다. 새로 지을 필요가 없다 — **`Component`**가 등록부·로더·
scaffold·conformance에서 이미 이 넷의 이름이다. 없는 것은 그 이름의 **런타임 base**다.

```python
class Component(ABC, Generic[CallT, JudgmentT]):
    """선언한다 → 그 시각의 bounded Call을 받는다 → 판정 하나를 돌려준다."""
    component_id: str
    def reads(self) -> Mapping[str, DatasetInput]: ...          # 오늘의 inputs(); 한 곳
    def requirements(self) -> tuple[DataRequirement, ...]: ...  # 한 곳
    @abstractmethod
    def judge(self, call: CallT) -> JudgmentT: ...              # 이름은 역할이 정한다 (아래)
```

역할별 콜백 이름(`compute` · `decide` · `project`/`monitor` · `execute`)은 남긴다. 저자가 읽는 동사이고
PRD §2.3이 두 역할을 동사로 가른다. `Generic[CallT, JudgmentT]`가 나르는 것은 **phase가 무엇을 먹이고
무엇을 받는지**이며, 그것이 §5의 `isinstance` 게이트 대부분을 타입 검사로 바꾼다. `memory`는
`Component`가 아니라 **`Stateful` mixin**(또는 `Model(Component)`)으로 올린다 — Constraint가 복사 없이
`Component`가 되는 길이 그것이다.

Exchange를 `Component`로 넣을지는 열린 결정(§8-2)이다. 넣으면 `ExecutionFieldRequirement`가
`DatasetInput`의 한 갈래(grain `point`)가 되고 `bind_registry_to_venue`가 사라진다. 안 넣으면 §1의
표는 3+1로 남고, 그것도 지금보다 낫다.

---

## 2. 척추의 이름 — `OccurrenceFlow`는 EventLoop다

`flow/loop.py:58`의 `run()`은 이렇다.

```text
static  = FrozenRun.dispatch_order(layer)          # freeze 시점에 전부 아는 사건들
due     = state.current.pending_accepted_intent    # 실행 중에 발행되는 사건, 한 번에 최대 하나
while static or due:
    다음 = min(static.head, due) by (utc, priority, id)   # due의 priority = -1
    traces.append(dispatch(다음))
return finish(traces)
```

두 사건원(**정적 스케줄**과 **런타임에 mint되는 큐**)을 하나의 시계로 병합하고, 시계가 가장 이른
사건으로 전진하며, 핸들러가 새 사건을 mint할 수 있다. 이것이 **discrete-event simulation의 루프**이고,
그 루프의 통칭이 event loop다. 오너의 이름이 맞다. `OccurrenceFlow`라는 이름은 사건원 하나
(occurrence)만 가리키고 due를 감춘다 — `_pending_due`가 왜 있는지는 이름으로 알 수 없다.

앞 리뷰 §2가 잰 것(타입 0, 생성자 계약 없음, 54줄)에 **이 리뷰가 보태는 것은 둘**이다.

**① 사건에 타입이 없어서 dispatch가 문자열 분기다.** `SimulationFlow._dispatch_static`은
`occurrence.role is OperationRole.STRATEGY_CALLBACK`으로 갈라 나머지 role은 `ValueError`로 거절한다.
`DataModelFlow`는 role을 보지 않는다. 즉 **같은 `OperationOccurrence`가 어느 루프에 들어가느냐에 따라
다른 뜻**이고, 그것이 다른 리뷰의 `A`(DataModel run이 `STRATEGY_CALLBACK`을 든다)가 생긴 자리다.
사건이 `OccurrenceEvent[kind]`·`DueEvent`처럼 **타입으로 갈리면 role 필드도, 문자열 분기도, 그
identity 오염도 없다.**

**② due 큐가 "최대 하나"인 것은 루프의 모양이 아니라 도메인 규칙이다.** 아키텍처 §8.2: *"새 accepted
intent는 latest pending pointer를 교체한다"*. 그 규칙(전략 하나에 pending 하나)이 `_pending_due`가
`Envelope | None`을 돌려주는 시그니처에 굳어 있다. 루프는 큐를 **큐**로 보고, "하나만 남긴다"는 큐
정책이 되어야 한다. 그래야 §15-5의 live 확장(사건원이 셋 이상)에서 루프를 다시 쓰지 않는다.

### 목표 계약

```python
class Event(Protocol):
    def sort_key(self) -> tuple[datetime, int, str]: ...

class EventLoop(ABC, Generic[EventT, TraceT, ResultT]):
    def __init__(self, *, schedule: Sequence[EventT], on_progress: Callable[[], None] | None): ...
    def run(self) -> ResultT: ...                       # 한 번 쓰인 walk, 오늘 그대로
    @abstractmethod
    def handle(self, event: EventT) -> TraceT: ...      # 타입별 핸들러로 위임
    @abstractmethod
    def finish(self, traces: tuple[TraceT, ...]) -> ResultT: ...
    def pending(self) -> Iterable[EventT]: return ()    # 사건원 둘째; 정책은 서브클래스

class StrategyEventLoop(EventLoop[StrategyEvent, StrategyTrace, SimulationResult]): ...
class DataModelEventLoop(EventLoop[OccurrenceEvent, DataModelTrace, DataModelResult]): ...
```

`Handler`는 오늘의 phase다 — `CallbackPhase` → `CallbackHandler`, `ExecutionPhase` →
`ExecutionHandler`, `ValuationPhase` → `ValuationHandler`, `DataModelPhase` → `ComputeHandler`.
바뀌는 것은 이름과 **핸들러가 `Component`를 부르는 한 가지 방법**(§1 ③)뿐이고, 본문은 record 147이
옮긴 그대로다.

### 이름 규칙 하나가 뒤집힌다

아키텍처 §10의 판정 규칙 셋째 줄 — *"이름: 개념인가 패턴인가? base · protocol · service · manager는
패턴이다"* — 는 **패턴 이름을 피하라**는 규칙이다. 오너의 오늘 진술은 그 반대다: *"클래스에 그것이
쓰는 패턴을 크게 박아라"*. **오너가 같은 날 판정했다(§8-1):** §10의 그 줄은 처음 쓸 때 패턴을 섣불리
강제할까 봐 적은 것이고, 원칙은 *intent·behavior > pattern·implementation*이다. 패턴 이름은 쓰되,
아키텍처는 그 패턴이 현재 선택이고 요구가 바뀌면 바뀔 수 있다고 적는다. §10의 그 줄은 그렇게 다시
쓴다 — 안 고치면 다음 세션이 그 줄을 근거로 되돌린다.

---

## 3. domain/에 없는 명사 — 데이터의 모양

`domain/`에 있는 것: `identifiers` · `instruments`(+roster) · `values`(timestamps·rows·memory·enums·
marks를 배너로 접음) · `errors` · `agendas`. **데이터가 어떤 모양인가에 대한 타입은 하나도 없다.**
그 타입들은 이렇게 흩어져 있다.

| 모양 | 뜻 | 오늘 어디에, 무엇으로 | 타입 |
|---|---|---|---|
| **Grain** | 한 행이 무엇인가 (`instrument_instant` / `instant` / `rows`) | `data/datasets.py:41` — 등록 모듈 안 | 있음 |
| **Wide 2d** | instant × instrument, 열이 종목 | `data/panel.py` `Panel`·`PanelWindow` (Arrow) | 있음 |
| **Wide 2d (둘째)** | 계정 history의 field 하나 | `AccountHistory.panel(field)` → `Mapping[str, tuple[object, ...]]` — dict-of-tuples, Arrow 아님 | **없음** |
| **Long** | (instant, instrument, values) 행 스트림 | `authoring.Observation` + `domain.values.Rows`(list of dict) + `data/store.ObservationBatch` — **세 표현** | 절반 |
| **Cross-section** | instant 하나 × N 종목 | `PanelWindow.current()`·`latest()` → `Mapping[str, object]`; `ExactExecutionSnapshot.rows`; `MarkBatch`; `ConstraintBounds.lower/upper_weights`; `Rebalance.target_weights`; `EconomicAccountView.weights()`; `ExecutionPhase`의 `prices` dict | **없음** — `Mapping[str, Decimal]` 58곳, `Mapping[str, object]` 49곳 |
| **Series** | N instant × 종목 하나 | `PanelWindow.series()` → `tuple[object, ...]`; `AccountHistory.series(field)` | **없음** |

세 가지가 보인다.

**① 오너의 진술 그대로다 — wide와 long 사이의 구분은 `Grain`에 선언되어 있고 `read()`/`rows()`
동사로 강제된다(소유자 결정 B안, 2026-09-02). 하지만 그 결정이 타입까지 내려오지 않았다.**
`_DeclaredReads.rows()`의 반환 어노테이션은 bare `tuple`이고, `Observation`은 저자 표면 파일에 있고,
`Grain`은 등록 파일에 있다. *"grain이 모양을 정한다"*는 도메인 사실인데 도메인 층에 없다.

**② 가장 많이 쓰이는 모양에 이름이 없다.** 전략이 **돌려주는 것**(`target_weights`), 제약이
**돌려주는 것**(`ConstraintBounds`), 평가가 **돌려주는 것**(`MarkBatch`), 거래소가 **받는 것**(가격
스냅샷) — 전부 cross-section이고 전부 `dict[str, Decimal]`이다. 그래서 `merged_constraint_bounds`가
dict comprehension으로 max/min을 돌리고, `SingleNameCap._worst`가 `sorted(weights.items())`를 돌고,
`plan_orders`가 `_targets`·`_prices`로 dict를 다시 검증한다. **한 모양에 대한 연산이 소비자마다
다시 쓰인다.** 3,000 종목 universe에서 이것이 Python dict 루프로 남는 것이 확장성의 첫째 한계다
(§6).

**③ `Panel`은 있으나 저자 경계에서 끊긴다.** `PanelWindow.values[name]`은 `to_pylist()`로 tuple을
만들고, 샘플 전략은 그것을 다시 `Decimal(str(v))`로 감싼다(`reversal_5d.py:52`). Arrow는 창까지만
오고 저자는 Python 스칼라를 받는다. 이것은 issue 061의 처방(lazy 변환)이 맞았다는 뜻이지, 모양이
저자에게 전달됐다는 뜻은 아니다.

### 제안 — `domain/shapes.py`

```python
class Grain(StrEnum): INSTRUMENT_INSTANT · INSTANT · ROWS       # data/datasets.py에서 이동
                                                              # (Exchange가 Component가 되면 POINT 추가)
class CrossSection(Generic[T]):      # instant 하나, 종목 → 값. Mapping 인터페이스 + 집합 연산
class Series(Generic[T]):            # 종목 하나, instant → 값
class Panel(Protocol):               # instant × instrument. current()/series()/window()
                                     #   Arrow 구현은 data/panel.py에 남는다
class Observation / Long             # authoring.py에서 이동; rows() 반환의 원소
```

그리고 **Call의 동사가 모양을 돌려주고, 판정도 모양으로 말한다**:

```python
call.read(alias, field) -> Panel            # wide
call.rows(alias)        -> tuple[Observation, ...]   # long
panel.current()         -> CrossSection[T]
panel.series(name)      -> Series[T]
Rebalance(target_weights: CrossSection[Decimal], ...)
ConstraintBounds(lower: CrossSection[Decimal], upper: CrossSection[Decimal])
MarkBatch -> CrossSection[Mark]
```

`merged_constraint_bounds`는 `CrossSection.elementwise(max)` 한 줄이 되고, `SingleNameCap._worst`는
`abs(weights).argmax()`가 된다. **새 필드는 하나도 없다** — 이것은 lineage가 아니라 모양이고,
"YAGNI over lineage"는 attribute에 대한 규칙이다. dtype(`Decimal` 유지 vs Arrow decimal128)은 오너
판정을 요구하므로 열어 둔다(§8-3). 모양 타입은 dtype과 독립이며, 먼저 들어가도 된다.

`domain/values.py`가 다섯 파일을 배너로 접은 것(다른 리뷰 `F`)도 여기서 같이 본다. **`shapes.py`가
생기면 `values.py`의 `rows.py` 절이 그리로 가고, `marks.py` 절은 `CrossSection[Mark]`의 별칭이 된다.**
접힌 파일을 되펼치자는 게 아니라, 접힌 것 중 모양인 것이 제 층으로 가는 것이다.

---

## 4. 척추의 세 층이 지금 어떻게 만나는가 — 그리고 어떻게 만나야 하는가

§1·§2·§3을 합치면 런타임의 층은 셋이고, 오늘은 그 경계가 셋 다 흐리다.

```text
오늘                                          목표
────────────────────────────────────────      ────────────────────────────────────────
OccurrenceFlow (untyped)                      EventLoop[Event, Trace, Result]
  ├ SimulationFlow                              ├ StrategyEventLoop
  │   FlowContext (17필드 bag, object 포트 2)    │   StrategyRuntime (typed ports)
  │   ├ CallbackPhase ─┐                        │   ├ CallbackHandler  ─┐
  │   ├ ExecutionPhase ├ 각자 Component를        │   ├ ExecutionHandler ├ Handler.call(component, Call)
  │   └ ValuationPhase ┘ 다르게 부른다           │   └ ValuationHandler ┘ 한 방법
  └ DataModelFlow                               └ DataModelEventLoop
      DataModelPhase                                └ ComputeHandler
                                              Component[CallT, JudgmentT]
authoring.Model / Constraint / Protocol         ├ DataModel  · StrategyModel(Stateful)
calls.*Context (mixin 공유)                     ├ Constraint · Exchange (§8-2)
exchange 인자 셋                                └ Call: DataCall · StrategyCall · ConstraintCall · ExecutionCall
dict / tuple / Mapping                        domain.shapes: Panel · CrossSection · Series · Observation
```

층 사이의 규칙은 셋이고 전부 이미 오너 판정이다 — 이 리뷰가 새로 얹는 규칙은 없다.

- **Loop는 경제 규칙을 소유하지 않는다**(아키텍처 §1.2·§8.1). `EventLoop`는 정렬·전진·위임만 한다.
- **Component는 서로를 부르지 않는다**(§1.3 세 줄 규칙). Handler가 순서를 안다.
- **Store 핸들은 소비자에게 가지 않는다**(§2.2). `Call`이 유일한 통로이고 `shapes`는 값이다.

`FlowContext`는 이 그림에서 **사라지는 것이 아니라 타입을 얻는다.** 오늘 `scan_session: object |
None`·`registry: object | None`인 두 포트와, 콜백마다 `ModelWindow`를 새로 만드는 lambda 셋
(`_run_strategy`)이 `StrategyRuntime`의 typed 필드가 된다. 0.6.0 호출 흐름 제안
(`docs/refactoring/2026-09-07-v060-call-flow-proposal.md` §3 *"FlowContext는 완성된 상태로
만들어진다"*)과 같은 방향이다.

---

## 5. OOP 위생 — 숫자로

배치 문제가 아니라 **계약을 손으로 대신한 양**이다. 전부 `src/vqapr` grep.

| 무엇 | 수 | 뜻 |
|---|---|---|
| `isinstance(` | **585** (flow 167 · exchange 60 · domain 55 · account 44 · portfolio 39 …) | 타입이 나르지 않는 계약을 런타임에 손으로 검사한다. `SimulationFlow.__init__`이 15개, `evaluate_constraints`가 7개 |
| `object.__setattr__` | **62** | frozen dataclass를 `__post_init__`에서 뚫어 정규화·캐시한다. 값 검증과 memo가 같은 구멍을 쓴다(다른 리뷰 `E`) |
| `-> object` | **30** | 척추(`loop.py`)·phase 반환·`FlowContext` 포트. 위 585의 원인 절반 |
| `Protocol` | **2** (`Exchange`, `DatasetCatalog`) | |
| `ABC` | **5**, 전부 `authoring.py` | 저자 계약만 추상이고 엔진 계약(`OccurrenceFlow`)은 평범한 클래스 |
| pydantic `BaseModel` | **7 모듈** (`run.py` · `component.py` · `sources.py` · `record.py` · `document.py` · `declarations.py` · `workspace_document.py`) | 저장되는 문서는 pydantic, 나머지 값은 dataclass+수동 검증 — **검증 체계 둘** |
| `Trace` / `Result` / `Evidence` 클래스 | **20** (Evidence 8 · Result 8 · Trace 4) | 세 평행 계열, 공통 base 없음, 한 kind에 셋이 다 있다 |
| 타입 검사기 | **없음** — `pyproject.toml`에 mypy/pyright 미선언, `lint`는 ruff뿐 | `Generic`을 도입해도 게이트가 없으면 어노테이션은 문서다 |

읽을 것.

- **585는 두 종류다.** 저자 경계의 검사(`Constraint.project must return ConstraintBounds`,
  `Observation(values={"a b": 1})` 거절)는 **남아야 한다** — 어노테이션은 거짓말할 수 있고 저자는
  대부분 달지 않는다(§10.2). 내부 경계의 검사(`frozen_run must be a FrozenRun`, `state must be a
  RunStateRepository`)는 타입 검사기가 있으면 **삭제 대상**이다. 둘을 가르는 선이 오늘 없다. `Component`와
  `EventLoop`가 Generic이 되면 선이 생긴다: **Component가 돌려주는 것은 검사하고, 프레임워크가 넘기는
  것은 믿는다.**
- **검증 체계는 하나로 수렴해야 한다.** 메모리에 이미 그 함정이 있다 — *"pydantic model_copy는
  재검증하지 않는다, 규칙 든 frozen 모델 변형은 `.replace()`로"*. dataclass 쪽은 `object.__setattr__`로
  같은 문제를 다른 모양으로 갖는다. 어느 쪽으로 수렴할지는 오너 판정(§8-4)이지만, **둘을 유지하는
  것이 가장 비싼 선택**이다.
- **20개 클래스는 세 이름이 세 사실을 가리킨다.** `*Evidence`는 값(`LifecycleTrace`에 `object`로 실림),
  `*Result`는 핸들러 반환, `*Trace`는 루프가 모으는 것. `EventLoop[EventT, TraceT, ResultT]`가 셋 중
  둘의 자리를 타입으로 고정하면 나머지 하나(`Evidence`)는 앞 리뷰 §6대로 `flow/artifacts.py`로
  들어간다.

---

## 6. 확장성 — 이 모양이 왜 scale하는가

오너가 *"나중의 code audit과 scalability"*를 조건으로 걸었다. 위 제안이 그 둘에 답하는 자리를 적는다.

| 축 | 오늘 | 제안 뒤 |
|---|---|---|
| **종목 수** (1,600 → 3,000+) | Arrow는 `PanelWindow`까지, 저자는 tuple·dict·`Decimal` 루프 | `CrossSection`/`Series`가 Arrow-backed면 저자가 columnar로 남을 수 있다. dtype 판정(§8-3) 뒤의 일 |
| **사건원 수** (live, §15-5) | 정적 1 + due 최대 1, 시그니처에 굳음 | `pending() -> Iterable[EventT]`; 큐 정책이 도메인 규칙 |
| **확장점 종류** (다섯째가 온다면) | 계약·Call·로더·phase·게이트 다섯 곳 추가 | `Component[CallT, JudgmentT]` 하나 + Handler 하나 |
| **run당 전략 수** | 이미 N (record 139), 프로세스 단위 병렬 | 불변 |
| **감사(audit)** | "이 값은 어디서 왔나"가 dict 키 추적 | 모양 타입이 provenance를 나른다 — `CrossSection`이 자기 instant를 안다 |

**바꾸지 않는 것.** PIT는 접근 불가능성으로 강제되고(`Call`이 유일한 통로), Account는 single writer이고,
`intended ≠ requested ≠ dealt ≠ committed` 네 단계는 그대로이고, DataModel은 계정을 보지 못하고
(`DataCall`에 `account`가 **없다**), 출하 profile은 `execute`를 오버라이드하지 못하고, run 기록은 끝에
한 번 쓴다(record 164). **이 리뷰의 어느 제안도 이 여섯을 건드리지 않는다.** 척추는 세 번의 독립
감사가 건강하다고 판정한 자리이고(진단 README §0), 이 리뷰는 네 번째다.

---

## 7. 순서 — 무엇이 무엇을 강제 가능하게 만드는가

breaking change가 허용되므로 호환 계층은 만들지 않는다. 순서는 **뒤의 단계를 타입으로 검사 가능하게
만드는 것이 앞에 온다**는 한 기준으로 정했다. 각 단계는 자기 record와 커밋을 갖는다.

| # | 단계 | 건드리는 것 | 왜 이 자리인가 |
|---|---|---|---|
| **0** | 타입 검사기를 게이트에 올린다 (`pyright` 또는 `mypy --strict`, `src/`만) | `pyproject.toml`, `project.yaml`의 `lint` | §5: 이것 없이는 1~4가 문서로 남는다. 오늘 트리에서 몇 개가 나오는지가 **측정**이고, 그 수가 1~4의 진행 지표다 |
| **1** | `Component[CallT, JudgmentT]` base + `Stateful` mixin; `Constraint`가 복사를 버리고 `Component`가 된다 | `authoring.py`, `calls.py`, `extension/loading.py` | 소비자가 저자 표면 하나. `Exchange` 편입은 §8-2 뒤 |
| **2** | `EventLoop`·`Event`·`Handler`: `OccurrenceFlow` 조이기 + phase 이름 + `_dispatch_static`의 role 분기 제거 | `flow/loop.py`, `simulation.py`, `datamodel.py`, phase 넷 | 앞 리뷰 순서 2와 같은 자리. 다른 리뷰 `A`~`D`(아젠다 role)가 여기서 같이 닫힌다 |
| **3** | `domain/shapes.py`: `Grain` 이동, `CrossSection`·`Series`·`Panel` 프로토콜, `Observation` 이동; Call 동사와 `Rebalance`·`ConstraintBounds`·`MarkBatch`가 모양으로 말한다 | `domain/`, `data/panel.py`, `authoring.py`, `portfolio/`, `constraints/`, `exchange/` | 가장 넓다(`Mapping[str, Decimal]` 58곳). 1·2 뒤에 두는 이유: 그때는 소비자가 `Component`·`Handler`로 셀 수 있다. dtype은 바꾸지 않는다 |
| **4** | 검증 체계 수렴 + 내부 `isinstance` 삭제 | 전 패키지 | 0의 측정이 0에 가까워진 뒤. 저자 경계 검사는 남긴다 |
| **5** | 배치: `flow/` kind 디렉터리화, `record/` 승격, `evidence/` 해소, `marking.py` 반환 | 앞 리뷰 §목표 형태 그대로 | 이름이 정해진 뒤 옮겨야 한 번에 옮긴다. `tests/`가 1:1 미러이므로(`tests/flow` 29파일, `from vqapr.flow` 55파일) 가장 늦게 |

**게이트.** 각 단계 뒤 `test_all`(약 6분, record 169)과 0의 타입 검사. 3은 run 조립과 기록 모양을
건드리므로 시나리오 stepper 재생성 대상이다(메모리: *"릴리스마다 실제 트레이스로 다시 만들기"*).

**측정으로 갱신한다.** 진단 README §3의 교훈 — *"표면에 대한 진단은 측정으로 갱신하고 읽기로 갱신하지
않는다"* — 은 여기도 적용된다. 이 리뷰는 읽기다. 1을 시작하기 전에 §5의 표를 스크립트로 만들어
`experiments/`에 두고, 단계마다 다시 잰다. 585가 얼마로 가는지가 이 재설계가 실제로 계약을 타입으로
옮겼는지의 유일한 증거다.

---

## 8. 열린 결정 — 오너 판정이 필요한 것

**8-1. 이름 규칙 — RESOLVED 2026-09-08, 오너 판정.** 아키텍처는 **intent·behavior > pattern·
implementation**이다. 절대적 요구사항은 의도와 행동으로 적고, 현재 구현이 어떤 패턴을 채택했는지와 그
이유를 적되, **그 패턴은 PRD 요구가 바뀌면 유연하게 바뀔 수 있다**고 명시한다. §10의 *"base ·
protocol · service · manager는 패턴이다"*는 아키텍처를 처음 쓸 때 섣불리 패턴을 강제하게 될까 봐 적은
것이지 패턴 이름을 피하라는 뜻이 아니었다. 따라서 `EventLoop`·`Handler`·`Component`는 채택 가능하고,
§10의 그 줄은 위 원칙으로 다시 쓴다. `flow/` → `engine/` 개명은 이 판정에 딸린 작은 결정으로 남는다.

**8-2. Exchange는 Component인가 — RESOLVED 2026-09-08, 오너 판정.** 넷의 공통 개념은 *"이벤트에서
시각을 받아 콜백되는 객체"*이고 Exchange도 그 하나다. Exchange가 다른 점은 한 점을 읽어서가 아니라
(한 점 읽기는 전략도 한다) **주문을 같이 받아 체결해야 한다**는 것이다. `Grain.POINT`는 철회한다 —
grain은 등록한 표의 한 행이 무엇인가이지 읽는 방식이 아니며, "이전까지"(`≤ ts`)와 "정확히"(`= ts`)의
차이는 이벤트 종류가 정한다.

**실행 테이블은 data다. 단, 특별하게 다룬다.** 물리(`trade_at`·instrument·`is_tradable`·후보 가격
필드들)는 dataset 등록이 갖고, **어느 가격을 `trade_price`로 쓸지는 run이 고른다** — 같은 표로 어떤
run은 close, 어떤 run은 open으로 체결한다. 오늘은 `trade_price`가 `FillConvention` 안에 있어 실행
입력 등록의 일부이므로(§17.7) 가격을 바꾸면 다른 `execution_input_id`를 등록해야 한다. 판정에 따르면
그 바인딩은 run 정의로 올라오고 `ExecutionInputRegistration`은 dataset 등록의 실행 역할로 흡수된다.
run이 자기 체결 규약을 들면 `docs/issues/034`(바꾼 결과가 record에 안 남는다)도 그 자리에서 닫힌다.
Model은 이 표를 보통의 PIT 데이터(`available_at ≤ ts`)로만 읽을 수 있고, 정확히-ts 읽기는 due
이벤트를 받는 Exchange와 valuation만 한다 — §10.1의 *"Model이 체결 테이블에 닿지 못한다"*는 그
형태로 유지된다.

**같은 날 같이 닫힌 것.** 8-3은 실측이 닫았다 — 3,000종목에서 cross-section 산술은 콜백당 10 ms
안쪽이고 run 356초 중 몇 퍼센트라 안쪽은 Decimal dict로 두고 타입만 만든다(`scratchpad/bench_xs.py`,
issue 068). 8-4는 오너 판정 — **pydantic 기본**, 검증 없는 운반용 값만 dataclass; 검증 문(디스크·등록·
저자 반환)과 신뢰 문(`model_construct`, 프레임워크가 만든 값)을 값 타입마다 둘 다 둔다. 8-5는 오너
판정 — **Constraint도 기억이 필요할 수 있다**("3회 위반하면 out"), `memory`는 `Component`의 것이고
run state가 컴포넌트마다 memory를 원자적으로 커밋한다.

**8-3. Cross-section의 dtype.** `Decimal` 정확성은 optimizer·account에서 오너 판정이다. `CrossSection`
을 `Mapping[str, Decimal]` 위의 얇은 타입으로 시작할지, Arrow decimal128로 갈지. **이 리뷰의 제안은
전자로 시작**한다 — 모양이 먼저, dtype은 측정 뒤. 3,000 종목에서 dict 루프가 실제로 병목인지는
`docs/issues/049`식으로 재야 한다.

**8-4. 검증 체계.** pydantic frozen(문서·설정)으로 수렴 vs dataclass+validator로 수렴 vs 오늘처럼 둘.
메모리의 `model_copy` 함정과 `object.__setattr__` 62곳이 각각의 비용이다. 이 리뷰는 판정하지 않는다.

**8-5. `Stateful`의 위치.** `memory`를 `Model(Component)` 중간 클래스로 둘지 mixin으로 둘지.
Constraint에 memory가 없어야 한다는 것(*"stateless predicate"*)은 유지되고, 문제는 그것을
상속으로 말할지 조합으로 말할지다. 메모리 *"Strategy instance is stateful — 콜백마다 새 인스턴스
절대 금지"*는 어느 쪽이든 지켜진다.

**8-6. Handler가 Component를 부르는 한 방법.** `Handler.call(component, call)` 한 지점에서 반환
게이트(`isinstance` + 역할별 validate)를 돌릴지, 각 `Component.judge`의 후처리 hook으로 둘지. 전자가
§1 ③의 답이고 §5의 "저자 경계 검사는 남긴다"의 자리다.

---

## 요약

| | 무엇 | 무게 | 다음 |
|---|---|---|---|
| §1 | 네 확장점이 한 패턴을 네 철자로 쓴다; `Component`라는 이름은 등록부에 이미 있다 | **구조** | 순서 1 (`Component[CallT, JudgmentT]`) |
| §2 | 척추는 EventLoop이고 사건·핸들러·결과에 타입이 없다; due 큐 "하나"는 도메인 규칙인데 시그니처에 굳었다 | **구조** | 순서 2; 8-1 판정 |
| §3 | 데이터 모양 다섯 중 타입 있는 것 하나 반; cross-section이 `dict[str, Decimal]` 58곳 | **구조 + 확장성** | 순서 3; 8-3 판정 |
| §5 | `isinstance` 585 · `object.__setattr__` 62 · `-> object` 30 · 검증 체계 둘 · 타입 검사기 없음 | **위생, 측정 지표** | 순서 0·4 |
| §6 | 척추의 여섯 불변식은 건드리지 않는다 | 확인 | — |

§1~§3은 한 덩어리다 — 셋 다 *"선언 → bounded view → 판정"*이라는 패턴에 **이름이 없어서** 각자
자기 철자를 갖게 된 자리다. 이름을 주면 나머지가 따라온다.
