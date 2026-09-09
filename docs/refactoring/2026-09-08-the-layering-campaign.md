# 레이어링 캠페인 — 순환을 없애고, 레이어를 산문이 아니라 테스트로 만든다

0.8.0의 `src/vqapr`는 126 파일 / 35,401줄이다. 패키지 단위 import 그래프를 AST로 뽑아 보면
**DAG가 아니다.** 이 캠페인이 잰 것과, 그것에 대해 무엇을 어떤 순서로 할 것인가.

오너 지시(2026-09-08): *"위험하더라도 패키지의 구조를 fundamentally simple and robust 하게
만드는 것이 중요해. breaking change더라도 상관 없어."*

---

## 0. 소유자 결정

1. **breaking change 허용.** 0.9.0으로 나간다. 단, 사용자와 agent가 실제로 쓰는 표면
   (`vqapr.public`, `vqapr.authoring`, CLI 전체)은 움직이지 않는다.
2. **국소 정리는 하지 않는다.** 파일 하나 옮기기는 경계를 다시 그으면 덮어써지므로 캠페인
   안에서만 한다.
3. **레이어는 테스트가 지킨다.** 산문으로 적힌 층은 record 124가 이미 한 번 잃었다
   (`docs/issues/archive/028`: 문서 안의 tripwire를 아무도 실행하지 않았다).

---

## 1. 진단 — 이 캠페인이 잰 것

측정: `develop @ 4fdd46fb`, 2026-09-08. 방법은 `src/vqapr` 전 모듈을 `ast`로 걸어
`vqapr.*` import를 패키지 노드로 접은 그래프.

### 1.1 최상위 평면 모듈이 사실상 한 패키지이고, 절반과 순환한다

`authoring.py` · `authoring_records.py` · `authoring_lookback.py` · `calls.py` ·
`declarations.py` · `workspace.py` · `workspace_document.py` · `inputs.py` · `public.py` —
아홉 개가 한 노드(`.`)로 접히면 **fan-in 12 / fan-out 20**, `domain` 다음으로 많이
의존받는다. 22개 노드 중 **11개**와 순환한다.

원인은 고도가 섞여 있기 때문이다. `authoring`(13개 패키지가 import)은 바닥이고,
`public`·`declarations`는 천장인데 같은 디렉터리에 평평하게 놓여 있다.

### 1.2 진짜 순환 셋은 전부 원인이 같다

| 순환 | 간선 | 어떻게 막아뒀나 |
|---|---|---|
| `account ↔ exchange` | `account/account.py:13` → `exchange.fills.Fill`<br>`exchange/venue.py:31` → `account.snapshot.AccountSnapshot` | 안 막았다. 양쪽 top-level |
| `exchange ↔ orders` | `exchange/venue.py:48`·`venues/krx.py:40` → `orders.batches.OrderBatch`<br>`orders/planning.py:11` → `exchange.listings.ExchangeRulesView` | `execution_table.py:534-535` deferred import 2개 |
| `authoring ↔ account` | `authoring.py:37` → `account.history`<br>`account/history.py:33` → `authoring.AccountHistoryInput` | `TYPE_CHECKING` |

셋 다 **동작이 아니라 값이 잘못된 자리에 있어서** 생긴다. `Fill`, `OrderBatch`,
`AccountSnapshot`, `AccountHistory` — 전부 두 패키지가 주고받는 값이다.

### 1.3 `extension ↔ testing`은 deferred조차 아니다

`extension/registration.py:24` → `testing.conformance.conformance`
`testing/conformance/runner.py:47` → `extension.loading`

모듈 단위 import 순서가 우연히 맞아 안 터질 뿐이다. 방향도 뒤집혀 있다 — 적합성 검사는
로더보다 **위**여야 한다.

### 1.4 `flow/` 루트가 자기 자식의 위이자 아래

- 자식 → 루트: `flow/strategy/*`가 `flow.artifacts`·`flow.run_state`·`flow.loop`를 **12번**
- 루트 → 자식: `flow/orchestration.py`·`flow/freeze.py`가 `flow/{strategy,datamodel,declaration}`를 **10번**

