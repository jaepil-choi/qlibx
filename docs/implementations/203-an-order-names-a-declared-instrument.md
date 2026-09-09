# 203 — An order names a declared instrument

| | |
|---|---|
| **작성 시각** | 2026-09-09 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M3 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md` 1e · 3d) |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §6.2 (세 집합이 독립이다) · §6.3 (검사가 두 시점으로 갈린다) |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `202` (run은 `writes`를 선언한다) |

---

## 왜 이 변경이 있는가

`docs/issues/archive/007`의 진단은 *"an undeclared instrument is silently a share"*였다. 008이 사전을
venue에서 프로젝트로 옮겼고, 013이 `charge`와 `stamped_kind`를 한 출처로 묶었다. 그런데 한 가지가
남아 있었다: **roster는 선택이었다.** roster 없는 strategy run은 완료됐고, 모든 fill이 `kind: None`을
찍었고, 성공 envelope의 `roster.known: false`와 note 한 줄이 그 사실을 말했다. 설계 §6.3은 이것을
전제로 뒤집는다:

> **preflight** — 선언이 하나라도 있는가? 0개면 어떤 주문도 성공할 수 없다. 돌 이유가 없다.
> **runtime** — 이 주문의 종목이 선언됐는가? 미등록이면 run 실패. 미등록 종목을 **전부 모아서** 보고.

어느 종목에 주문이 나갈지는 전략이 판단해 봐야 알기 때문에 preflight가 잡을 수 없고, 그래서 검사가
두 시점으로 갈린다. 미등록은 경제적 사실이 아니라 설정 오류이므로 typed zero-dealt로 넘기지 않고
실패한다.

세 집합 사이에 요구되는 포함관계는 둘뿐이다 — **주문 ⊆ 선언, 주문 ⊆ 테이블.** 선언과 테이블 사이에는
아무것도 요구하지 않는다. execution table에 ETF 3,000개가 섞여 있어도 주식 200개만 선언하고 주식 30개만
주문하면 그대로 돈다.

---

## 무엇이 어떻게 바뀌었는가

### 두 개의 문, 두 개의 코드

```
roster.absent          412   preflight (Stage.FREEZE) · check 의 judgment.  strategy run 만.
instrument.undeclared  412   runtime  (Stage.RUN)    simulation.due.instrument_declaration
```

**`roster.absent`** — `flow/declaration/roster.py`의 `require_declared_roster(workspace, run_id=...)`가
`preflight_run`의 strategy 분기에서, venue를 찾은 직후에 묻는다. 읽는 것은 **포인터뿐이다**
(`workspace.registered_instruments()`): 등록이 빈 테이블을 거절하므로 포인터가 있다는 것은 종목이 하나는
있다는 뜻이고, 테이블 자체는 전과 같이 run 시작에 한 번, 신선하게 읽는다. `check`는 같은 사실을
`_judge_roster`로 묻는다 — `run.output_registered`와 같은 두-문 패턴이고, 코드는 preflight 쪽
(`flow/declaration/roster.py`)과 judgments 쪽에 각각 철자되며 테스트가 둘을 한 문자열로 묶는다 (judgments 모듈이
자기 목록을 스스로 공개해야 한다는 `test_check`의 규칙 때문에 import로 대신할 수 없다). datamodel run은
주문하지 않으므로 묻지 않는다.

**`instrument.undeclared`** — `flow/strategy/execution.py`의 `execute_due`가 **주문 계획 전에** 새
단계 `DUE_INSTRUMENT_DECLARATION` 안에서 `require_declared(registry, targets ∪ holdings, exchange_id)`를
부른다 (`domain/instruments.py` — roster와 주문만 있으면 답할 수 있으므로 layer 0). 계획 전인 이유가 설계의 "전부 모아서"다: `plan_orders`는 roster를 통해 비용을 계산하고
(`ExchangeRulesView._declared`), 첫 미등록 종목에서 멈춘다. 그 앞에서 intent의 target과 현재 보유를 훑어
미등록을 **전부** 모아 하나의 `VqaprError`로 올리면, `due_boundary`가 그것을 `SimulationFailure`로 감싸고
envelope의 `failures`에는 그 Failure 하나가 그대로 실린다 — 미등록 종목 이름이 전부 든 채로.
`registry`가 `None`이면(워크스페이스 없이 조립된 run) 모든 종목이 미등록이다. 추측하지 않는다.

보유 종목까지 검사하는 이유: `plan_orders`는 `positions ∪ targets`를 돈다. target에서 빠진 보유 종목은
청산 주문이 될 수 있고, 그것도 주문이다. 정상 경로에서 보유 종목은 살 때 선언돼 있었으므로 이 검사는
roster가 줄어든 경우에만 걸린다 — 그때 거절하는 것이 옳다. venue가 그 매도를 분류할 수 없기 때문이다.

### 한 번에 선언하고 등록하는 문

`register_instruments(project_root, {id: kind}, *, directory=None)`이 `public`에 생겼다. `export_roster`로
kind별 parquet을 쓰고(기본 `<project_root>/instruments/`), `apply({"instruments": {"tables": ...}})`로
`vqapr register instruments.yaml`과 **같은 문**을 지나 등록하며, 영수증(`instruments`, `by_kind`,
`digest`)을 돌려준다. showcase 003·007, 픽스처 여섯 개가 이것을 쓴다. 이전엔 모든 호출자가
`export_roster` + yaml 쓰기 + `register`를 손으로 이어 붙였다.

### sample이 roster를 선언한다

`vqapr new sample`이 `instruments_stock.parquet`을 **materialize 시점에 export하고** `sample.yaml`의
`instruments:` 섹션으로 등록한다. 배포 파일이 아니라 export인 이유: `vqapr new instruments`와 같은
exporter가 쓰므로 둘이 어긋날 수 없다. README 표에 한 줄이 늘었다. 열 개 이름은 전부 합성 주식이다.

### 표면

```
skills   run-declaration.md      "Not required — a run without one completes" → 필수. 두 코드와 두 명령
         execution-profiles.md   "KRX venue without a roster refuses to charge" → 어떤 run도 roster 없이 안 돈다
         result-tables.md        "`kind` is null when no roster was registered" → 이제 없다
