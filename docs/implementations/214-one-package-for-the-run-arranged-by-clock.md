# 214 — One package for the run, arranged by clock

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M14 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md`) — **Stage 5 완료, 캠페인 완료** |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §3 (두 시계) · §4 (배선표) · §10.1 (패키지 이름과 배치: 아직 안 정한 것) · 캠페인 문서 §7 5c-5d |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `213` (The wiring table is data, and a part is a tool plus a clock) |

---

## 왜 이 변경이 있는가

캠페인 §7은 마지막 단계를 **"기계적 — 이름만"**으로 그었고 §0-6은 *"패키지 이름은 마지막에 정한다.
무엇을 하는지가 끝난 뒤에"*라 했다. M13까지가 무엇을 하는지를 끝냈다: run은 부품 하나(자기 시계를
선언한다)와 도구들(시장 시계에 붙는다)이고, 두 kind의 차이는 **시계가 하나냐 둘이냐**뿐이다
(설계 §3, §4.3). 그런데 `flow/`는 그 차이를 kind로 갈라 두 패키지에 담고 있었다 — `flow/strategy/`
(loop · callback · execution · valuation · compliance · accrual · context)와 `flow/datamodel/`
(loop · compute · output). 같은 걸음(`EventLoop`)을 걷는 루프 둘이 서로 다른 디렉터리에 있어서,
"무엇이 다른가"를 읽으려면 두 파일을 나란히 열어야 했다.

---

## 무엇이 어떻게 바뀌었는가

### `flow/run/` — 한 패키지, 시계로 배열

```text
flow/run/
  loop.py          StrategyEventLoop (시계 둘) · DataModelEventLoop (시계 하나)   ← 둘이 한 파일
  callback.py      전략 시계: StrategyModel.decide
  compute.py       전략 시계: DataModel.compute
  accrual.py       시장 시계 1: 자리 (§7.3)
  execution.py     시장 시계 2: pending intent 체결, 통장 append
  valuation.py     시장 시계 3: 프레임워크가 committed 장부를 mark
  compliance.py    시장 시계 4: 선언된 규칙이 관찰
  context.py       전략 run의 handler들이 공유하는 것 (state · 실패 봉투 · timing)
  output.py        datamodel run이 쓰는 창고 문
