# `flow/`와 `evidence/`의 구조 리뷰 — 2026-09-08

## 범위와 근거

기준 HEAD `76c827b0`(브랜치 `develop`, working tree에 미커밋 6파일). 수치는 pristine tag가 아니라
**측정 시점 working tree** 기준이다.

이 문서는 오너의 질문 넷에서 나왔다 — *"`flow/`는 뭐 하는 역할이고 왜 이렇게 많지"*,
*"`flow/loop.py` 이건 또 뭐야"*, *"god file을 나누는 건 좋은데 잘게 다 나누는 건 좋은 방법이 아니고,
일반화된 패턴으로 동일한 부분은 동일하게"*, *"`record/`를 두면 `evidence/`는 어떻게 하려고"*.
대화에서 확인한 것만 적는다.

**감사한 것:** 패키지별 LOC, `flow/` 17파일의 docstring/코드 비율(AST), `flow/`와 `evidence/`의 모듈
docstring 전문, `flow/loop.py`·`flow/execution.py`·`flow/datamodel.py`·`flow/marking.py` 본문,
`flow/simulation.py`·`flow/record.py`의 심볼 목록, `flow` / `evidence`의 import 방향과 외부 소비자 전수.

**감사하지 않은 것:** 모든 함수의 의미, 테스트, 실행 분기, 성능. 이 문서는 **배치의 문제**만 다루고
동작의 결함은 다루지 않는다. 아래 어느 항목도 버그가 아니다.

---

## 0. 크기 — 문제로 세기 전에

`src/vqapr` 전체 33,805줄 중 `flow/`가 **9,333줄(27.6%)**로 최대 패키지다. 다만 그중 2,169줄이
docstring·주석이고 **실제 코드는 6,166줄**이다. 이 저장소가 결정의 근거를 코드 옆에 남기는 스타일의
결과이므로 파일 크기를 그대로 복잡도로 읽으면 안 된다.

| 파일 | 총 | docstring+주석 | 코드 |
|---|---|---|---|
| `record.py` | 1,944 | 667 | 1,022 |
| `preflight.py` | 776 | 111 | 601 |
| `callback.py` | 736 | 142 | 549 |
| `orchestration.py` | 727 | 177 | 483 |
| `run_state.py` | 712 | 124 | 515 |
| `datamodel.py` | 669 | 129 | 475 |
| `judgments.py` | 645 | 208 | 366 |
| `run.py` | 602 | 102 | 406 |
| `context.py` | 577 | 136 | 360 |
| `frozen.py` | 484 | 66 | 374 |
| `valuation.py` | 388 | 71 | 288 |
| `execution.py` | 351 | 44 | 290 |
| `simulation.py` | 284 | 31 | 231 |
| `roster.py` | 177 | 91 | 63 |
| `marking.py` | 148 | 40 | 89 |
| `loop.py` | 113 | 30 | 54 |

**record 147의 분할 자체는 문제가 아니다.** `callback.py`/`execution.py`/`valuation.py`는 2,200줄
55메서드짜리 `SimulationFlow`에서 verbatim 이동한 것이고, 각각 응집도가 있다. 아래 지적은 "쪼갠 것"이
아니라 **"어떤 축으로 쪼갰는가"**에 대한 것이다.

---

## 1. `flow/`는 분할 축 두 개가 같은 레벨에 평평하게 놓여 있다

`flow/` 루트에 kind축과 phase축이 섞여 있다.

```
flow/
  datamodel.py      ← kind축   (DataModel 런 전체)
  simulation.py     ← kind축   (Strategy 런의 디스패처)
  callback.py       ← phase축
  execution.py      ← phase축
  valuation.py      ← phase축
  context.py        ← phase가 공유하는 상태
  run_state.py      ← phase가 공유하는 발행
```

`datamodel.py`와 `callback.py`는 같은 층위의 이름이 아니다. 전자는 "런의 한 종류", 후자는 "런의 한
단계"다. 디렉터리는 둘을 형제로 보여준다.

## 2. 척추는 있는데 척추 노릇을 못 한다 — `flow/loop.py`

