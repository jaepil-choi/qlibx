# 한 모양 캠페인 — 선언은 pydantic 하나, 문은 하나, 규칙은 한 자리

| | |
|---|---|
| **작성 시각** | 2026-09-04 KST (+09:00) |
| **기준 커밋** | `develop @ dd55822b` (= `v0.4.1` + `attempts/` 제거). 이 문서의 수치는 그 커밋에서 직접 잰 것이다 |
| **트리 상태** | 134 모듈(`__init__` 24 포함) / 31,557줄 · ruff clean · fast **1,387 passed** / 22 deselected (`dd55822b`, 2026-09-04) |
| **선행 캠페인** | `docs/refactoring/2026-09-03-the-deletion-campaign.md` — Step 0–7 완료, records `141`–`148`; 그 뒤 `149`·`150` |
| **진단** | 이 문서 §1. 0.4.1 spine stepper(`docs/walkthroughs/2026-09-04-spine-stepper-0.4.1.html`)의 실제 트레이스와 import 그래프로 쟀다 |
| **판정 기준** | `docs/vqapr-prd.md` → `docs/vqapr-architecture.md` §17 → `docs/design/the-panel-the-surface-and-the-run.md` |
| **소유자 결정 (2026-09-04)** | 아래 §0의 여섯. 전부 이 세션에서 소유자가 직접 내렸다 |

> **이 캠페인은 척추를 건드리지 않는다.** `optimize`·`plan_orders`·`Account.prepare_fill`·
> `Fill.__post_init__`·PIT 술어·네 개의 시계는 한 줄도 움직이지 않는다. 움직이는 것은 그 바깥의
> **같은 것의 두 번째 사본**들이다.

---

## 0. 소유자 결정 여섯

| # | 결정 | 근거 |
|---|---|---|
| D1 | **선언되거나 디스크에 남는 것은 전부 pydantic.** 한 행마다 만들어지는 것(`Observation`·`Fill`·`Mark`·주문 행)은 dataclass 그대로 | 삭제 캠페인 D3의 후반. record `145`는 문서만 바꾸고 도메인 dataclass를 남겨 **모든 kind가 두 번 검증**된다 (§1.3) |
| D2 | **중복은 없앤다.** 같은 규칙이 두 자리에 적혀 있으면 한 자리만 남긴다 | §1.3의 표 |
| D3 | **문은 하나.** `Workspace.register_*`(5)와 `Transaction.register_*`(5) 중 후자만 | record `134` 뒤 선언 하나 = 트랜잭션 하나인데 직접 문이 남았다 |
| D4 | **전략 하나 = 파일 하나.** 상수만 달라도 새 파일. 같은 파일의 재등록은 기록에 *tuning*으로 읽힌다 | 이슈 `065` 설계 절반을 이것으로 닫는다. config 채널은 만들지 않는다 |
| D5 | **`flow/materialize.py`는 지운다.** 단, "정말 같은 길인지" 먼저 확인 — 확인됐다 (§1.4) | run의 표를 dataset으로 등록하는 길이 0.4.1에 이미 있다 |
| D6 | **`references/`는 둔다** (1.0.0 전까지 참고). `attempts/`는 `git rm` (이력 유지, `dd55822b`) | "코드가 많다"는 `src/`의 이야기다 |

---

## 1. 진단 — 이 캠페인이 잰 것

### 1.1 트레이스가 지나는 것

0.4.1 stepper 11 scene · 프레임 108 · **소스 파일 36개**. CLI에서 import로 닿는 모듈 106개, 전체 134개.
`flow/`가 9,350줄 / 21파일 = 30%이고 트레이스는 그중 14개를 지난다. 나머지 7개(`views`·`reporting`·
`model_state`·`stamping`·`roster`·`records`·`materialize`)는 호출자 1~2개짜리 조각이다.

`check`(scene ②)와 `run`(scene ③)이 `judgments → preflight_run`을 **따로 걷고 거절 렌더링만 다르다** —
`076`의 세 번째 항목이고 `012`/`015` family의 세 번째 재발이다.

### 1.2 죽은 것과 빈 것

| 파일 | 왜 |
|---|---|
| `models/{model,data_model,strategy_model}.py` | `vqapr.authoring`의 re-export shim 셋 |
| `models/{calls,contexts,memory}.py` + `__init__` | `Model`은 authoring에 있다. 남은 셋은 `call` 객체와 memory 정규화 — 패키지 이름이 거짓말이다 |
| `flow/views.py` | 함수 하나, 테스트 하나만 import |
| `data/stores/__init__.py` | 0바이트 |

### 1.3 같은 것의 두 모양

