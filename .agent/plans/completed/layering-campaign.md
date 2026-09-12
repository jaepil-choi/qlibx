# Layering campaign: the package import graph is a DAG, and a test says so

Status: complete

## Purpose

`src/vqapr`의 패키지 단위 import 그래프를 **DAG로 만들고, 그 사실을 테스트로 고정한다.**

관측 가능한 결과:

- 패키지 간 순환 4개(`account↔exchange`, `exchange↔orders`, `authoring↔account`,
  `extension↔testing`) → 0
- 최상위 평면 모듈 9개 → 1(`public.py`)
- `tests/boundaries/test_the_layers_hold.py`가 초록이고 위반 상수가 0
- deferred import 12개 → 실측 하한

진단 전문은 `docs/refactoring/2026-09-08-the-layering-campaign.md`.

## Scope and non-goals

**In scope.** `src/vqapr` 전체의 모듈 배치, 그에 따른 `tests/` 갱신,
`tests/boundaries/`의 레이어 테스트 신설, `pyproject.toml`의 근거 문단 갱신.

**Non-goals.**

- `data/scan.py` 3분할 — 순환과 무관. Step 8에서 판단만 한다.
- `agent/`(출하 skill·sample) — leaf, 손대지 않는다.
- import-linter 도입 — 대체물은 `tests/boundaries/`의 테스트다.
- 동작 변경 — 이 캠페인은 배치만 바꾼다. 계산·계약·refusal 어휘는 그대로.
- `portfolio/intents.py` 이동 — 순환이 아니다.

## Acceptance criteria

1. `tests/boundaries/test_the_layers_hold.py`가 위반 0으로 초록.
2. `uv run pytest tests/ -q -m ""` 초록.
3. `uv run pytest tests/characterization/test_refusal_codes.py -q` 초록 —
   **모든 단계에서 lost 0.**
4. `uv run ruff check src/`, `uv run pyright` 무출력/무증가.
5. `vqapr.public` · `vqapr.authoring` · `vqapr.domain.errors` · `vqapr.portfolio.*` ·
   `vqapr.cli.*`의 import 경로 무변 → showcases 9개 코드 수정 0.
6. 기록 190–197이 `docs/implementations/`에 존재.

## Repository context

측정 기준점: `develop @ 4fdd46fb` (0.8.0 stamped). 126 파일 / 35,401줄.

움직이는 것들의 현재 위치:

- 평면 모듈: `src/vqapr/{authoring,authoring_records,authoring_lookback,calls,declarations,
  workspace,workspace_document,inputs}.py`
- 값이 잘못 놓인 곳: `exchange/fills.py`, `orders/batches.py`, `account/snapshot.py`,
  `account/history.py`
- 순환을 가린 deferred: `account/history.py:33`, `exchange/execution_table.py:534-535`
- 고도가 섞인 곳: `flow/{loop,artifacts,run_state}.py` vs `flow/{orchestration,freeze}.py`
- 중복 층: `analysis/` vs `report/measure.py`

지켜야 하는 기존 게이트:

- `tests/characterization/test_refusal_codes.py` — refusal 어휘의 oracle. 재생성은
  `python -m tests.characterization.refusal_codes`이며 **게이트가 스스로 재생성하지 않는다.**
- `tests/boundaries/test_a_deferred_import_states_its_reason.py` — `CEILING` 래칫(M2 이후 10).
  숫자는 내려갈 수 있고 올라갈 수 없다. 내리면 같은 커밋에서 상수를 내린다.
- `tests/boundaries/test_the_facade_is_not_reached_up_to.py` — `vqapr.public`을 import하는
  `src/` 모듈 수.
- `tests/boundaries/test_domain_imports_only_itself.py` — Step 1에서 레이어 표의 한 행으로
  흡수하고 삭제.

## Milestones

- [x] M0: 측정 · 잔재 청소 · 캠페인 문서 + 이 계획 (기록 없음)
- [x] M1: `tests/boundaries/test_the_layers_hold.py` 무장 (record 190)
- [x] M2: 값을 `domain/`으로, `orders/` 소멸 (record 191)
- [x] M3: `authoring/` 패키지 (record 192)
- [x] M4: `extension/` 상단 정리, `testing/` 소멸 (record 193)
- [x] M5: `project/` 패키지 — a·b·c 세 단위 (records 194·195·196)
- [x] M6: `flow/engine/` (record 197)
- [~] M7: **취소** — 오진이었다 (Discoveries D5)
- [x] M8: 래칫 잠금 · 문서 갱신 (record 198)