[`flow/loop.py`](../../src/vqapr/flow/loop.py)의 `OccurrenceFlow`(l.58)는 **이미 일반화된 패턴이다.**
코드 54줄, walk를 한 번만 쓰고, 두 kind가 훅 넷(`_start` / `_pending_due`+`_dispatch_due` /
`_dispatch_static` / `_finish`)만 구현한다. 이 파일은 1번 항목이 말하는 "잘게 나눔"의 사례가 아니라
그 반대다. **문제는 이 척추가 아무것도 강제하지 못한다는 것이다.**

**① 타입을 하나도 나르지 않는다.** `run() -> object`, `_dispatch_static(...) -> object`,
`_finish(traces: tuple[object, ...]) -> object`. 제네릭도 프로토콜도 없다. 결과가 양쪽에 그대로
나온다:

- [`simulation.py:200`](../../src/vqapr/flow/simulation.py) — `SimulationFlow.run()`이 `super().run()`
  뒤에 `assert isinstance(result, SimulationResult)`로 손수 좁힌다. 오버라이드의 절반이 타입 복구다.
- [`datamodel.py:653`](../../src/vqapr/flow/datamodel.py) — `tuple(traces)  # type: ignore[arg-type]`.

**② 하위 계약이 생성자가 아니라 속성 대입이다.** `_static_occurrences`·`_on_progress`·`_start_cutoff`는
클래스 레벨 어노테이션뿐이고 `__init__`이 없다. 서브클래스가 셋 중 하나를 안 채우면 런타임
`AttributeError`다. 그리고 이 저장소는 [`authoring.py:238`](../../src/vqapr/authoring.py)에서
`ABC`+`abstractmethod`를 쓰는데(`DataCall`, `Model`, `StrategyCall`) `OccurrenceFlow`만 평범한 클래스에
`NotImplementedError`다. `DataModelFlow.__init__`이 isinstance 검사를 손으로 다섯 개 하는 것
([`datamodel.py:620`](../../src/vqapr/flow/datamodel.py))이 그 빈자리의 증상이다.

**③ 공유하는 것이 54줄뿐이다.** 척추가 이렇게 얇으면 양쪽이 얼마나 다르게 자랐는지가 보이지 않는다.
아래 3번의 비대칭(475줄 1파일 vs 2,233줄 6파일)이 여태 드러나지 않은 이유가 이것이다. **패턴을
조이는 것이 3번을 보이게 만드는 선행 조건이다.**

**곁가지:** `OperationEnvelope`(l.25)는 `OperationOccurrence` 하나를 감싸 `sort_key()`를 그대로
위임하는 것 말고 하는 일이 없고, 실사용처는 `loop.py:74` 한 줄이다(그 외에는 테스트 하나).
record 162에서 `events.py`를 접으며 딸려온 의례다. `DueExecutionEnvelope`는 `-1` 우선순위라는 진짜
규칙을 담으므로 성격이 다르다.

## 3. 같은 추상의 두 구현이 입도가 다르다 — `strategymodel.py`가 없는 게 아니라 6개로 흩어져 있다

| 구현 | 파일 | 코드 줄 | 한 파일이 담는 것 |
|---|---|---|---|
| `DataModelFlow` | `datamodel.py` **1개** | 475 | Flow + Phase + Output(parquet spill/seal/register) + 출력 계약 검증 |
| `SimulationFlow` | `simulation.py` `callback.py` `execution.py` `valuation.py` `context.py` `run_state.py` **6개** | 2,233 | Flow / 3 phase / 공유 상태 / 상태 발행 |

`OccurrenceFlow`의 이득 — *"strategy run과 datamodel run은 같은 루프"*(record 148) — 이 **파일 배치에서
안 보인다.** 오너 지적 그대로다: 일반화된 패턴이 있으면 동일한 부분은 동일하게 놓여야 한다.

## 4. `flow/marking.py` — 도메인 서비스가 소비자 옆으로 옮겨졌다

`ValuationService`([`flow/marking.py:63`](../../src/vqapr/flow/marking.py))는 보유 포지션마다 마크를
고르는 **규칙**이다. 런의 진행과 무관하고, `FlowContext`도 `FrozenRun`도 보지 않는다.

이 파일은 원래 `valuation/marking.py`였고 one-shape Step 7(record 162)에서 **"소비자 옆으로"**라는
근거로 `flow/`에 들어왔다. 그 근거를 일반화하면 `exchange/`도 `orders/`도 `flow/` 안에 있어야 한다 —
전부 `flow`의 phase가 유일 소비자에 가깝기 때문이다. 즉 **소비자 인접성은 층위 배정의 근거가 될 수
없다.** 이건 record 162의 판단을 되돌리자는 것이지 새 결함의 발견이 아니다.