```

`git mv`다 — 아홉 모듈 중 여덟은 내용이 import 경로 외에 안 바뀌었다. `loop.py`만 둘을 합쳤다:
옛 `strategy/loop.py`(299줄) + `datamodel/loop.py`(95줄) → 369줄, 모듈 docstring이 "차이는 시계 수"를
한 번 말하고 두 클래스 docstring이 각자 "시계 둘" · "시계 하나"로 시작한다. 옛 `strategy/loop.py`가
record `147` 이후 테스트를 위해 재수출하던 비공개 이름 둘(`_shadows_package_table` ·
`_marks_from_execution_snapshot`)은 뺐다 — 비공개 이름은 정의된 모듈에서 import한다
(`tests/flow/run/test_stale_marks.py`가 `flow.run.valuation`에서).

`flow/engine/`(`EventLoop` · artifacts · run_state)은 그대로다. 두 kind가 **함께 구현하는** 걸음과
두 kind가 **각자 걷는** 시계는 바뀌는 이유가 다르다(아키텍처 §10의 첫 판정 규칙): 걸음은 결정성
계약이 바뀔 때, handler는 배선표가 바뀔 때. `engine/` 60 · `declaration/` 63 · `run/` 65 · `flow` 70.

### 이름 — §10.1을 여기서 정한다

| 후보 | 왜 아닌가 / 왜 이것인가 |
|---|---|
| `flow/strategy/` + `flow/datamodel/` (현행) | kind로 가른다. 설계가 kind를 "같은 것을 두 번 본 것"으로 만든 뒤라 거짓 경계 |
| `flow/clocks/` | 조직 원리를 말하지 내용물을 말하지 않는다. `clocks.execution`은 읽히지 않는다 |
| `flow/engine/`에 전부 | 걸음(결정성)과 handler(배선)는 다른 이유로 바뀐다. 한 디렉터리에 두 altitude — record `197`이 푼 문제의 재발 |
| **`flow/run/`** | **run 하나를 돈다.** `project/run.py`가 선언이고 `cli/run.py`가 명령이면 `flow/run/`은 실행이다 — 같은 명사의 세 층 |

`tests/flow/run/`이 1:1 미러다(옛 `tests/flow/strategy/` 여섯 + `tests/flow/datamodel/` 셋).

### `Role`이 `ComponentKind`를 흡수하는가 — 아니다

ExecPlan이 후보로 적었다. `ComponentKind`는 **등록 가능한 넷**이고 `Role`은 **배선표의 다섯 행**이다.
하나로 합치면 `Role.ACCRUAL`이 `register_*`·`load_*`·scaffold의 kind 자리에 값으로 들어갈 수 있게
된다 — 없는 문을 있는 것처럼 보이게 하는 것(아키텍처 §10 "구현이 하나뿐이고 닫혀 있으면 확장점의
겉모습을 만들지 않는다"의 반대 방향). M13의 `ComponentKind.role`이 둘을 잇는 한 문이고 그것으로
충분하다. Accrual이 문이 되는 날 `ComponentKind.ACCRUAL`이 생기고 두 집합이 같아진다.

### `LAYERS`

`"flow.strategy": 65, "flow.datamodel": 65` → `"flow.run": 65`. `OPEN`은 비어 있었고 비어 있다.

### 산문 속 경로

`account/marking.py` · `data/scan.py` · `domain/model_state.py` · `extension/loading.py` ·
`report/measure.py` · `record/schema.py` · `flow/engine/__init__.py`와 테스트 셋의 docstring이
`flow/strategy/…`·`flow/datamodel/…`을 가리키던 것을 `flow/run/…`으로. `public.py`의 export 이름은
하나도 안 바뀌어 고정 테스트는 그대로 통과한다.

---

## 무엇을 잃었나

- **루프 클래스를 하나로 만들지 않았다.** "차이가 시계 수뿐"은 배선의 사실이지 아직 코드의
  사실이 아니다: `StrategyEventLoop`는 `RunStateRepository`+`FlowContext` 위에, `DataModelEventLoop`는
  `RunOutput` 위에 서 있고, 둘을 한 클래스로 접으려면 datamodel run도 accepted state 루트를 갖거나
  strategy run의 발행이 창고 문을 지나야 한다. 그것은 척추 변경이고 Stage 5는 기계적이라고 §7이
  그었다. 한 파일에 나란히 둔 것이 이 마일스톤의 정직한 끝이다.
- **`callback.py`라는 이름.** `decide.py`가 더 정확하지만 클래스가 `CallbackHandler`이고 stage가
  `SimulationStage.CALLBACK`이며 record의 `timing.callback`이 그 이름을 쓴다. 모듈만 바꾸면 셋이
  어긋난다. 이름 넷을 한 번에 바꾸는 것은 이 캠페인 밖(record 어휘가 움직인다).

---

## 검증

```
uv run python -m pytest tests/ -q -m ""       1660 passed (213s)
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
scripts/showcase_record_digest.py --check      83/83 — 재기록 없이
tests/boundaries/test_the_layers_hold.py       OPEN = {} · flow.run 65
```

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **테스트끼리의 import도 경로다.** `tests/flow/test_runtime_resource_ownership.py`가
  `tests.flow.datamodel.test_a_datamodel_is_a_run`에서 픽스처를 빌리고 있었다. `src`의 경로만 바꾸면
  수집 단계에서 죽는다 — 옮길 때 `tests.<옛 경로>`도 grep한다.
- **비공개 이름을 다른 모듈이 재수출하지 않는다.** 재수출은 "테스트가 옛 위치에서 import한다"를
  영구화한다. 옮길 때가 끊을 때다.
- **`ruff format`은 이 저장소의 게이트가 아니다** (45/152 파일이 미포맷). 손으로 접은 줄을
  포맷터로 다시 펴지 않는다.

---

## 캠페인 끝 — 다음이 이어받을 것

- ExecPlan은 `.agent/plans/completed/two-clocks-campaign.md`로.
- **설계 §8이 PRD·아키텍처에 흡수되는 것**은 캠페인 뒤 별도 작업이다. 아키텍처 §3.2·§10의 트리와
  M0가 꽂은 여섯+셋 포인터가 그 작업의 입구다. 지금 아키텍처 §10의 트리는 record `188` 시점이라
  `constraints/`·`flow/loop.py`·`declarations.py`를 아직 그리고 있다.
- 설계 §10.3(`writes`가 하나인가 리스트인가)은 열려 있다. M2가 하나로 갔고 아무것도 그것을
  되물은 적이 없다.
