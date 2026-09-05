# Handoff — 한 모양 캠페인, 2026-09-04 세션 종료 시점 (갱신: Step 2·2b·3 병합)

**받는 사람:** 다음 세션의 에이전트. 이 문서와 저장소만으로 이어서 할 수 있게 썼다. 채팅 이력은 없다.
**계획 문서:** `docs/refactoring/2026-09-04-the-one-shape-campaign.md` (왜·무엇·순서). **살아 있는 상태:**
`.agent/plans/active/one-shape-campaign.md`. **이 파일:** 어디까지 했고 다음 손이 정확히 무엇을 하는가.

---

## 0. 지금 트리 상태

| | |
|---|---|
| `develop` | **`b4bef34b` — Step 0·1·2·2b·3 병합됨.** fast **1,417 passed / 22 deselected**. **2026-09-05 갱신: 그 위에 캠페인 밖 브랜치 넷이 병합됐다** — records `155`(`078`)·`156`(`079`·`083`·`084`·`085`)·`157`(`080`·`081`)·`158`(`086`), 마지막 것은 §0b 참조. 전체 스위트 `test_all` 기준 **1,452 passed** (`157` 병합 시점) |
| 브랜치 | 없음 — **Step 4 완료(record `159`)**, 다음은 `step-05-document-is-the-domain`. `082`의 나머지(dataset이 producer run을 댄다)를 Step 5에 접는다 → 6 → 7 |
| baseline | `dd55822b`에서 fast **1,387 passed / 22 deselected** |
| 모듈 수 | 134 → **127** / 31,557 → 31,461줄 (Step 0 뒤) |
| record 번호 | 다음은 **`155`**. **계획서·§3에 적힌 번호는 무시하고, 브랜치를 딸 때 그 시점의 다음 미사용 번호를 쓴다** — 2026-09-05 판정으로 캠페인 밖 작업 넷이 앞에 끼어들어 계획 번호가 밀렸다 |
| 열린 이슈 | **열하나** — `023`·`027` + 실환경 아홉 `078`~`086` (86파일 / 75닫힘). 아홉은 이 핸드오프가 쓰인 **뒤**에 접수됐다(`4bdfc4cf`) — 색인은 `docs/issues/README.md` §1 |

**첫 행동:** `git checkout develop && git checkout -b step-04-delete-materialize`, 그리고 §3 Step 4.
**Step 4 전에 SLOW 스위트를 한 번 돌린다** — showcase 005–008을 이 단계가 다시 쓴다.

> **§3의 record 번호는 이 갱신 전에 쓰인 것이다.** Step 2·2b·3은 닫혔다(records `152`·`153`·`154`).
> **§3의 record 번호는 전부 무효로 읽는다** — 번호는 브랜치를 딸 때 정한다. 손 위치는 유효하다.

## 0b. 2026-09-05 세션이 남긴 것 — 캠페인 밖 브랜치 넷

전부 `develop`에 `--no-ff`로 병합·푸시됐다. 각 record가 무엇·왜·검증을 든다.

| record | 브랜치 | 닫은 이슈 | 한 줄 |
|---|---|---|---|
| `155` | `fix/078-size-down-and-leave-cash` | `078` | 지불 가능 수량이 **청구하는 채널**(`ExchangeRulesView.charge`)에서 rate를 읽고, 보정은 청구된 값으로 다시 풀고, 못 맞추면 거부 대신 현금을 남긴다. 척추 인접(`orders/planning.py`)이라 캠페인 밖 |
| `156` | `fix/refusals-and-summaries-tell-the-truth` | `079`·`083`·`084`·`085` (+`082`의 `--kind` 절반) | datamodel 거부가 pyarrow 문장+확정 스키마를 인용하고 원인을 단정 안 함(`type_drift`→`schema_mismatch`); `show model`의 구조화 거부와 `list components --kind`; run conflict `fix`가 `rm run-definition`을 대고 같은 문서의 producer run을 거부가 이름으로 댐(`declaration.read.run_fed_by_sibling`); `fill_summary.never_filled` |
| `157` | `fix/080-081-enumerate-then-cascade` | `080`·`081` | datamodel 쪽 `unfinished`/`running` 열거와 `rm datamodel`이 record 없는 디렉터리를 댐; `list runs`의 `orphaned` 행; `rm run-definition`의 `records_remaining`; **`rm run <id> --cascade`** (record → 정의 → materialized 출력 → component, 다른 run이 이름 대는 것은 `kept`+`held_by`) |
| `158` | `fix/086-tolerance-and-three-buckets` | `086` | `StampedConstraintFinding`이 `excess`를 `max(bound×1%, 10bp)`(또는 `Constraint.tolerance`)로 판정해 `held`/`within_tolerance`/`breached`; contract 블록이 셋을 나눠 세고 `ok`는 `breached`만 봄; monitoring 행에 `verdict`·`tolerance`. **constraint·scaffold 코드 변경 0** |