| 지금 | 뒤 |
|---|---|
| `RunDocument` → `to_domain()` → `RunDefinition`(`flow/run.py`, `_require_*` 7개 + `__post_init__`) | `RunDocument`가 곧 도메인 |
| `DatasetDocument`→`DatasetRegistration`, `ExecutionInputDocument`→`ExecutionInputRegistration`, `ComponentDocument`→`ComponentRef` | 같음. `to_domain`/`from_domain` 8쌍 삭제 |
| `Workspace.register_*` ×5 **와** `Transaction.register_*` ×5 | `Transaction`만 |
| `declarations.py`의 `_require_keys`·`_permitted_values`·`_shape_words`·`_expected_members` | pydantic 이전의 오류 문장 생성기. `ValidationError → Failure` adapter 하나만 |
| 기록 family 일곱: `run.py`(Frozen*)·`records.py`(builder dict)·`run_records.py`(`_*_FIELDS` 손 스키마 + writer + reader + lock)·`run_state.py`·`model_state.py`·`stamping.py`·`reporting.py` | **같은 필드 목록이 세 번 적혀 있다.** record 모델 셋(`RunRecord`·`StrategyRecord`·`DatamodelRecord`)이 그 셋을 대체 → 파일 셋 |
| `Rebalance.of`의 quantise+settle(`authoring.py:647-655`) **와** `weighting.rescale(grid=)` | `of`·`signed` 둘 다 `rescale`을 부른다 (`075`) |
| `cli/check.py::_from_python` **와** `cli/run.py`의 try 밖 `preflight_run` | preflight 거절 렌더 한 곳, 두 verb가 쓴다 (`076`) |
| 순환 4: `authoring↔account.history`, `conventions↔execution_table`, `windows↔store`, `valuation↔callback` | 0 |

### 1.4 `materialize.py`는 정말 같은 길인가 — 확인

| | `publish_run_allocation`/`publish_run_record` | datamodel run |
|---|---|---|
| 입력 | 전략 run의 in-process 결과 | `DataModel.compute()` |
| 출력·등록 | `.vqapr/materialized/`, `DatasetRegistration.of(grain=INSTRUMENT_INSTANT)` → `validate` → `register_dataset` | **같은 세 줄** |

등록 기구는 두 벌이고 use case("한 전략의 출력이 다른 전략의 입력")는 datamodel run이 하지 않는다.
그런데 그 use case는 **세 번째 길**로 이미 된다: record `146` 뒤 run의 표는 parquet이고, 그 디렉터리를
dataset으로 등록하면 읽힌다. 2026-09-04 실험 — `RunRecordWriter`로 `vqapr.weight` 두 세션을 쓰고 그
디렉터리를 등록, `ModelWindow`로 읽음: 등록 통과, `t2+1h`에서 `{'A': 0.25, 'B': 0.75}`, `t1+1h`에서
t2 행이 안 보임(PIT 유지). materialize만 하던 것 셋과 처리:

- 가중치가 숫자였다 → 기록은 Decimal을 텍스트로 저장(`146`)하므로 `fields: {weight: "CAST(weight AS DOUBLE)"}`.
  skill이 이 등록을 보여 준다.
- `vqapr.account`를 `observed_at`으로 날짜 매기고 null이면 `event_time` → 두 시계 다 valuation이 행에 쓰고
  (`valuation.py:260,276`) `148` 뒤 같은 instant다. `available_at: event_time`.
- `lineage.json`(`state_path`) → 읽는 곳이 materialize 자신의 테스트와 showcase뿐. 소스 경로(run id·fp8)와
  `run.json`의 digest가 provenance다.

### 1.5 비용 요인

테스트 151파일 중 **136개(90%)가 내부 모듈을 직접 import**하고 대상이 98개 모듈이다. 모듈을 합치는
비용은 코드가 아니라 테스트다. 각 단계 record에 "순수 rename에 깨진 테스트 수"를 측정값으로 적는다.

---

## 2. 단계

각 단계 = 브랜치 하나 = record 하나(production 변경이 있을 때) = `--no-ff` 병합 하나. `develop`은 항상 green.

