# Handoff — 한 모양 캠페인, 2026-09-04 세션 종료 시점

**받는 사람:** 다음 세션의 에이전트. 이 문서와 저장소만으로 이어서 할 수 있게 썼다. 채팅 이력은 없다.
**계획 문서:** `docs/refactoring/2026-09-04-the-one-shape-campaign.md` (왜·무엇·순서). **살아 있는 상태:**
`.agent/plans/active/one-shape-campaign.md`. **이 파일:** 어디까지 했고 다음 손이 정확히 무엇을 하는가.

---

## 0. 지금 트리 상태

| | |
|---|---|
| `develop` | **`aded3145` — Step 0·Step 1 병합됨.** fast **1,388 passed / 22 deselected**. 그 앞은 `dd55822b`(attempts/ 제거), `8138f027`(0.4.1 stepper) |
| 브랜치 | 없음 — 다음은 `step-02-076-one-preflight-door` |
| baseline | `dd55822b`에서 fast **1,387 passed / 22 deselected**. Step 0 브랜치도 1,387 passed |
| 모듈 수 | 134 → **127** / 31,557 → 31,461줄 (Step 0 뒤) |

**첫 행동:** `git checkout develop && git checkout -b step-02-076-one-preflight-door`, 그리고 §3 Step 2.

## 1. 소유자 결정 (2026-09-04, 전부 확정 — 다시 묻지 말 것)

| | 결정 | 메모리 파일 |
|---|---|---|
| A (`065`) | **전략 하나 = 파일 하나.** 상수만 달라도 새 파일. 같은 파일 재등록 = 기록상 tuning. config 채널 없음 (`ComponentDocument.config`는 선언·저장·기록되지만 모델에 안 잇는다 — 그대로 둔다) | `strategy-file-is-the-identity.md` |
| B | **`flow/materialize.py` 삭제.** 단 "정말 같은 길인지" 확인 뒤 — 확인 완료(§3 Step 4에 실험 재현 스크립트) | — |
| C | **`references/` 유지**(1.0.0 전). `attempts/`는 `git rm` 완료(`dd55822b`) | `references-stay-until-1-0.md` |
| D1 | 선언·기록 = pydantic. 행 단위 hot path(`Observation`·`Fill`·`Mark`)는 dataclass | 캠페인 §0 |
| D2·D3 | 중복 0, 문 하나(`Transaction.register_*`만) | 캠페인 §0 |

## 2. 완료된 것

- **Step 0** (`5bc05103`): `models/` 패키지 삭제 → `src/vqapr/calls.py`(contexts+observations), `src/vqapr/domain/memory.py`; shim 셋·`flow/views.py`·`data/stores/` 삭제; `065` 판정을 이슈 파일·ledger·`SKILL.md`(3번 항목 "One strategy is one file")에 기록. record 없음(harness/docs).
- **Step 1** (`f55dc610`, 브랜치): `PanelWindow.current()` (`src/vqapr/data/panel.py`), `latest()` docstring, `authoring.py`의 `read()` docstring 셋, `SKILL.md`, scaffold 둘. record `151`. `072` CLOSED, ledger 72/76.
- `.agent/project.yaml`의 `active_campaign`이 새 캠페인 문서를 가리킨다.

## 3. 다음 단계 — 정확한 손 위치

### Step 2 — `076`: preflight 거절 렌더 한 곳 (record `152`, 브랜치 `step-02-076-one-preflight-door`)

문제: `cli/check.py:214 _from_python`은 `f"{type(error).__name__}: {error}"`만 쓰고 `__cause__`를 버린다.
`cli/run.py:174`는 `preflight_run(workspace, definition)`을 `try` **밖**에서 불러 같은 `ValueError`가
`stage: unhandled`로 나간다. `flow/preflight.py:160 _validate_initial_model_state`는 세 단계(save →
load → save)를 상수 문자열 하나로 감싼다.

할 것:
1. `_from_python`을 `cli/check.py`에서 꺼내 `flow/preflight.py`(또는 `cli/envelope.py`)로 옮기고 이름을
   `preflight_refusal(phase, error, target) -> Failure`로. `observed`에 `__cause__` 체인을 붙인다:
   `"ValueError: strategy initial payload for 'x' cannot be staged <- EOFError in load_payload: Ran out of input"`.
2. `_validate_initial_model_state`: 세 `try` 블록으로 나눠 각 메시지에 단계 이름(`save_payload on a fresh
   instance` / `load_payload of those bytes on a second fresh instance` / `save_payload again`)을 넣는다.
3. `cli/run.py::run`: `preflight_run`을 `try`로 감싸 `(TypeError, ValueError)`를 `VqaprError(stage=...,
   failures=[preflight_refusal("preflight", error, target)])`로 올린다 — `check`와 같은 코드
   `run.check.preflight_refused`. `_refuse_if_judged`가 이미 같은 패턴(`JUDGMENT_STAGE`)이다.