## 5. `flow/record.py` — persistence 1,944줄이 실행층 안에 있다

역할이 넷이다: Arrow 스키마 추론(`_arrow_type`/`_unified_schema`), 쓰기 + 워크스페이스 락
(`RunRecordWriter`, `LockClaim`, spill/seal), 읽기 질의(`read_table`/`run_ids`/`member_progress`/
`resolve_strategy_ref` 등 20여 개), freeze 헬퍼(`freeze_run_record`/`freeze_strategy_record`/
`freeze_datamodel_record`).

그리고 **`flow/` 밖에서 직접 소비된다** — `report/record.py`, `cli/show.py`, `cli/run.py`,
`cli/list_.py`, `cli/rm.py`, `public.py`. 런을 실행하지 않는 다섯 소비자가 실행층 모듈을 import한다.
`flow/`에서 가장 결합도가 높은 지점이다.

## 6. `evidence/`는 소비자가 다른 세 파일을 이름 하나로 묶고 있다

544줄, `src/vqapr`에서 가장 작은 패키지인데 안에 두 종류가 있다.

| 파일 | 줄 | 정체 | 소비자 |
|---|---|---|---|
| `tables.py` | 59 | `TableSpec` — 사용자가 선언하는 표 | [`authoring.py:38`](../../src/vqapr/authoring.py)이 재수출, `public.py` |
| `recorder.py` | 105 | `InvocationRecorder` — 사용자가 행을 쓰는 통로 | [`authoring.py:37`](../../src/vqapr/authoring.py)이 재수출, `flow/run_state.py`·`flow/valuation.py` |
| `artifacts.py` | 380 | `*Evidence`, `SimulationStage`, `SimulationFailureKind` — 프레임워크 내부 lineage 값 | `flow/` 6파일 (+`public.py`가 `SimulationFailure` 하나) |

앞의 둘은 **저작 계약**(사용자 API 표면)이고 뒤의 하나는 **flow 내부 값**이다. 1번 항목과 같은 종류의
오류다 — 소비자가 다른 것이 이름 하나로 묶여 있다.

**확인한 사실:** `flow/record.py`는 `evidence/`를 **한 곳도 import하지 않는다.** 둘은 파이프라인의
앞뒤가 아니다. 실제 경로는 아래이고, 이음매는 `run_state.py`다.

```text
*Evidence (값)        → LifecycleTrace 안에 object로 실림      (run_state.py)
InvocationRecorder    → run_state.recorder_rows (평평한 row)
                                                    ↓  seam
                                              record.py → parquet
```

Evidence 객체는 디스크에 직접 가지 않는다. row로 납작해진 뒤에 간다. 따라서 `record/`를 신설하고
`evidence/`를 그대로 두면 **같은 이야기를 하는 것처럼 보이는 형제 패키지 둘**이 생기지만 실제로는
의존조차 없는 상태가 된다. 그 배치가 다음 리팩터에서 다시 혼란을 만든다.

## 7. `flow/execution.py`는 층위 위반이 **아니다** — 이름이 오해를 만든다

오너가 *"`exchange`는 밖에 있는데 `flow/execution.py`는 안에 있다"*고 지적했으나, 본문을 보면 자기
로직이 없다: `exact_execution_snapshot` → `plan_orders` → `exchange.execute` →
`Account.prepare_fill` → 커밋 발행. 전부 남의 것을 순서대로 부른다. execution *메커니즘*이 아니라
**due 하나를 처리하는 phase 오케스트레이터**이므로 `flow/`에 있는 것이 맞다. 클래스명도 이미
`ExecutionPhase`다.

문제는 파일명이 `execution.py`라 `exchange/execution_table.py`와 같은 층으로 읽힌다는 것뿐이다.
phase 파일을 하위 디렉터리로 내리면(아래 제안) 자연히 해소된다.

**예외 하나:** 같은 파일의 `bind_registry_to_venue`([`flow/execution.py:313`](../../src/vqapr/flow/execution.py))는
venue 인스턴스에 `object.__setattr__`로 `_registry`/`_rules`를 심는다. docstring이 근거를 길게 적어
두었고(`execute`의 시그니처를 바꿀 수 없다) 그 근거는 타당하지만, 결과적으로 `flow/`가 `exchange/`의
private 필드를 쓴다. 위 항목들과 성격이 다르므로 여기서 결론 내지 않고 기록만 한다.