| Step | 무엇 | 닫는 이슈 | record |
|---|---|---|---|
| **0** | §1.2 삭제. `models/` → `vqapr/calls.py` + `domain/memory.py`. `065` 판정 문서화 | `065` | 없음 (harness/docs) |
| **1** | `PanelWindow.current()` — `max_available_at`의 행만, 없는 이름은 부재. `latest()` docstring 한 문장 | `072` | `151` |
| **2** | preflight 거절 렌더 한 곳(`__cause__`를 `observed`에), `run`의 `preflight_run`을 try 안으로, `_validate_initial_model_state`가 세 단계 중 어느 것인지 말한다, `save/load_payload` docstring + scaffold 문장 | `076` | `152` |
| **2b** | **답하지 못한 판정은 통과가 아니다.** `judgments.py`의 helper 다섯(`_decide_agenda`·`_judge_execution_ordering`·`_judge_datasets_and_fields`·`_judge_account`·`_instant`)이 dispatcher의 `blocked` wrapper보다 먼저 잡는 `try`를 걷어낸다. `check`가 `passed`/`blocked`/실패 셋을 다시 구별하게 된다. **설계 결정 하나 남음: 중복 보고를 허용하는가**(blocked 한 줄 + preflight 거절 한 줄) | `077` | `153` |
| **3** | `Rebalance.of`가 `rescale(grid=QUANTUM)`을 부른다. `Rebalance.signed(weights, *, gross=1)`. `Budget`·`Rebalance` docstring | `075` | `154` |
| **4** | `flow/materialize.py` 삭제, public에서 이름 넷, `stamping.py`→`datamodel.py`. showcase 005–008을 "member run → 표 등록 → ensemble run"으로. skill에 "run의 표를 등록한다" | — | **`159`** (2026-09-05 완료; `155`–`158`은 캠페인 밖 브랜치가 가져갔다) |
| **5** | **문서가 도메인이다** (D1·D2·D3, ExecPlan). `to_domain` 층·`flow/run.py` 앞 373줄·`Workspace.register_*`·`declarations.py`의 문장 생성기 삭제. `Frozen*`는 frozen pydantic | `027`(문서 메서드 한 줄) | **`160`** (2026-09-07 완료. §1.3의 `declarations.py` 행은 **틀렸다** — 7개 중 6개가 `refusals_from`의 구현이라 남김; `Dataset`/`ExecutionInput` 문서는 codec이라 남김; `Frozen*` pydantic화는 Step 6의 첫 마일스톤으로 연기. record `160` §M5b·M5c·M5d) |
| **6** | **기록 family 7 → 3** (ExecPlan): `flow/frozen.py`·`flow/record.py`(모델 셋 + layout + writer/lock + reader)·`flow/run_state.py`(+`model_state`). `reporting`→`cli/run`. `valuation↔callback` 순환 절단 | — | **`161`** (2026-09-07 완료. `valuation↔callback`은 이미 끊겨 있었다 — 남은 순환 셋을 Step 7에 실측으로 넘김; `Frozen*` pydantic화는 **불필요**로 판정) |
| **7** | 작은 패키지 접기: `domain/` 10→4, `constraints/` 7→3, `valuation/`→`flow/valuation` 옆, `runtime/`→`flow/`. 남은 순환 셋 | — | **`162`** (2026-09-07 완료. 순환 3→0, ratchet 18→13, 모듈 123→111. 실측 정정: `domain/` **5**(`agendas`는 `calls.py`가 읽는 값), `constraints/` **5**(shipped constraint는 파일이라 `builtin/` 둘은 못 합침), `marking`은 `flow/marking.py`로 **옆에**(접으면 `context`를 거쳐 순환), `events`는 `flow/loop.py`로) |

순서의 제약: 2b는 어디에든 놓을 수 있지만 **3 앞**에 둔다 — 재현 픽스처 둘이 `077`을 접수한 세션에서 이미
확인됐고, 판정 계층의 같은 병(`076`의 판정 층 형태)이라 한 흐름으로 읽힌다. 4가 5 앞 — materialize가
`workspace.register_dataset` 직접 문의 마지막 외부 호출자다.
5가 6 앞 — `Frozen*`가 pydantic이 된 뒤에야 record 모델이 그것을 `model_dump`한다. 7은 마지막 —
테스트 churn이 가장 크다.

### 인수조건 (공통)

- fast+slow 전부, showcase 게이트(여덟 + `show_003` 손으로), ruff, vulture, `uv build`.
- Step 5·6: record `104`의 tracer로 sample journey가 같은 함수를 같은 순서로 지난다(척추 불변).
- Step 5: 0.3.0/0.4.1 `workspace.yaml` fixture가 열리고 다시 쓰면 byte-identical.
- 모듈 수·줄 수·순환 수를 record에 측정값으로. **하한을 숫자로 박지 않는다.**

---

## 3. 넣지 않은 것

- **`agent/sample/`** (4파일, 516줄). PRD §11.4가 "fresh user가 materialize할 수 있는 샘플"을 요구하는데
  어떤 CLI도 그것을 노출하지 않고, 소비자는 테스트 여섯뿐이다. wheel에 실린 테스트 픽스처인지 노출 안
  된 제품인지는 **소유자 질문**. 이 캠페인은 두지 않는다.
- **`public`의 이름 21개** (showcase·skill·testbed 어디도 안 쓴다). 삭제해도 모듈은 안 준다. Step 4가
  materialize의 넷을 지우고, 나머지는 "Python에서 run을 부르는 것이 제품인가"에 달렸다 — 열린 질문.
- **`023p`.** HELD.
- **`references/`.** D6.
- **`testing/conformance/`.** `public.conformance`로 노출된 표면이다.