4. `authoring.py:851-855` `save_payload`/`load_payload` docstring 두 문장: "preflight calls `save_payload` on
   a fresh instance, `load_payload` on another with those bytes, and `save_payload` again; bytes must match
   before the first callback. A class with nothing to save yet must accept an empty source." `SKILL.md`에
   같은 문장(`grep -n payload src/vqapr/agent/skill/SKILL.md`로 자리 찾기; scaffold는 payload를 emit하지
   않으므로 건드리지 않는다).
5. 테스트: `tests/cli/`에 `load_payload`가 빈 bytes에서 `EOFError`를 내는 전략 → `check`의 `observed`에
   `EOFError`와 단계 이름, `run`의 envelope이 `stage: run.check`·code `run.check.preflight_refused`
   (`unhandled` 아님). 기존 `tests/flow/test_preflight.py`가 payload 왕복을 이미 본다.
6. `tests/characterization/refusal_codes.py`(refusal-code inventory)가 코드 상수 폴딩을 본다 — `_from_python`을
   옮기면 그 inventory 테스트를 다시 돌려 확인.

### Step 3 — `075`: `Rebalance.of`/`.signed`가 `rescale`을 부른다 (record `153`)

- `src/vqapr/authoring.py:573-720` `Rebalance.of`. 647-690의 quantise+settle 블록이
  `src/vqapr/portfolio/weighting.py:161 rescale(weights, long=, short=, grid=QUANTUM)`의 사본이다.
  **차이 하나:** `of`는 잔차를 book 전체의 최대 |weight|에 settle하고 `rescale`은 **side별**로 settle한다.
  `of`를 `rescale` 위에 다시 쓰면 잔차 위치가 바뀔 수 있다 — 테스트(`tests/qa/test_a_budget_refusal_names_its_numbers.py`,
  `grep -rl "Rebalance.of" tests`)로 출력 비교, 바뀐 것은 record에 적는다. `authoring`이
  `portfolio.weighting`을 import하게 된다(weighting은 `optimize`만 import — 순환 없음).
- `Rebalance.signed(weights: Mapping[str, Decimal|int|float|str], *, gross=1)`: 부호 있는 가중치 →
  `|w|` 합이 `gross`가 되게 정규화 → long/short 비율은 **신호가 정한 대로**(균등 분할 아님) →
  `rescale(w, long=L, short=-S, grid=QUANTUM)` → `cash = 1 - sum` → `Budget(SIGNED, cash (-1, 2), target (-1, 1))`.
  이것이 `075`가 요구한 "market-neutral residual book"이다(`of`는 `invested`를 반으로 쪼개 textbook의
  절반, `018`).
- `Budget` docstring(`portfolio/budgets.py:26`)에 `of`가 만드는 두 budget을 값으로 적는다. `Rebalance`
  docstring(`:574`)에 "weights are validated to the last digit; see `rescale`, `QUANTUM`".
- `public.py`에 `signed`는 classmethod라 export 변경 없음. `SKILL.md`의 `Rebalance.of` 문단 옆에 `signed`
  한 줄.

### Step 4 — `flow/materialize.py` 삭제 (record `154`)

확인된 사실: run의 표는 parquet 디렉터리이고 그대로 dataset으로 등록·읽기가 된다. 재현 스크립트(세션
scratchpad에 있었으므로 여기 옮긴다 — `tests/`에 이 형태의 테스트를 하나 넣어 "run 표를 등록한다"를 고정):

```python
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from vqapr.flow.run_records import RunRecordWriter
from vqapr.public import (DataRequirement, DatasetRegistration, Grain, RowsLookback,
                          ModelWindow, SourceSpec, register_dataset)
from vqapr.workspace import Workspace
from vqapr.data.store import DuckDbObservationStore

store = project / ".vqapr"
w = RunRecordWriter(store, "member", "rev@abcdef12"); w.open()
t1 = datetime(2024, 3, 5, 15, 30, tzinfo=UTC); t2 = t1 + timedelta(days=1)
w.append("vqapr.weight", [{"instrument": "A", "weight": Decimal("0.5"), "event_time": t1}, ...])
w.append("vqapr.weight", [...t2...]); w.release()
tables_dir = store / "runs/member/strategies/rev@abcdef12/tables/vqapr.weight"
reg = DatasetRegistration.of("member_weights", "src", instrument_field="instrument",
    available_at="event_time", key_fields=("event_time", "instrument"),
    fields={"weight": "CAST(weight AS DOUBLE)"},   # 기록은 Decimal을 텍스트로 저장(146): CAST 필요
    grain=Grain.INSTRUMENT_INSTANT)
register_dataset(project, reg, SourceSpec.of("src", tables_dir))   # -> True
req = DataRequirement.of("member_weights", "weight", lookback=RowsLookback(2))   # panel grain = RowsLookback
win = ModelWindow(evaluation_time=t2 + timedelta(hours=1), instruments=("A", "B"),
                  store=DuckDbObservationStore(Workspace.open(project)), allowed_requirements=(req,), consumer_id="ensemble")
win.panel([req], "weight").latest()   # {'A': 0.25, 'B': 0.75}; t1+1h에서는 t2 행이 안 보임 (PIT)
```