### M1 — 레이어 테스트를 먼저 무장

L0~L8을 파일 안의 선언 표로 두고 `src/vqapr` 전 모듈을 AST로 걸어 "자기 레이어보다 위를
import하는가"를 검사한다. `xfail`이 아니라 **현재 위반 집합을 상수로 박은 래칫** — 늘 수 없고,
줄면 같은 커밋에서 상수를 내린다(`CEILING` 패턴과 동일).

이동 **전에** 켠다. deferred 상한선이 *"이 리팩토링 자신이 숫자를 올릴 가장 유력한 원인"*이라는
이유로 첫 코드 이동 전에 무장한 것과 같다.

### M2 — 값을 `domain/`으로

| 옮길 값 | 지금 | 죽는 순환 |
|---|---|---|
| `Fill`, `FillBatch`, `ZeroDealtReason` | `exchange/fills.py` | account↔exchange |
| `OrderRequest`, `OrderBatch`, `ZeroDeltaDiagnostic` | `orders/batches.py` | exchange↔orders |
| `AccountSnapshot`, `AccountMark`, `AccountState` | `account/snapshot.py` | account↔exchange, exchange↔orders |
| `AccountHistory`, `retained_marks`, `ACCOUNT_FIELDS`, `INSTRUMENT_FIELDS` | `account/history.py` → `authoring/`(M3에서 자리 잡음) | authoring↔account |

`orders/planning.py`(489줄, 유일한 호출자 `flow/strategy/execution.py:32`) → `exchange/planning.py`,
**`orders/` 소멸.** `exchange/execution_table.py`의 deferred 2개 제거 → `CEILING` 12 → 10.
`account/history.py`의 `TYPE_CHECKING` deferral은 M3에서 죽는다(값을 `domain/`으로 내리는 것이
아니라 `AccountHistory`와 `AccountHistoryInput`을 한 패키지에 두는 것이 답이므로).

### M3 — `authoring/` 패키지

`authoring.py`(1,235줄)가 이미 갖고 있는 구역 주석 세 개를 그대로 선으로 쓴다:
"Shared validation helpers"(L74) / "StrategyModel algebra"(L356) / "Constraint algebra"(L1054).

```
authoring/__init__.py(door) _validation.py component.py data.py decision.py
          strategy.py constraint.py context.py(←calls.py) records.py history.py
```

`vqapr.authoring` 경로 유지(모듈→패키지). `vqapr.calls`는 breaking.

관행을 명시적으로 세운다: **`__init__.py`는 패키지 논거를 싣는다. 재수출은 그 경로가 published
계약이거나(`authoring`) 모듈 배치를 일부러 감출 때만(`record`).**

패키지 불변식은 `authoring.py`의 *"pure algebra, no runtime adapter"*(모듈 불변식)를 대체한다:
**"Component가 보는 것 전부, 그리고 자기 위의 것은 아무것도."**

### M4 — `extension/` 상단 정리

- `testing/conformance/runner.py` → `extension/conformance.py`, **`testing/` 소멸.**
  `public.py:151`이 재수출하므로 사용자 표면 무변.
- `authoring_lookback.py` → `extension/lookback.py` (scaffold 규칙이지 authoring 계약이 아니다).
- `inputs.py` → `domain/inputs.py` (`vqapr.domain.errors` 하나만 import).

### M5 — `project/` 패키지

```
project/__init__.py(door) document.py state.py store.py merge.py references.py
        declaration/{document,refusals,sections,authored}.py
```

`workspace.py`(1,278줄, `Workspace` 954줄/37메서드) + `workspace_document.py`(447) +
`declarations.py`(1,159). `workspace_document.py`는 지금 **두 문서**의 모델을 한 파일에 담고
있다 — `DatasetCodec`(workspace.yaml) vs `DatasetDeclaration`(사용자 선언). 그 선이 분할선이다.

하위 이동마다 refusal baseline **lost 0** 확인.
`tests/boundaries/test_the_codec_moved_and_the_refusals_did_not.py`는 삭제가 아니라
**다시 쓴다**(M0 Discovery를 담아).

### M6 — `flow/engine/`

`flow/{loop,artifacts,run_state}.py` → `flow/engine/`. 루트에는 `orchestration.py` ·
`freeze.py` · `roster.py`만.

### M7 — `analysis/` → `report/`

`analysis/{performance,signal,execution}.py` → `report/`. `public.py`가 둘 다 재수출하므로
사용자 표면 무변.

### M8 — 마감