한 디렉터리에 substrate와 orchestration이 섞여 있다. 자식이 부모의 공용 값을 읽는 것 자체는
정상이지만, 그 값들이 orchestration과 같은 층에 놓여 있는 것은 아니다.

### 1.5 같은 일을 하는 두 패키지 — **오진, M8에서 철회**

진단은 `analysis/{performance,signal,execution}.py`(363줄)와 `report/measure.py`(835줄)가 둘 다
*"기록된 행을 읽어 값을 낸다"*이므로 한 패키지여야 한다고 적었고, M7이 그 병합이었다.

**틀렸다.** M7을 시작하기 전에 4개 간선을 확인하니 `report/measure.py`가 `analysis/`의 함수를
**쓰고 있었다** — `fill_summary`, `drawdown as running_drawdown`, `returns as period_returns`,
`correlation as pearson_correlation`. 중복이 아니라 **층**이다. `analysis/`는 원시 도구이고
`report/`는 그것으로 문서를 조립한다.

게다가 `analysis/`에는 독립 소비자가 있다: `cli/run.py`가 `fill_summary`를 쓰고, `public.py`가
여섯 함수를 사용자 표면으로 내보낸다. 병합하면 순환도 레이어 위반도 고치지 못한 채
사용자 도구를 프레임워크 문서 생성 패키지 안에 묻고 `vqapr.analysis.*`만 깨진다.

**M7은 취소한다.** 이 캠페인은 측정된 결함만 고친다는 것이 그 근거다.

### 1.6 감지 장치가 없다

`pyproject.toml:55-57`이 import-linter를 거절하며 적은 근거:

> *"a misplaced type surfaces as a circular import, which Python reports without a tool."*

`tests/boundaries/test_a_deferred_import_states_its_reason.py`가 그 문장에 대해 쓴 것:

> *"**That premise is already false where it matters most.** A function-local import defers the
> cycle to the first call, so Python stops reporting it."*

지금 deferred import는 12개이고 `CEILING = 12`, 즉 천장에 붙어 있다. 그중 3개
(`account/history.py:33`, `exchange/execution_table.py:534`, `:535`)가 위 1.2의 순환을
가리고 있다.

### 1.7 죽은 잔재

`.py` 없는 `.pyc` 45개, 그리고 `src/vqapr/evidence/` — `.py` 하나 없이 `__pycache__`만 남은
유령 디렉터리. 전부 git-ignore 대상이므로 작업트리 청소일 뿐이지만, 옛 이름
(`flow/simulation`, `flow/run_spec`, `domain/timestamps`, `workspace_codec`, `venues`,
`materialization` …)이 그대로 보여 탐색을 오염시킨다.

---

## 2. 하나의 규칙

1.2가 셋 다 같은 원인이므로 규칙도 하나다.

> **두 패키지가 주고받는 값은 `domain/`에 산다. 패키지는 동작만 갖는다.**

새 규칙이 아니다. `src/vqapr/domain/values.py`가 이미 *"Portable values every layer shares and
none owns"*라고 선언하고 있고, record 162가 `Mark`/`MarkBatch`를 정확히 그 근거로 옮겼다.
**일관되게 적용되지 않았을 뿐이다.**

---

## 3. 목표 레이어

```
L0  domain/ _internal/                     (vqapr import 0)
L1  data/  portfolio/  transforms/  account/  authoring/
L2  exchange/                              (orders/ 흡수)
L3  extension/  constraints/               (testing/ 흡수)
L4  project/                               (workspace* + declarations)
L5  flow/  record/
L6  report/                                (analysis/ 위에서 조립)
L7  public.py
L8  cli/                                   (agent/ 는 leaf, 손대지 않는다)
```

노드 22 → 18, 평면 모듈 9 → 1(`public.py`), 순환 4 → 0.

(초안은 `analysis/`를 `report/`가 흡수한다고 적었다. M7에서 철회 — §1.5.)