할 것:
1. `git rm src/vqapr/flow/materialize.py`; `public.py:84`의 import 블록과 `__all__`에서
   `AllocationPublicationSpec`·`AllocationPublicationResult`·`RunRecordSpec`·`RunRecordResult`·
   `publish_run_allocation`·`publish_run_record` 제거; `tests/boundaries/test_public.py:165`가 `__all__`을
   튜플째 고정한다.
2. `flow/stamping.py`(`derived_available_at`, `LookAheadDetected`) → 남은 유일 호출자 `flow/datamodel.py`로
   접는다. `tests/flow/test_publish_allocation.py`가 `LookAheadDetected`를 import한다 — 그 테스트는 삭제.
3. 삭제: `tests/flow/test_publish_allocation.py`, `tests/flow/test_publish_run_record.py`. 재작성:
   `tests/acceptance/test_enhanced_index.py`, `test_ensemble_netting.py`, `test_signal_measurement.py`,
   `tests/qa/test_run_record_availability_clocks.py`(확인). docstring 언급: `flow/context.py:154`,
   `flow/run_state.py:129`.
4. showcase 005·006·007·008 (`grep -n publish_run showcases/*/run.py`): member run → 그 run의
   `tables/vqapr.weight/`(또는 전략이 선언한 표) 디렉터리를 dataset으로 등록 → ensemble run. 
   `show_006`·`007`의 `publish_run_record(... "vqapr.account", availability_field="observed_at")`는
   `available_at: event_time`으로 등록한다 — 두 시계는 valuation이 행에 쓰고(`flow/valuation.py:260,276`)
   148 뒤 같은 instant다(`:237`). showcase 게이트: `tests/showcases/test_every_showcase_completes.py`.
5. `SKILL.md`에 "Registering a run's table as a dataset" 문단(위 스크립트의 YAML 형태: `source:` 디렉터리,
   `available_at: event_time`, `fields: {weight: "CAST(weight AS DOUBLE)"}`).
6. `tests/characterization/refusal_codes.py` inventory에서 `materialize.*` 코드 제거(재생성).
   `scripts/vulture_whitelist.py` 확인.

### Step 5 — 문서가 도메인이다 (ExecPlan 필요, record `155`)

캠페인 §1.3 표가 계약이다. 손 위치:
- `src/vqapr/workspace_document.py`: `RunDocument.to_domain(:412)`, `DatasetDocument`·`ExecutionInputDocument`·
  `ComponentDocument`의 `to_domain`/`from_domain`. 이 문서 모델들이 도메인 타입이 된다(이름은 도메인 쪽
  이름 `RunDefinition` 등을 남기고 문서 쪽을 지우는 편이 import 변경이 적다 — `grep -rl RunDefinition src tests`
  = 16 테스트 파일).
- `src/vqapr/flow/run.py:37-373`: `_identity`·`_require_*` 7개·`ConstraintSet`·`StrategyConfig`·`StrategyEntry`·
  `DataModelEntry`·`RunDefinition.__post_init__` — pydantic validator로 흡수 후 삭제. `:373-` `Frozen*` 5개는
  frozen pydantic으로.
- `src/vqapr/workspace.py`: `Workspace.register_dataset/…_run`(5) 삭제, `_merge_*`(4)를 `Transaction`으로.
  호출자: `grep -rn "\.register_\(dataset\|execution_input\|component\|run\|instruments\)(" src tests` —
  `declarations.register_dataset/_execution_input`(:105-131)이 `Workspace.create(...).register_*`를 부른다 →
  `transaction()`으로. `flow/datamodel.py:325 workspace.register_dataset` 도 (Step 4 뒤엔 materialize 없음).
- `src/vqapr/declarations.py`: `_require_keys`(:381)·`_permitted_values`(:268)·`_shape_words`(:351)·
  `_expected_members`(:344)·`_keys_present`(:264)·`_model_of`·`_mapping_value_model` — pydantic 이전의 문장
  생성기. 남기는 것: `refusals_from`(:168, `ValidationError → Failure` adapter), `_nearest_hint`, 상대경로,
  `_sole_subclass`(ast), 참조검사, `apply/_apply`.
- 게이트: `tests/cli/test_agent_surface.py`(`fix`·`explain`·`source` 필드), `tests/test_the_document_round_trips.py`
  (0.3.0/0.4.1 `workspace.yaml` byte-identical), 선언 오류 테스트 23파일(`grep -rl "declaration\." tests/cli`).