레이어 테스트 위반 상수 0으로 잠금 · `CEILING` 실측 하향 ·
`pyproject.toml:55-57`의 import-linter 거절 근거를 새 사실로 교체 ·
`docs/vqapr-prd.md`·`docs/design/agent-first-surface.md`의 경로 언급 갱신 ·
`.agent/project.yaml`의 `active_campaign` 갱신 · `data/scan.py` 분할 여부 판단.

## Progress

- **M0 완료** (2026-09-08, `develop @ 4fdd46fb`)
  - 진단 측정 → `docs/refactoring/2026-09-08-the-layering-campaign.md` §1
  - Step 0(a) 측정 완료 → 아래 Discoveries D1
  - stale `.pyc` 45개와 `src/vqapr/evidence/` 유령 디렉터리 삭제 (git-ignore 대상, 커밋 없음)
  - 외부 표면 확인: showcases는 `vqapr.public`(92) · `cli.register`(4) ·
    `portfolio.budgets`(3) · `authoring`(3) · `domain.errors`(2) · `portfolio.optimize`(1)
    뿐이고 **이 캠페인에서 하나도 움직이지 않는다.** testbed는 wheel 핀이라 무관.

- **M1 완료** (record 190, `9ac9dd11`) — `test_the_layers_hold.py` 무장, 위반 11개를 `OPEN`에
  박음. `test_domain_imports_only_itself.py` 흡수·삭제.
- **M2 완료** (record 191) — `costs`·`fills`·`batches`·`snapshot`이 `domain/`으로,
  `planning`이 `exchange/`로, `orders/` 소멸. 순환 2개 사망. `CEILING` 12 -> 10,
  `OPEN` 11 -> 9.

- **M3–M8 완료** (records 192–198). 커밋: `c43abdfd` `cfa68990` `c32846eb` `3b94e6a3`
  `790bfee7` `d1d637b6` `1fde3a47`.

**끝난 자리 (`develop @ 1fde3a47`)**

| | `4fdd46fb` | 끝 |
|---|---|---|
| 패키지 간 순환 | 4 | **0** |
| 최상위 평면 모듈 | 9 | **1** (`public.py`) |
| 그래프 노드 | 22 | 18 |
| 선언된 레이어 위반 (`OPEN`) | 11 | **0** |
| deferred import | 12 | 10 |

`test_all` 1603 passed / 2 failed — 캠페인 전 baseline과 동일. 두 실패는 캠페인 이전부터
있던 `_shipped.json` 릴리스 게이트이며 record 190이 stash 트리로 확인했다.

## Discoveries

**D1 — record 117의 workspace 제약은 record 171이 만료시켰다.** (M0, 결정적)

record 117은 `Workspace`를 `_workspace_error`에서 떼어내면 refusal code 37개가 조용히
사라진다고 측정했고 `test_the_codec_moved_and_the_refusals_did_not.py`가 그것을 못박았다.
그러나 record 171이 `refusal_codes._SourceIndex`를 **패키지 전역 interprocedural**로 바꿨고,
그 docstring이 과거형으로 쓴다 — *"A per-file index ... so splitting a module dropped codes
from the baseline."*

측정: `_workspace_error`를 `src/vqapr/_probe_error.py`로 통째로 옮기고 호출자 25곳은 그대로 둔 뒤
`pytest tests/characterization/test_refusal_codes.py` → **10 passed, gained 0, lost 0.**
`_workspace_error`에 리터럴로 전달되는 코드 **22개 전부**가 모듈 경계를 넘은 뒤에도 baseline에
남아 있었다. 프로브는 되돌렸다(커밋하지 않음).

→ **M5가 열린다.**

**D4 — `extension -> workspace`는 계획에 없던 네 번째 순환이었다.** (M1)

레이어 표가 찾아냈다. `extension/registration.py:113`이 `Workspace.transaction`을 직접 열고,
`declarations.py`는 `extension`을 호출한다 — 즉 등록의 영속화 절반이 자기가 쓰는 대상보다
아래에 있다. M5가 닫는다: `extension/`은 `prepare_component`(검증·지문·적합성)만 갖고,
영속화 wrapper는 `project/`로 올라간다.

**D5 — §1.5는 오진이었고 M7은 취소했다.** (M8)

`analysis/`와 `report/`가 같은 일을 한다고 진단했으나, M7 착수 전 4개 간선을 확인하니
`report/measure.py`가 `analysis/`의 함수를 **쓰고** 있었다 — 중복이 아니라 층이다.
`analysis/`에는 독립 소비자도 있다(`cli/run.py`, `public.py`의 여섯 함수). 병합은 순환도
레이어 위반도 고치지 못한 채 사용자 도구를 묻고 경로만 깨뜨린다. 측정된 결함만 고친다.