### 3.1 `authoring/`과 `extension/`은 합치지 않는다

합칠 뻔했고 그래프가 막았다.

- `exchange/venue.py:32`가 `authoring.Component`를 상속한다 → **contract는 exchange보다 아래**
- `extension/loading.py`가 Exchange를 로드한다 → **loader는 exchange보다 위**

둘은 필연적으로 다른 층이다. `authoring/` = Component가 **보는 것**(L1),
`extension/` = Component를 **설치하는 것**(L3).

---

## 4. 단계

기록은 **190부터 197**. 단계마다 커밋(AGENTS.md).

| Step | 내용 | 기록 |
|---|---|---|
| 0 | 측정 · 잔재 청소 · 이 문서 | — |
| 1 | 레이어 테스트를 **먼저** 무장 | 190 |
| 2 | 값을 `domain/`으로, `orders/` 소멸 | 191 |
| 3 | `authoring/` 패키지 | 192 |
| 4 | `extension/` 상단 정리, `testing/` 소멸 | 193 |
| 5 | `project/` 패키지 (a·b·c 세 단위) | 194·195·196 |
| 6 | `flow/engine/` | 197 |
| 7 | ~~`analysis/` → `report/`~~ **취소** (§1.5 오진) | — |
| 8 | 래칫 잠금 · 문서 갱신 | 198 |

단계별 상세와 진행 상태는 `.agent/plans/active/layering-campaign.md`에 있다.

### 인수조건 (공통)

각 단계:

```
uv run ruff check src/ && uv run pyright && uv run pytest tests/ -q
```

단계 끝(커밋 전) `uv run pytest tests/ -q -m ""`.
Step 2·5는 추가로 `uv run pytest tests/characterization/test_refusal_codes.py -q`가 필수이며,
**lost가 하나라도 있으면 그 단계는 되돌린다.**

---

## 5. Step 0의 측정 — record 117의 제약은 만료됐다

이 캠페인에서 가장 큰 단일 대상은 `workspace.py`의 `Workspace` 클래스(954줄, 37 메서드)다.
그것을 묶어두던 제약이 살아 있는지가 Step 5의 존폐를 결정하므로, 코드를 옮기기 전에 쟀다.

**제약의 출처.** record 117은 `workspace.py`(당시 2,227줄)의 4분할 계획 중 codec 분할만
취했고, `tests/boundaries/test_the_codec_moved_and_the_refusals_did_not.py`가 그 이유를 못박고
있다 — `Workspace`를 `_workspace_error`에서 떼어낸 시도가 **refusal code 0개 추가 / 37개
삭제**를 측정했다. 초록 스위트와 깨끗한 린트를 통과하면서.

**왜 다시 재는가.** record 171이 `tests/characterization/refusal_codes.py`의 `_SourceIndex`를
바꿨다. 그 docstring이 과거형으로 쓴다:

> *"Those two are merged across modules on purpose. A per-file index only ever resolved a code
> forwarded through a helper defined in the same file, **so splitting a module dropped codes from
> the baseline**."*

즉 37개 소실은 **파일 국소 resolver 시절의 측정치**다.

**측정 (2026-09-08, `develop @ 4fdd46fb`).** `_workspace_error`를 `src/vqapr/_probe_error.py`로
통째로 옮기고 `workspace.py`가 그것을 import하게 한 뒤 — 호출자 25곳은 그대로 두고 —
`tests/characterization/test_refusal_codes.py`를 돌렸다.

```
10 passed in 11.88s
```

**gained 0, lost 0.** `_workspace_error`에 리터럴로 전달되는 코드는 22개이고, 22개 전부가
모듈 경계를 넘은 뒤에도 baseline에 남아 있었다.

**판정.** record 117의 제약은 record 171이 만료시켰다. 인벤토리는 이제 패키지 전역
interprocedural이며 cross-module hop을 따라간다. **Step 5가 열린다.**