- `027`은 여기서 닫는다: `register` 성공 envelope에 PIT 필드 한 문장씩 — `DatasetDocument.spoken()` 같은
  메서드(`available_at` 컬럼·timezone), `ExecutionInputDocument.spoken()`(`at`·`selector`·`trade_price`).
  `cli/register.py:73`이 `apply()`의 반환(`dict[str, list[str]]`, id 목록)을 envelope에 넣는다 → 문장 리스트를
  더한다. "One sentence per PIT-bearing field, or nothing" (`027` §What to settle).

### Step 6 — 기록 family 7 → 3 (record `156`)

캠페인 §1.3 표의 마지막 행. `flow/run_records.py`의 `_RUN_FIELDS`(:109)·`_STRATEGY_FIELDS`(:145)·
`_DATAMODEL_FIELDS`(:168)·`RUN_JSON_FIELDS`(:188)와 `flow/records.py`의 lambda builder 셋이 record 모델
셋으로. `_require_known_schema`(:1163) → `model_validate`. `model_state.py` → `run_state.py`;
`reporting.py` → `cli/run.py`. `valuation.py:46`이 `CallbackPhase`를, `callback.py:52`가 `ValuationPhase`를
import하는 순환은 둘 다 `FlowContext`만 보게. 확인 대상: `run_state.prepare/publish_valuation_only`가
148 뒤에도 `valuation.py:194,221`에서 불리는데 실제 도달하는지(record 104 tracer).

### Step 7 — 패키지 접기

캠페인 §2 표 그대로. 마지막에.

## 4. 열린 질문 (소유자에게, 막지는 않음)

- `src/vqapr/agent/sample/`(4파일, 516줄): PRD §11.4가 요구하는 샘플 여정인데 어떤 CLI도 노출하지 않고
  소비자는 테스트 여섯뿐(`tests/boundaries/test_the_facade_is_not_reached_up_to.py`가 "shipped sample"로
  명시). wheel의 픽스처인가, 노출 안 된 제품인가.
- `public.__all__` 57개 중 21개는 showcase·skill·외부 testbed 어디도 안 쓴다(캠페인 §3). Step 4가 여섯을
  지운다. 나머지는 "Python에서 run을 부르는 것이 제품인가"에 달렸다.

## 5. 함정 — 이 세션이 밟은 것

- **bash 한 명령에 heredoc 둘**(python 편집 스크립트 + `cat >>`)은 파싱 실패로 **아무것도 실행되지 않는다.**
  편집 스크립트는 scratchpad 파일로 쓰고(`Write`) 실행; 테스트 추가는 heredoc 하나만.
- 한글은 tool 인자에 **리터럴 UTF-8**로(AGENTS.md 비ASCII 절). `PYTHONUTF8=1` 항상.
- `LF will be replaced by CRLF` 경고는 무해(autocrlf).
- fast 스위트: 혼자 ~106s, 둘을 동시에 띄우면 8-9분. `-p no:cacheprovider`. `| tail`로 파이프하면 끝날 때까지
  출력 파일이 비어 있다 — 백그라운드로 띄우고 notification을 기다린다.
- `ruff check src/`만 게이트. `tests/`에는 pre-existing E501 27개 — 건드리지 말 것.
  `ruff --fix`를 tests/에 돌리면 무관한 파일(`tests/showcases/test_every_showcase_completes.py`)이
  바뀐다 — 되돌릴 것.
- vulture 기준선 2건(`workspace_document.py:600 strategy_configs`, `tests/constraints/test_builtin.py:136`).
- 테스트 151파일 중 136개가 내부 모듈을 import한다. 모듈 이름을 바꾸면 `grep -rl "vqapr\.<old>" src tests`
  → sed → `ruff check --fix src/`(import 정렬·중복 병합)로. F402(loop var가 import를 가린다)는 손으로.
- panel grain은 `RowsLookback`/`CalendarLookback`, `InstantsLookback`은 `grain: rows`에서만 (Step 4 실험에서
  한 번 틀렸다).
- record 번호: 다음은 `152`. 파일명 `NNN-kebab.md`, 같은 커밋에 넣는다. harness/docs-only 변경은 record 없음.
- 캠페인 관례: 단계 = 브랜치 = `--no-ff` 병합. develop은 항상 green.

## 6. 검증 명령

```bash
PYTHONUTF8=1 uv run ruff check src/
PYTHONUTF8=1 uv run pytest tests/ -q -p no:cacheprovider          # fast (~2분 단독)
PYTHONUTF8=1 uv run pytest tests/ -q -m "" -p no:cacheprovider    # +slow, Step 4·5·6·7 전에
PYTHONUTF8=1 uv run vulture
uv build
```