**함정 하나, 기록해 둔다.** `tests/qa/test_run_records_survive_and_race.py::test_five_processes_racing_...`은
문서화된 ~1/12 flake이고, `157`의 전체 스위트에서 한 번 실패했다(1,452 passed / 1 failed). 격리 재실행
5/6, `develop`에서 5/5. **소스를 막 고친 직후에 돌리면 더 자주 실패한다** — 다섯 자식 프로세스가 바뀐
모듈을 동시에 바이트컴파일하느라 창이 넓어진다(3/5 관측). 실패하면 두어 번 다시 돌려 보고, 세 번 연속이면
그때 의심한다.

**Step 4가 남긴 함정 둘 (record `159`).** ① `run(..., store_root=...)`를 준 run은 행을 메모리에
**안 남긴다** — `final_state.recorder_rows`가 비어 있다(sink로 넘기고 root는 보관 안 함). 저장된 run의
표를 읽으려면 record 디렉터리에서 다시 읽는다(showcase의 `_recorded_rows`). ② record는 세션마다 part
하나이고, 그 세션에 값이 없던 컬럼은 `null` 타입으로 써진다 — 여러 part를 읽는 쪽이 스키마를 **union**해야
하고, 패키지의 `scan._relation`이 이제 그렇게 한다(`union_by_name=true`). 직접 duckdb로 읽을 때도 같은
옵션이 필요하다. ③ 모듈을 지운 뒤에는 전체 스위트 전에 `pytest --collect-only`부터 — 1초면 import 누락이 잡힌다.

**남은 실환경 이슈는 `082` 하나** — `--reads` 인덱스와 dataset의 producer `run_id`. 캠페인 Step 5에서 dataset
문서를 다시 쓸 때 접는다. 원래부터 열려 있던 `023`·`027`은 그대로.

## 1. 소유자 결정 (전부 확정 — 다시 묻지 말 것)

### 1b. 2026-09-05 판정 다섯 — 실환경 아홉 중 다섯

이슈 파일의 `**Status:**` 줄이 authority이고, ledger §1의 「2026-09-05 소유자 판정」이 색인이다.
**같은 날 전부 구현됐다** — records `155`–`158`, 아래 §0b. 판정 자체는 그대로 유효하고, 다시 묻지 않는다.

| | 결정 | 메모리 파일 |
|---|---|---|
| `079` | **데이터와 타입은 사용자 책임.** 스키마를 선언하게 하지 않고, precision을 지목하지도 않는다. 구분 못 하는 자리에서는 pyarrow 문장을 그대로 낸다 | `data-and-types-are-the-users-responsibility.md` |
| `086`·`085` | **허용오차는 후하게, 대신 기록을 나눈다.** 기본 `max(bound × 1%, 10bp)` · override 가능 · 판정은 `constraints/evaluation.py` 한 자리(저자 코드 변경 0) · 기록은 `held`/`within_tolerance`/`breached` + 각 worst excess · `ok`는 `breached > 0`일 때만 false | `generous-tolerance-split-the-record.md` |
| `081`·`080` | **삭제는 쉬워야 한다 — cascade를 만든다.** `rm run --cascade`. `080`(열거 완비)이 선행. 부분 실패는 되돌리지 않고 남은 것을 이름으로 보고 | `deletion-must-be-easy.md` |
| `078` | 두 번째 절반: **거부하지 않는다.** 지불 가능 수량이 안 맞으면 한 단위 덜 사고 잔액은 현금. 첫 번째 절반(청구 채널에서 비용 읽기)은 그대로 버그 | 위 `generous-tolerance...`와 같은 뿌리 |

**기각된 안들** (다시 제안하지 말 것): `079`의 선언 스키마와 precision 지목 · `086`의 절대 금액
기본값(vqapr에 통화 개념이 없다 — 돈은 단위 없는 `Decimal`)과 lot 유도(`ConstraintCall`이 최소
권한으로 venue를 못 본다) · `086`의 tolerance를 `ConstraintBounds`에 두는 안(`project`로 새어
feasible set을 넓힌다).

### 1a. 2026-09-04 판정 (캠페인)

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
- **Step 2** (`1fc97286` 병합, record `152`): preflight 거절 문 하나 —
  `cli/run.py::preflight_refusal`이 `__cause__` 사슬을 `observed`에 싣고(4홉 상한),
  `_validate_initial_model_state`가 세 단계 각각의 이름을 대고, `run`이 `preflight_run`을 `try`
  안에서 불러 `check`의 stage·code로 낸다. `076` CLOSED. fast 1,393 passed.
- **Step 2b** (`a15df2f9` 병합, record `153`): 소유자가 요청한 `try`/`except` 전수조사(153지점)가
  낸 `077`. `flow/judgments.py`의 helper 다섯이 dispatcher의 `blocked` wrapper보다 먼저 잡던 것을
  전부 제거 — agenda는 값이 아니라 **호출**(`_agenda_once`), `datasets`는 **멤버당 판정 하나**
  (`datasets[<component-id>]`), `_instant`는 없는 값에만 `None`. `VqaprError`가 이 모듈에서
  import되지 않는다. `077` CLOSED. fast 1,400 passed.