sample   instruments_stock.parquet + `instruments:` 섹션
showcase 003 · 007 이 roster 를 등록 (구성 종목 = 주식)
```

`_roster_envelope`의 `known: false` 가지는 남아 있다 — strategy run에서는 이제 도달할 수 없지만, 함수는
`RunResult.roster`를 있는 그대로 렌더링하는 것이 일이고 그 가지를 지우는 것은 M3 밖이다.

---

## 무엇을 잃었나

- **roster 없이 도는 strategy run.** 테스트 픽스처 일곱 곳(`test_preflight._setup`,
  `test_check.workspace`, `test_commands._workspace_for_run`, `test_check_does_not_mutate`,
  `test_check_collects`, `test_valuation_clock`의 RUNNER, `test_time_002._flow`)이 roster를 선언한다.
  `_workspace_for_run(roster=False)`가 "선언 안 한 프로젝트"를 묻는 테스트를 위해 남았다.
- `test_a_run_says_whether_it_knew_what_its_instruments_were`는 반대 명제가 됐다: 성공 경로의 note가
  아니라 `check`·`run` 양쪽의 `roster.absent` 거절, 그 뒤 roster 등록 후 완료.
- `test_run_freezes_its_record`의 *"the sample registers no roster"*는 `by_kind == {"stock": 10}`이 됐다.

---

## 검증

```
uv run python -m pytest tests/ -q -m ""       1619 passed  (신규 11: 단위 8 · journey 2 · 기존 재작성)
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
python -m tests.characterization.refusal_codes 두 코드 추가 (roster.absent · instrument.undeclared)
scripts/showcase_record_digest.py --check      4/81 changed → 원인 확인 후 다시 잡음 → 81/81
```

**digest 4건은 show_007 하나다.** 행·열은 같고 값이 바뀐 곳이 둘: `vqapr.fill`의 `kind` 열이 64행 전부
`None`에서 `stock`이 됐고(roster가 생겼으니), `strategy.json`의 `roster`가 `null`에서 읽은 roster의
digest·`by_kind {"stock": 4}`가 됐다. M3가 identity를 건드리지 않는다는 예측대로 `run_id` 열은 그대로다.
show_003은 record를 남기지 않아 기준선 밖이고, show_001은 시뮬레이션이 없다.

**첫 스위트에서 5건이 떨어졌고 넷은 한 원인이었다** — 층 위반(아래 흔적). 다섯째는 show_001이 roster
없이 strategy run을 돌리던 것으로, 새 규칙이 showcase에서도 그대로 작동했다는 뜻이다.

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **zero-dealt 행은 `kind`가 없다.** 두 번째 세션이 아무것도 바꾸지 않으면 `no_trade` 사유의
  `dealt_quantity: 0` 행이 남고 그 `kind`는 `None`이다 — roster가 그 종목을 선언했어도. 새 journey의
  첫 판본이 "모든 fill 행이 stock"을 단언했다가 여기서 떨어졌다. M3의 문제가 아니라 zero-dealt 경로가
  분류를 찍지 않는 기존 모양이고, 단언은 dealt 행으로 좁혔다. `result-tables.md`가 *"`kind` is never
  null"*이라고 쓰지 않도록 한 이유이기도 하다 — *"every filled id was declared"*라고 쓴다.
- **`flow/roster.py`는 `flow.declaration`·`flow.strategy`보다 위 층이다** (`test_the_layers_hold`:
  `flow` 70, `flow.declaration` 63, `flow.strategy` 65). 게이트 헬퍼를 처음 그 파일에 두었다가 두
  하위 패키지가 위를 import하는 꼴이 됐다. 테스트의 처방대로 값을 아래로 내렸다 — 순수한 절반
  (`undeclared_instruments`·`require_declared`·`instrument.undeclared`)은 `domain/instruments.py`로,
  워크스페이스를 읽는 절반은 새 `flow/declaration/roster.py`로. 같은 스위트가 함수-지역 import 수의
  천장(10)도 지킨다: `register_instruments`의 `export_roster` import를 모듈 상단으로 올렸다.
- **judgment 코드는 judgments 모듈에 문자 그대로 철자돼야 한다.** `test_check`가 정규식으로
  `NAME = "a.b"` 꼴을 모아 `JUDGMENT_CODES`와 대조한다. `flow/declaration/roster.py`의 상수를 import해 쓰면
  "published but not spelled"로 떨어진다. 그래서 두 곳에 철자하고 테스트로 묶었다.

---

## 다음 기록이 이어받을 것

- `Fill.zero_dealt`가 `kind`를 찍지 않는다. 설계 §5.2의 `LedgerEntry` 한 모양(M11)에서 origin·detail을
  정할 때 함께 정한다.
- `_roster_envelope`의 `known: false`·note 가지와 `roster_report(None)`은 strategy run에서 도달
  불가가 됐다. Stage 5 정리 후보.
- Exchange 계약 좁힘(M10, 설계 §6.1)에서 `ExecutionCall`이 종목 사전을 **명시적으로** 받게 되면
  `_bound_rules`의 `registry is None` 가지도 사라진다.