`test_the_codec_moved_and_the_refusals_did_not.py`는 Step 5에서 **삭제가 아니라 다시 쓴다** —
옛 결론만 읽고 되돌리는 사람이 없도록, 만료 사실과 이 측정치를 담은 형태로.

---

## 6. 넣지 않은 것

- **`data/scan.py`(1,471줄) 3분할.** 세 덩어리로 깨끗이 갈리고(등록 시점 증명 ~600줄 /
  실행 시점 읽기 ~600줄 / 커넥션·세션 코어 ~300줄) refusal 8개가 전부 리터럴이라 안전하지만,
  **순환과 무관하다.** Step 8에서 판단한다.
- **`portfolio/intents.py` 이동.** `flow/strategy`와 `public`만 쓰므로 순환이 아니다.
  1.2의 규칙은 순환을 죽이려고 적용하는 것이지, 값을 전부 `domain/`으로 쓸어담으려는 것이 아니다.
- **`agent/`.** 출하 자산(skill 9개, sample)이고 leaf다. 손대지 않는다.
- **import-linter 도입.** `pyproject.toml`이 거절한 이유 자체는 바뀌지만
  (*"순환은 Python이 알려준다"*는 이미 거짓), 대체물은 이 저장소의 관행대로
  `tests/boundaries/`의 테스트다. 계약 파일이 타입 배치를 몰아가서는 안 된다는 원래 논거는
  여전히 유효하다.

---

## 7. 끝난 자리 (2026-09-08, `develop @ d1d637b6` 이후)

| | 시작 (`4fdd46fb`) | 끝 |
|---|---|---|
| 패키지 간 순환 | **4** | **0** |
| 최상위 평면 모듈 | **9** | **1** (`public.py`) |
| 그래프 노드 | 22 | 18 (패키지 17 + `public.py`) |
| deferred import | 12 (천장에 붙음) | 10 |
| 레이어 위반 | 11 (`OPEN`에 선언) | **0** |

소멸한 패키지: `orders/`, `testing/`. 새 패키지: `authoring/`, `project/`, `flow/engine/`.

**측정으로 뒤집은 것 하나.** record 117이 `workspace.py`를 통째로 묶어둔 근거(분할 시 refusal
code 37개 소실)는 record 171이 resolver를 패키지 전역으로 바꾸면서 만료됐다. Step 0이 코드를
옮기기 전에 그것을 쟀고(gained 0 / lost 0, 리터럴 코드 22개 전부 유지), M5a가 실제로 쪼갠 뒤에도
같은 결과였다.

**테이블이 아니었으면 못 찾았을 것 하나.** `extension → project`(record 196)는 진단에 없었다.
양쪽 top-level import에 deferred도 아니었고 패키지는 내내 정상적으로 import됐다. M1이
레이어를 **적어두지** 않았다면 이 캠페인은 그것을 지나쳤을 것이다.

**하지 않기로 한 것.**

- **M7 병합** — §1.5의 오진. 위 참조.
- **`data/scan.py`(1,471줄) 3분할** — 세 덩어리로 깨끗이 갈리고 refusal 8개가 전부 리터럴이라
  안전하지만 **순환도 레이어 위반도 아니다.** 이 캠페인은 크기 문제를 레이어 문제와 분리해
  다뤘고(`store.py` 957, `project/registration.py` 1,276도 같은 판정), 마지막에만 예외를 두면
  그 분리가 무의미해진다. 별도 작업의 후보로 남긴다.
- **`flow/declaration/` 개명** — 이제 선언하지 않는 세 모듈(`frozen`·`preflight`·`judgments`)을
  담는다. 이름이 **불완전**하지 그르지는 않다. importer가 많고 검사되는 속성이 없다.
- **`flow/roster.py` 이동** — project 층 읽기가 flow 경로에 있지만 위반하는 레이어가 없다.

**한 것.** `extension/registration.py` → `extension/prepare.py`. 이것은 불완전한 이름이 아니라
**거짓인** 이름이었다 — record 196이 쓰는 절반을 `project/`로 내린 뒤 이 파일은 등록하지 않는다.