---

## 제안하는 목표 형태

```text
flow/
  loop.py              OccurrenceFlow — 척추. ABC + Generic으로 조인다 (2번)
  declaration/         run.py  preflight.py  frozen.py  judgments.py
  strategy/            flow.py  callback.py  execute.py  value.py  context.py  state.py
  datamodel/           flow.py  compute.py  output.py
  artifacts.py         ← evidence/artifacts.py
  orchestration.py     run 하나 = 멤버 여럿
  roster.py

record/                ← flow/record.py 승격 (writer / reader / freeze / arrow schema)
portfolio/ 또는 account/  ← flow/marking.py 반환
authoring 계약          ← evidence/tables.py + evidence/recorder.py
```

핵심은 **kind를 디렉터리로 올리고 phase를 그 안으로 넣는 것**이다. `strategy/`와 `datamodel/`이 나란히
서고, 둘 다 `loop.py`의 훅 넷만 구현한다는 사실이 배치로 드러난다. phase 파일이 넷인 것은 strategy가
실제로 4단계이기 때문이라는 정당화가 생기고, `datamodel/`도 같은 규칙으로 3파일이 된다.

`evidence/`는 **유지가 아니라 해소**된다. 이름이 사라지므로 `record/`와 겹칠 일도 없다.

### 이동 안전성

- `OccurrenceFlow`를 조이는 것은 `flow/` 밖에 소비자가 없다(서브클래스 둘 + 테스트 하나). 가장 좁다.
- `TableSpec`·`InvocationRecorder`는 `authoring.py`가 이미 재수출하므로 사용자 import
  (`from vqapr.authoring import TableSpec`)는 **깨지지 않는다.**
- `evidence/artifacts.py`는 소비자가 `flow/` 뿐이고 `public.py`가 `SimulationFailure` 하나를
  재수출한다 — 그 한 줄만 따라간다.
- `flow/marking.py` 반환은 소비자가 `flow/valuation.py`·`flow/execution.py` 둘뿐이다.
- `flow/record.py` → `record/`는 소비자 여섯을 건드린다. 위 넷 중 가장 넓다.

### 순서 (제안, 미확정)

1. `flow/marking.py` 반환 — 소비자 2, 위험 최저
2. `OccurrenceFlow` 조이기(ABC + Generic + 생성자 계약) — 소비자가 `flow/` 안에만 있고,
   **3번을 강제 가능하게 만드는 선행 조건이다**
3. `evidence/` 해소 — 소비자 표면은 재수출이 막아준다
4. `flow/record.py` → `record/` — 소비자 6
5. `strategy/`·`datamodel/` 대칭화 — `public.py`·`cli/`·`report/`까지 import 경로가 번진다

## 열린 결정

- **`OccurrenceFlow`를 어디까지 조일 것인가.** `ABC`+`abstractmethod`까지인지, `Generic[TraceT,
  ResultT]`로 반환 타입까지 나르게 할지, `__init__`으로 세 속성을 계약화할지 — 셋은 독립적으로
  선택 가능하고 이 리뷰는 결론 내지 않았다.
- **`OperationEnvelope`를 남길 것인가.** 지금은 `sort_key()` 위임 전용 래퍼다. 없애면 `run()`의 병합
  비교가 조금 덜 균질해지고, 남기면 실사용 한 줄짜리 타입이 하나 남는다.
- **`tables.py`·`recorder.py`를 어디에 둘 것인가.** `authoring.py`는 지금 1,193줄짜리 단일 모듈이다.
  거기 흡수할지, `authoring/` 패키지로 승격하고 그 밑에 둘지 정해지지 않았다.
- **`marking.py`의 귀착지.** `portfolio/`와 `account/` 중 어느 쪽인지 이 리뷰는 결론 내지 않았다.
- **`bind_registry_to_venue`의 private 접근**(7번). `load_exchange`가 `execute` 오버라이드를
  거부한다는 제약이 있는 한 대안이 자명하지 않다.
- **5번(대칭화)을 할 것인가.** 1~4와 달리 이득이 "읽는 사람에게 패턴이 보인다"는 것 하나이고 비용은
  가장 크다. 오너 판단 사항이다.