- **Step 3** (`b4bef34b` 병합, record `154`): `Rebalance.signed(weights, *, gross=1)`이 부호 있는
  가중치를 받아 long/short 비율을 **신호가 정한 대로** 둔다(`gross=2`가 교과서 $1/$1). `of`는
  `portfolio.weighting.rescale(grid=QUANTUM)`을 부른다. **잰 차이가 버그였다** — book 전체 settle이
  숏 쪽 잔차를 롱 이름에 얹어서 `invested=1`인 book의 gross가 1.000000000002였다. side별 settle로
  정확해졌고 cash는 9케이스 전부에서 안 바뀌었다. `075` CLOSED. fast 1,417 passed.
- `.agent/project.yaml`의 `active_campaign`이 새 캠페인 문서를 가리킨다.

## 2.5 소유자 결정 D7 (2026-09-04, Step 2b에서)

판정이 답하지 못했고 preflight가 **같은** 결함을 거절할 때, envelope은 **둘 다** 싣는다 —
"이 질문은 던지지 못했다"(blocked 한 줄)와 "이게 잘못됐다"(preflight 거절 한 줄). 서로 다른
진술이기 때문이다. 결함 하나에 항목 둘이 나오는 것이 받아들인 비용이다. helper의 `try` 다섯이
존재한 이유가 정확히 앞쪽을 억제하려는 것이었다.
`tests/cli/test_a_judgment_that_could_not_look_is_not_passed.py`가 양쪽 절반을 고정한다.

## 2.6 전수조사가 남긴 것 — 고치지 않은 셋

`077` 마지막 절에 기록만 해뒀다. 같은 모양이지만 작다.

- `extension/loading.py:198` `accepts_contract_call`이 introspect 실패 시 **`True`**를 돌려준다
  (fail-open). `testing/conformance/runner.py:150`도 같은 경우 `continue`.
- `data/store.py:96` `except TypeError: return grid[0]` — 창을 테이블 전체로 넓힌다. 형제인
  `data/scan.py:1039`는 같은 TypeError에 답을 지어내지 않고 정답 경로로 넘긴다. **CLI 경로로는
  도달 불가**(preflight가 naive `available_at`을 먼저 거절)라 방향만 틀린 방어 코드.
- `agent/sample/build.py:115` `except ValueError: continue` — 거래대금 파싱 실패로 유동성 랭킹이
  아래로 편향된다.

나머지 감사는 깨끗했다: bare `except:` **0건**, `except BaseException` 3건은 전부 cleanup 후
재-raise, `contextlib.suppress` 10건은 전부 cleanup·락 위생이고 각자 이유가 적혀 있다.

## 3. 다음 단계 — 정확한 손 위치

### ~~Step 2 — `076`~~ — **완료**, record `152`. 아래는 당시의 계획으로, 기록으로만 남긴다.

<details>
<summary>Step 2 원 계획 (닫힘)</summary>

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

</details>

### ~~Step 3 — `075`~~ — **완료**, record `154`.

### ~~Step 4 — `flow/materialize.py` 삭제~~ — **완료 2026-09-05, record `159`.** 아래는 당시의 손 위치로, 기록으로만 남긴다. 다음 손은 **Step 5**(§3의 다음 절, record `160`).

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

### Step 5 — 문서가 도메인이다 (ExecPlan 필요, record `160`) ← **다음 손**

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
- 긴 heredoc 하나도 파싱에 실패한다(2026-09-04에 ~120줄 마크다운에서 재발, 파일이 아예 안 생겼다).
  **긴 파일은 `Write`로 쓴다.** `cat > f <<'EOF'`가 조용히 아무것도 안 만들 수 있으니 `ls`로 확인할 것.
- **`git add -A` 금지.** 소유자가 병렬로 편집 중인 파일(2026-09-04에 `README-draft.md`·`docs/vqapr-prd.md`·
  design 문서 하나, 421줄)이 커밋에 딸려 들어갔다. 손댄 파일을 명시해서 add하거나, add 뒤 `git status`로
  확인할 것. 이미 섞였으면 `git reset --soft HEAD~1` → `git restore --staged <남의 파일>` → 재커밋.
- 백그라운드로 띄운 pytest는 **띄운 시점의 트리**를 수집한다. 그 뒤에 테스트를 고치면 그 실행 결과는
  못 쓴다 — 다시 돌린다. 파이프(`| grep`)를 물리면 notification의 exit code는 pytest가 아니라 grep 것이다.
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
- record 번호: 다음은 `155`. 파일명 `NNN-kebab.md`, 같은 커밋에 넣는다. harness/docs-only 변경은 record 없음.
- 캠페인 관례: 단계 = 브랜치 = `--no-ff` 병합. develop은 항상 green.

## 6. 검증 명령

```bash
PYTHONUTF8=1 uv run ruff check src/
PYTHONUTF8=1 uv run pytest tests/ -q -p no:cacheprovider          # fast (~2분 단독)
PYTHONUTF8=1 uv run pytest tests/ -q -m "" -p no:cacheprovider    # +slow, Step 4·5·6·7 전에
PYTHONUTF8=1 uv run vulture
uv build
```