**D2 — `authoring/`과 `extension/`은 합칠 수 없다.**

`exchange/venue.py:32`가 `authoring.Component`를 상속하므로 contract는 exchange보다 아래여야
하고, `extension/loading.py`는 Exchange를 로드하므로 exchange보다 위여야 한다. 필연적으로
다른 층이다. 합치려던 초안을 그래프가 막았다.

**D3 — 순환 셋의 원인이 하나다.** `Fill` · `OrderBatch` · `AccountSnapshot` · `AccountHistory`,
전부 두 패키지가 주고받는 값이다. `domain/values.py`가 이미 선언한 규칙
(*"Portable values every layer shares and none owns"*)이 일관되게 적용되지 않았을 뿐이다.

## Decision log

- **2026-09-08 오너** — breaking change 허용, 근본 단순성 우선.
- **2026-09-08 오너** — 국소 정리(파일 하나 이동)는 캠페인 밖에서 하지 않는다. 경계를 다시
  그으면 덮어써진다.
- **M0** — `portfolio/intents.py`는 옮기지 않는다. 순환이 아니다. 규칙은 순환을 죽이려고
  적용하는 것이지 값을 전부 `domain/`으로 쓸어담으려는 것이 아니다.
- **M0** — import-linter는 도입하지 않는다. `pyproject.toml`의 *"계약 파일이 타입 배치를
  몰아가서는 안 된다"*는 논거는 유효하다. 무효가 된 것은 *"순환은 Python이 알려준다"* 쪽이고,
  그 자리는 `tests/boundaries/`의 테스트가 메운다.

## Validation

각 단계:

```
uv run ruff check src/ && uv run pyright && uv run pytest tests/ -q
```

단계 끝(커밋 전): `uv run pytest tests/ -q -m ""`
M2·M5 필수: `uv run pytest tests/characterization/test_refusal_codes.py -q`
캠페인 끝: `uv run vulture`, 그리고 손으로
`uv run python showcases/show_003_real_data_long_short/run.py` (data/DW 필요)

기록된 증거:

- M0 baseline (프로브 전): `10 passed in 22.41s`
- M0 프로브 (cross-module hop): `10 passed in 11.88s`, 코드 22/22 유지

## Risks and recovery

- **refusal code가 사라지는 것** — 초록 스위트·깨끗한 린트를 통과하면서 관측성만 잃는 것이
  record 117이 잡은 실패 모드다. lost가 하나라도 있으면 그 단계를 되돌린다.
- **새 순환** — 가장 싼 잘못된 해법은 function-local import다. `CEILING` 래칫이 막는다.
  올바른 해법은 값을 `domain/`으로 내리는 것.
- **되돌리기** — 단계마다 커밋하므로 어느 단계든 단독 revert 가능. **push는 하지 않는다.**
- **D1이 뒤집히는 경우** — M5만 취소하고 `workspace.py`는 그대로 둔다. M1–M4·M6–M8은 영향
  없으므로 캠페인은 계속된다. 그 사실을 record 194 자리에 "왜 안 했는가"로 남긴다.

## Next action

**없음 — 캠페인 완료.** 인수조건 6개 전부 충족(§Acceptance criteria).

이 캠페인이 명시적으로 남긴 후보, 각각 별도 작업:

1. **`data/scan.py` 3분할**(1,471줄). 세 덩어리로 깨끗이 갈리고 refusal 8개가 전부 리터럴이라
   안전하지만 순환도 레이어 위반도 아니다. record 198 §Trade-offs에 측정치가 있다.
2. **`tests/agent/test_the_release_records_what_it_ships.py` 2개 실패.** 캠페인 이전부터 있던
   것으로, 릴리스 전용 `_shipped.json` 게이트가 기본 `test` 명령에서 돌고 있다.
   `.agent/project.yaml`은 그것이 릴리스 사이에는 "실패하는 것이 정상"이라고 적는다.
3. **불완전한 이름 둘.** `flow/declaration/`(이제 선언하지 않는 세 모듈),
   `flow/roster.py`(flow 경로의 project 층 읽기). 거짓은 아니고 위반도 없다.
4. **0.9.0 릴리스.** 이 캠페인은 breaking이다 — 깨지는 경로 목록은 record 191–197의
   각 §Trade-offs에 있다.
