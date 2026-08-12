# 2026-08-07 12:00 Review findings and six-commit remediation plan

Reviewer: coding agent (Claude Opus 5)
Scope: `src/qlibx` 전체 (11,120 LOC) + `pyproject.toml` + 번들 sample
Reviewed commit: `d805b0c` (`feat: add safe onboarding lifecycle`)
Branch: `exp/2nd-attempt`
Baseline: 142 passed (`.venv/Scripts/python.exe -m pytest tests -q`)
Canonical documents: `docs/qlibx-prd.md`, `docs/qlibx-architecture.md`

> 이 문서는 감사 기록이자 **handoff 문서**다. Canonical contract가 아니며 PRD와 Architecture가 정본이다.
> §2의 finding은 모두 `CONFIRMED` — 코드 경로 추적만이 아니라 실제 실행 또는 파일 확인으로 관측했다.
> §4의 구현 계획은 사용자 승인을 받은 확정 결정이다 (§3 참조).

---

## 0. 후속 agent를 위한 사용법

1. **§1에서 현재 상태를 먼저 확인한다.** M1이 부분적으로 진행된 상태로 handoff되었다.
2. §3의 **확정 결정(locked decision)** 을 읽는다. 이미 사용자 승인을 받았으므로 재논의하지 않는다.
3. §4의 커밋 순서대로 진행한다. 순서에는 §4.0의 근거가 있으며 임의로 바꾸면 안 된다.
4. 각 커밋마다 `docs/implementations/NNN-slug.md`를 새로 만든다 (§5.2). 이 review 문서에는 수정
   내역을 덧붙이지 않는다.
5. 각 커밋 전에 `.venv/Scripts/python.exe -m pytest tests -q`와 `ruff check .`를 통과시킨다.
6. `.agent/plans/active/code-review-remediation.md`의 `Progress` / `Next action`을 갱신한다.
   이 plan 파일은 `.gitignore`로 local working state이므로 commit 대상이 아니다.

### 공통 실행 환경

```powershell
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe -m ruff check .
uv sync --cache-dir .uv-cache
```

전체 suite는 약 2분 소요된다. `tests/acceptance/`는 `data/DW/`와 `data/preprocessed/`의 실제
파일을 DuckDB로 읽어 session-scoped parquet fixture를 만든다 (`tests/acceptance/real_dw_support.py`).

---

## 1. Handoff 시점의 작업 상태

**M1 (C1) 완료 및 commit됨: `df531de chore: require python 3.11 or newer`.
다음 작업은 M2 (C2)부터다.**

M1에서 적용된 변경:

| 파일 | 변경 |
|---|---|
| `pyproject.toml` | `requires-python = ">=3.11,<3.13"`, `target-version = "py311"` |
| `README.md` | 최상단에 `- Requires Python 3.11 or newer (below 3.13).` 추가 |
| `uv.lock` | `uv sync`로 재생성, `requires-python = ">=3.11, <3.13"` |
| `src/qlibx/data/store.py`, `src/qlibx/kernel/clock.py`, test 5개 | `ruff --fix`가 `UP017` 27건 자동 수정 (`timezone.utc` → `datetime.UTC`) |
| `docs/implementations/032-python-311-floor.md` | 신규 |

M1 검증: `pytest tests -q` → **142 passed in 111.25s**, `ruff check .` → **All checks passed!**

**다음 agent의 시작점: §4.1의 C2.**

두 가지 주의:

> 1. `UP017` 자동 수정이 `src/qlibx/data/store.py`와 `src/qlibx/kernel/clock.py`를 건드렸다.
>    이 문서의 `file:line` 인용은 M1 **이전** 기준이므로 몇 줄씩 어긋날 수 있다. 인용된 코드
>    조각으로 `grep`해 위치를 재확인할 것.
> 2. `.agent/tmp/`는 pytest scratch 상태로 untracked이며 `.gitignore`에 없다. `git add -A`를 쓰면
>    딸려 들어가므로 파일을 명시적으로 staging할 것. (별도 정리 대상이며 이 작업 범위 밖이다.)

---

## 2. Diagnostics — 13개 확정 finding

142개 테스트가 전부 통과하는 상태에서 발견되었다. **즉 어느 것도 기존 suite가 잡지 못한다.**

| # | 심각도 | 위치 | 요약 | PRD/Arch 근거 |
|---|---|---|---|---|
| F-01 | high | `data/store.py:90` | session filter가 UTC 날짜 vs profile session timezone 날짜 비교 | §4.4 PIT |
| F-02 | high | `pyproject.toml:9` | `requires-python >=3.10`인데 `StrEnum`은 3.11+ | §1.2 |
| F-03 | high | `data/store.py:59`, `registry.py:153` | naive timestamp를 조용히 UTC로 간주 | §2.6, §4.6 |
| F-04 | high | `data/registry.py:250` | `os.rename`이 POSIX에서 조용히 덮어씀 | §12.2 append-only |
| F-05 | medium | `cli.py:38` | `project sample`에 `--sample-id` 없음 | §2.7 |
| F-06 | medium | `project.py:131` | constraint monitoring facade 미노출 | §11.5, UC-EXEC-003 |
| F-07 | medium | `flow/composition.py:346` | ensemble `run()` 2회 실행 + instance mutation | Arch §2.4 |
| F-08 | medium | `flow/daily.py:1288` | `_on_monitor`가 성과 산술 + mark 없으면 run 중단 | Arch §2.2, PRD §2.4 |
| F-09 | medium | `flow/constraints.py:92,161` | 광범위 `except`가 compute 실패를 data 실패로 오분류 | §2.6, §7.5 |
| F-10 | low | `flow/daily.py:1166` | 빈 holdings mark가 publish 결과 무시하고 먼저 append | — |
| F-11 | low | `simulation.py:38` | `DailySimulationSpec`만 export, 구성 타입은 미export | §1.2 |
| F-12 | low | `flow/daily.py:410` | `DailyExecutionFlow` 1770줄 god class | Arch §2.2, §2.4 |
| F-13 | low | `sample.py:29` | `sample_id` 클래스 속성 shadowing, 중복 튜플 | — |

### F-01 — session filter의 timezone 불일치 (CONFIRMED, 실행 확인)

`ObservationStore.query`는 `observation_time`을 **UTC 달력 날짜**로 필터한다:

```python
# src/qlibx/data/store.py:90
visible = visible.loc[visible["observation_time"].dt.date == session_date]
```

그런데 호출자는 **profile session timezone**으로 `session_date`를 만든다:

```python
# src/qlibx/flow/daily.py:887
session_date = event.ts.astimezone(ZoneInfo(self._profile.session_timezone)).date()
```

**재현 (실행하여 확인함):**

```python
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
KST = ZoneInfo('Asia/Seoul')
s = pd.to_datetime(pd.Series(['2024-01-02T00:00:00+09:00']), utc=True)
print(list(s.dt.date))                                  # [date(2024, 1, 1)]  <- UTC 날짜
print(datetime(2024,1,2,15,30,tzinfo=KST).date())       # date(2024, 1, 2)    <- KST 날짜
```

**판정 기준:** `observation_time`이 `2024-01-02T00:00:00+09:00`(일봉의 매우 흔한 규약: 세션 날짜
자정 KST)인 dataset은 KST session 2024-01-02 조회에서 **행 전체가 사라진다.** 이후 flow는
`EXECUTION_SESSION_PRICE_MISSING`(`daily.py:911`) 또는 `VALUATION_PRICE_MISSING`(`daily.py:1205`)로
실패한다. 데이터는 존재하고 PIT상 available한데도 실패한다.

**왜 142개 테스트가 못 잡는가:** 모든 fixture의 `observation_time`이 00:00 UTC 또는 09:00 KST에
있어서 두 달력의 날짜가 우연히 일치한다. 버그는 **latent**이며 15:00 UTC 이후에만 발현한다.
따라서 수정 시 경계를 넘는 회귀 테스트를 반드시 추가해야 한다 (§4.3).

**session() 호출자 전수 (수정 시 전부 확인):**

| 위치 | session_date 계산 | tz |
|---|---|---|
| `flow/daily.py:888`, `:897` | `event.ts.astimezone(ZoneInfo(profile.session_timezone)).date()` | KST |
| `flow/daily.py:1193` | 동일 | KST |
| `flow/analysis.py:223` | `request.return_session` — **timezone 없는 bare `date`** | 없음 |
| `resources/samples/basic/strategy.py:18` | `view.as_of.date()` — **UTC** (다른 모든 곳과 불일치) | UTC |
| `resources/samples/daily_closed_loop/strategy.py:25` | `view.as_of.astimezone(KST).date()` | KST |
| `tests/acceptance/real_dw_support.py:408`, `:444`, `:467` | 동일 | KST |
| `tests/acceptance/test_historical_strategy_scenarios.py:175` | 동일 | KST |

### F-02 — Python floor (CONFIRMED)

`requires-python = ">=3.10,<3.13"`인데 11개 모듈이 `from enum import StrEnum`(3.11+)을 import한다:
`domain.py:4`, `errors.py:4`, `onboarding.py:7`, `account/account.py:6`, `analysis/results.py:7`,
`config/project.py:4`, `data/contracts.py:3`, `evidence/contracts.py:4`, `flow/composition.py:7`,
`operations/strategy.py:5`, `portfolio/construction.py:5`.

3.10에서 resolution은 성공하고 첫 `import qlibx`가 `ImportError`로 죽는다. 다른 3.11+ 전용 구문
(`datetime.UTC` import, `Self`, `tomllib`, `ExceptionGroup`)은 검색 결과 없음.

### F-03 — naive timestamp의 묵시적 UTC 간주 (CONFIRMED)

```python
# src/qlibx/data/store.py:59-62   (:61은 :59와 완전히 동일한 dead line)
available_at = pd.to_datetime(frame[time_field], errors="raise", utc=True)
if not isinstance(dataset.available_at, AvailableAtField):
    available_at = pd.to_datetime(frame[time_field], errors="raise", utc=True)   # <- 중복
    available_at = available_at + pd.to_timedelta(...)
```

`utc=True`는 naive 값을 **UTC로 간주**한다. KRX 소스가 `2024-01-02 15:30:00`(naive)이면
`2024-01-03 00:30 KST`로 해석되어 PIT cutoff가 9시간 밀린다. `registry.py:153`도 동일
(`errors="coerce"`라서 파싱 불가 값만 잡고 naive는 통과).

PRD §2.6 "경제적 의미를 추측하지 않는다", §4.6 "명시적 실패가 silent fallback보다 우선" 위반.
timezone은 정확히 그런 "경제적 의미"다. 번들 skill도 이를 금지한다:
`resources/skills/qlibx/SKILL.md:26` "Do not infer available_at from DATE alone".

### F-04 — `os.rename`의 플랫폼 의존 (CONFIRMED, 코드 추적)

```python
# src/qlibx/data/registry.py:233-253
if destination.exists():        # TOCTOU
    ...  REGISTRATION_IDENTITY_CONFLICT
...
try:
    os.rename(temporary, destination)
except FileExistsError:          # POSIX에서는 절대 발생하지 않음
    ...
```

Python 문서: "On Unix, if dst exists and is a file, it will be replaced silently."
"On Windows, if dst exists, OSError will be raised." 따라서 Linux/macOS에서 동시 등록 시
기존 registration이 조용히 덮어써지고 `REGISTRATION_IDENTITY_CONFLICT`가 발동하지 않는다.
class docstring이 약속한 append-only 불변식이 개발 플랫폼(Windows)에서만 성립한다.

### F-05 — CLI에서 신규 sample 도달 불가 (CONFIRMED)

`sample.py:30-34`에 3개 sample 등록, `project.py:105`가 `sample_id` 인자를 받지만
`cli.py:38-40`은 `root`와 `--apply`만 정의하고 `cli.py:111`은 `materialize_sample(apply=...)`로
호출한다. 최근 3개 커밋이 추가한 `constraint-workflow-v1`, `daily-closed-loop-v1`은 CLI로 도달
불가. `AGENTS.md`의 testbed 규칙상 agent는 public CLI만 쓸 수 있어 PRD §2.7이 겨냥한 사용자에게
정확히 보이지 않는다.

### F-06 — constraint monitoring facade 미노출 (CONFIRMED)

`flow/monitoring.py`의 `MonitoringFlow`와 `portfolio/constraints.py:311`의
`monitor_actual_single_name_caps`는 구현·테스트 완료. 그러나 `QlibxProject`에 진입점이 없고
`ConstraintMonitoringRequest`도 `qlibx.__all__`에 없다. `grep monitor src/qlibx/project.py
src/qlibx/__init__.py` → 결과 없음.

`adjust` / `validate` / `monitor` 3개 중 앞 2개만 커밋 `6101c71`에서 노출되었다.
PRD §15.3(`prd:1678`)은 "Strategy decision이 없는 clock에도 actual-account monitoring finding을
만든다"를 acceptance criteria로 요구한다. Architecture §8도 3개를 나란히 정의한다
(`qlibx-architecture.md:1099-1107`). `030` 레코드의 Remaining limitations에 명시적 deferral로
기록되어 있으나, 공개 surface가 반쪽인 상태는 유지.

### F-07 — ensemble operation의 순수성 위반 (CONFIRMED)

```python
# src/qlibx/flow/composition.py:344-348
operation = EnsembleStrategyOperation(definition, tuple(members))
operation.run(object())            # 검증 목적 1회차 — dummy view
...
combined = self._research.invoke_strategy(operation, ...)   # :357 내부에서 run() 2회차
...
evidence = operation.evidence(invocation, strategy.artifact.artifact_id)   # :367
```

`run()`이 `self._contributions/_gross_before/_gross_after/_net`를 mutate하고(`:201-204`)
`evidence()`가 그것을 읽는다. 결과적으로:

- netting 계산이 invocation당 2회 실행 (PRD §13.5의 3,000종목 규모에서 낭비)
- `:178-200`의 raise가 `:201`의 할당보다 **먼저** 일어나므로, 실패 후 `evidence()`를 부르면
  조용히 0을 반환
- Architecture §2.4 "③④는 순수하고" 위반. `run()`은 `del view`(`:155`)로 view를 쓰지도 않는다

`StoredSignalStrategyOperation.run`(`:291`)은 이미 순수하다.

### F-08 — `_on_monitor`의 책임 혼재 (CONFIRMED)

`daily.py:1288-1341`이 turnover / transaction cost rate / gross·net return을 flow layer에서
계산한다. Architecture §2.4가 경고하는 "계산이 Flow로 흘러들어온 신호"다. 그리고 monitoring은
계좌 스냅샷만 남기고(`:1396-1424`) `MonitorView`도 compliance 평가도 하지 않아 PRD §11.5의
"PIT-safe compliance data 평가"가 daily flow에 연결되어 있지 않다.

더 나쁜 것은 `:1289-1295`:

```python
mark = next((item for item in reversed(self._marks) if item.event_time == event.ts), None)
if mark is None:
    self._fail(event, "session_performance", "SESSION_MARK_EVIDENCE_MISSING")
    return
```

`_fail`은 `self._errors`를 채우고 `_drain`(`:592-600`)이 run 전체를 중단시킨다. 관찰자여야 할
monitoring이 run을 죽인다 (PRD §2.4: monitoring finding은 authority가 아니다).

### F-09 — 실패 stage 오분류 (CONFIRMED)

```python
# src/qlibx/flow/constraints.py:75-99
try:
    benchmark = self._benchmark(view, declaration)        # data read
    result = adjust_single_name_caps(...)                 # pure compute
except ConstraintEvaluationError as exc: ...
except Exception as exc:
    return self._failure(..., stage_path="constraint.adjust.data",
                         code="CONSTRAINT_DATA_READ_FAILED",
                         retry=("provide complete PIT benchmark and execution-lot inputs",))
```

pure operation 내부의 `TypeError`가 "데이터를 다시 주세요"로 보고된다. agent는 데이터와 무관한
결함에 대해 benchmark를 영원히 재공급하게 된다. PRD §2.6은 "실패한 requirement identity"를,
§7.5는 hierarchical stage contract를 요구한다.

**동일 패턴 3개 사이트:** `flow/constraints.py:92`(adjust), `:161`(validate),
`flow/monitoring.py:63-90`. 추가로 **`flow/analysis.py:222-261`도 동일 결함**이다 — 원 리뷰
13건에는 없었으나 3분의 2만 고치는 것을 피하기 위해 범위에 포함하기로 결정했다 (§3).

### F-10 — 빈 holdings mark의 순서 비대칭 (CONFIRMED)

```python
# src/qlibx/flow/daily.py:1166-1174  (빈 holdings 분기)
self._marks.append(evidence)          # <- 먼저 append
self._publish_model(...)              # <- 반환값 무시

# src/qlibx/flow/daily.py:1285-1286  (정상 분기 — 올바름)
if published is not None:
    self._marks.append(evidence)
```

publish 실패 시 `self._marks`에 미발행 artifact가 남고, `_on_monitor:1289`가 이를 유효한 source로
취급해 `SESSION_SOURCE_ARTIFACT_MISSING`이 엉뚱한 지점에서 발생한다.

### F-11 — public surface 비대칭 (CONFIRMED)

`qlibx/__init__.py:16-34`가 `DailySimulationSpec`을 export하지만 필수 필드 타입
(`KrxExchangeConfig`, `CostRule`, `StockInstrument`, `EtfInstrument`, `Side`)은 export하지 않는다.
번들 sample 자신이 증거다:

```python
# src/qlibx/resources/samples/daily_closed_loop/run.py:19
from qlibx.execution import CostRule, KrxExchangeConfig, Side, StockInstrument
```

PRD §1.2: "정상적인 사용을 위해 agent가 package source나 site-packages private module을 열어야
한다면 public product surface의 결함으로 취급한다."

### F-12 — god class (CONFIRMED)

`DailyExecutionFlow` = `daily.py:410-2184` (1770줄). `_on_execution` = `:845-1153` (310줄, 9개 책임:
sizing, order 생성, matching, shadow account, memory plan, recovery point, commit, 발행, 정리).
Architecture §2.2 "일곱 질문을 섞지 않는다" / §2.4 위반.

구체적 비용: `:920-943`의 order sizing 산술은 순수 로직인데 flow에 갇혀 있어 clock 구동 전체
run 없이는 테스트할 수 없다. **F-01이 142개 green 테스트를 뚫고 살아남은 이유가 바로 이것이다.**

### F-13 — sample.py 정리 (CONFIRMED)

`sample.py:29`가 클래스 속성 `sample_id = default_sample_id`를 두고 `:45`가
`self.sample_id = sample_id`로 가린다. `SampleMaterializer.sample_id`를 클래스에서 읽으면 항상
기본값을 보고한다. `_samples`(`:30-34`)의 값은 전부 `("x","x")` 형태로 source/destination 구분이
정보를 담지 않는다.

---

## 3. 확정 결정 (locked — 재논의 금지)

사용자 승인 완료, 2026-08-07.

| # | 결정 | 근거 |
|---|---|---|
| D1 | **naive timestamp: `source_timezone` 필드 추가.** 무조건 거부도, 경고만도 아님 | fixture churn 최소(등록당 1줄), PRD §1.2 "user가 근거를 확인해 선택" 철학과 일치 |
| D2 | **테마별 6 commit**, 각각 implementation record 032~037 | repo 관행이 "1 commit = 1 record"이고 다중 commit record 사례 없음 |
| D3 | **F-12는 표적 추출만.** 순수 계산 2개만 레이어 밖으로. god class 자체는 분해하지 않음 | 142 테스트 전체를 위험 범위에 넣지 않으면서 원칙(④는 순수) 회복 |
| D4 | **Python floor `>=3.11`** (3.12 아님) | 코드가 실제 요구하는 최소치. 근거 없이 3.11 사용자를 배제하지 않음 |
| D5 | `flow/analysis.py:222-261`의 동일 결함도 F-09와 함께 수정 | 3개 사이트 패턴의 2/3만 조용히 고치는 것을 방지 |
| D6 | `registration_identity` churn 수용 | 0.1.0, 외부 consumer 없음. 대안(None 필드를 identity에서 제외)은 영구적 취약성을 추가 |

---

## 4. 6-commit 구현 계획

| # | Record | Subject | Findings | 선행 |
|---|---|---|---|---|
| C1 | 032 | `chore: require python 3.11 or newer` | F-02 | — |
| C2 | 033 | `fix: reject undeclared timestamp timezone` | F-03, F-04 | C1 |
| C3 | 034 | `fix: filter sessions in the declared session timezone` | F-01 | C2 |
| C4 | 035 | `refactor: extract pure order sizing and session performance` | F-12, F-08 | C3 |
| C5 | 036 | `fix: keep operations pure and classify compute failures` | F-07, F-09, F-10 | C4 |
| C6 | 037 | `feat: expose bundled samples and constraint monitoring` | F-05, F-06, F-11, F-13 | C1 |

### 4.0 순서의 근거 (변경 금지)

- **C1 먼저.** `target-version = "py310"`이면 ruff `UP` 규칙이 3.11 구문을 거부한다. floor를 먼저
  올려야 이후 커밋이 3.10 호환 코드를 썼다가 되돌리는 일이 없다.
- **C2 → C3.** 소스의 timezone이 선언되기 전에는 관측치가 **어느 지역 달력일**에 속하는지 결정할 수
  없다. 두 커밋 모두 `tests/acceptance/real_dw_support.py`를 수정하므로 직렬화해야 diff가 명료하다.
- **C3 → C4.** session date 계산(`daily.py:887-888`)과 sizing 블록(`:904-943`)은 16줄 거리다.
  timezone을 먼저 고쳐야 C4가 **이미 올바른** 코드를 옮긴다.
- **C4 → C5 (실제 정합성 제약).** F-10은 빈 mark 분기를 "발행 성공 후 append"로 바꾸고, F-08은
  `SESSION_MARK_EVIDENCE_MISSING`을 제거한다. C5가 먼저 오면 mark 발행 1회 실패가
  `ARTIFACT_PUBLICATION_FAILED` + `SESSION_MARK_EVIDENCE_MISSING` **2개 오류**를 만든다.
- **C6는 마지막, C1에만 의존.**

### 4.1 C2 — `fix: reject undeclared timestamp timezone`

#### `DatasetRegistration.source_timezone` 설계

`src/qlibx/data/contracts.py`:

```python
source_timezone: str | None = Field(default=None, min_length=1)
```

model validator에서 `ZoneInfo(self.source_timezone)`를 resolve하고 실패 시
`ValueError(f"unknown source_timezone: {...!r}")`. **`str`인 이유:** `registration_identity`가
`model_dump_json()`에서 파생되므로 안정적이고 CLI YAML(`cli.py:115`)에서 사람이 쓸 수 있어야 한다.
`DailyExecutionProfile.session_timezone: str = "Asia/Seoul"`(`daily.py:256`)이 이미 IANA 문자열
관행을 확립했다. `RegisteredDataset`에도 같은 필드를 default `None`으로 추가해 기존 registry JSON이
그대로 로드되게 한다.

**적용 범위:** qlibx가 timestamp로 파싱하는 정확히 두 컬럼 — availability source field
(`available_at.field` 또는 `.source_field`)와 `observation_time_field`. semantic binding 컬럼에는
적용하지 않는다.

**판정 규칙과 error code:**

| 상황 | 결과 |
|---|---|
| 파싱 대상 컬럼이 naive, `source_timezone` 없음 | **FAIL** `TIMESTAMP_TIMEZONE_UNDECLARED`, stage `dataset.register.timestamp_timezone` |
| naive, `source_timezone` 선언됨 | 해당 zone으로 localize(`ambiguous="raise"`, `nonexistent="raise"`) 후 UTC 변환 |
| 이미 offset-aware | UTC 변환. 선언은 이 컬럼에 적용되지 않음 |
| **모든** 파싱 컬럼이 aware인데 `source_timezone` 선언됨 | **FAIL** `TIMESTAMP_TIMEZONE_UNUSED` |
| DST ambiguous/nonexistent, 또는 naive+aware 혼재 | **FAIL** `TIMESTAMP_LOCALIZATION_FAILED` |

"선언했으나 미사용" 규칙이 *"이미 aware면 어떻게 하나"* 에 대한 답이다. 컬럼별 엄격 거부는
정당한 혼합 형태(date-only naive `observation_time` + offset 있는 `available_at`)를 깨뜨린다.
**전체가** 미사용일 때만 거부하면 "죽은 설정 없음 / 묵시적 가정 없음"을 유지하면서 혼합을 허용한다.
이미 aware인 번들 sample `registration.yaml`에 누군가 "친절하게" `source_timezone`을 추가하는 것도
이 규칙이 막는다.

3개 모두 `commit_status=CommitStatus.NONE`, `_publish` 이전 실패. `tests/test_data_registration.py:172`가
검증하는 `LOGICAL_KEY_DUPLICATE` 계약과 동일.

retry preconditions:
- `TIMESTAMP_TIMEZONE_UNDECLARED` → `("declare source_timezone for the naive source, or provide offset-qualified timestamps",)`
- `TIMESTAMP_TIMEZONE_UNUSED` → `("remove source_timezone; the source timestamps already carry an offset",)`
- `TIMESTAMP_LOCALIZATION_FAILED` → `("provide offset-qualified timestamps for the ambiguous or mixed local times",)`

#### 공유 helper

`store.py:59-65,71-75`와 `registry.py:153-169`가 파싱을 중복한다. 둘 다 `data` layer이므로
layer 내 신규 모듈이 규칙상 안전하다 (`test_architecture.py::qlibx_imports`가
`qlibx.data.timestamps`를 `"data"`로 축약하고 `- {layer}`로 제외).

신규 `src/qlibx/data/timestamps.py`:

```python
class TimestampNormalizationError(ValueError):   # .code, .context — PortfolioConstructionError 패턴
def normalize_timestamps(values, *, field, source_timezone) -> NormalizedTimestamps
    # NormalizedTimestamps: utc: pd.Series (UTC, NaT 보존), was_naive: bool
```

알고리즘:
1. `local = pd.to_datetime(values, errors="coerce", utc=False)`. raise하거나 `object` dtype
   (혼합 offset / naive+aware 혼재)이면 `TIMESTAMP_LOCALIZATION_FAILED`, pandas 메시지 500자 절단.
2. `local.dt.tz is None`이면 naive. `source_timezone is None` → `TIMESTAMP_TIMEZONE_UNDECLARED`
   (context: `field`, `naive_rows`, 샘플 값 최대 3개). 아니면
   `local.dt.tz_localize(zone, ambiguous="raise", nonexistent="raise").dt.tz_convert("UTC")`,
   pandas 오류는 `TIMESTAMP_LOCALIZATION_FAILED`로 감싼다. `was_naive=True`.
3. 아니면 `local.dt.tz_convert("UTC")`, `was_naive=False`.

`data/__init__.py.__all__`에 **추가하지 않는다** — 내부 계약이다.

#### 호출부 변경

**`registry.py`** (`register`, :153 부근):
- availability 컬럼과 (있으면) observation 컬럼을 정규화하고 두 `was_naive`를 수집
- 둘 다 성공 후: `registration.source_timezone is not None and not any(was_naive)` →
  `TIMESTAMP_TIMEZONE_UNUSED`
- 기존 `AVAILABLE_AT_INVALID` NaT 카운트 검사는 반환된 UTC series에 대해 유지 (`errors="coerce"`
  동작 보존이므로 해당 테스트 무변경)
- `ConfirmedDelayRule`의 `+ delay_seconds`는 정규화 **이후** 유지 (:165-169). delay는 지역
  벽시계가 아니라 instant에 적용된다
- `TimestampNormalizationError` → `failure(...)`로 `exc.code`, `exc.context` 매핑

**`store.py`**:
- :61의 dead duplicate 삭제
- :59-65, :71-75를 `normalize_timestamps(..., source_timezone=dataset.source_timezone)`로 교체
- `TimestampNormalizationError` → `DataSnapshotError`로 번역 (dataset 이름과 명시적
  `source_timezone` 재등록 안내 포함). :32의 physical fingerprint 검증 때문에 도달 불가해야 하지만
  raw pandas 예외가 새어나가면 안 된다

#### 해싱과 §16.3 영향

**`schema_fingerprint`: 영향 없음.** 정규화 이전의 raw read `frame.dtypes`를 해싱한다
(`registry.py:172-176`). 레코드에 명시할 것.

**`registration_identity`: 전 dataset churn.**
`stable_hash(registration.model_dump_json() + physical_fingerprint + schema_fingerprint)`이므로
`"source_timezone":null` 키가 추가되어 모든 identity가 바뀐다. 결과(심각도 순):

1. **기존 dataset 재등록이 실패한다.** `_publish`(:233-244)가 `destination.exists()` +
   identity 불일치 → `REGISTRATION_IDENTITY_CONFLICT`. 기존 retry precondition 문구가 이미 대응책을
   안내한다. 기존 등록의 **로드**는 정상(`snapshot()`, requirement resolution, `scoped.py:178`의
   staleness 검사 — 한 프로세스 내에서 일관). 재등록만 충돌. PRD §16.3의 "explicit unsupported
   error" 분기이지 silent break가 아니다.
2. **업그레이드 전 naive 소스 등록은 query 시점에 동작을 멈춘다** (위 `DataSnapshotError`).
   이것이 의도된 안전성이지만 migration note로 **기록**해야 하며 사용자가 발견하게 두면 안 된다.
3. **`DailyExecutionFlow._registry_fingerprint`**(:551-556)가 identity를 해싱하므로 업그레이드 전
   run의 resume은 `RESUME_BRANCH_REQUIRED`. 설계상 올바르며
   `test_gap_recovery_001_changed_identity_requires_explicit_branch`가 이미 커버.

**권장(선택):** `RegistrationEvidence`(contracts.py:72)에
`localized_source_timezone: str | None = None`을 추가하고 실제 localize가 일어났을 때만 설정.
identity 중립(evidence는 identity payload가 아님)이고 "무엇을 가정했는가"가 감사 가능해진다.
기존 fixture는 `None` 또는 `"UTC"`이고 `available_at_min/max` 문자열은 오늘과 byte-identical.

#### fixture migration — 정확한 계획

폭발 반경이 커 보이지만 **등록당 필드 1개 추가 / assertion 변경 0건**으로 끝난다. 모든 naive
fixture가 의도적으로 15:30 KST를 naive 06:30(= naive UTC)으로 인코딩하므로
`source_timezone="UTC"`가 오늘의 coercion을 byte-for-byte 재현한다.

**Group A — `source_timezone="UTC"` 추가 (parquet 재생성 불필요, assertion 무변경):**

| 파일 | 등록 |
|---|---|
| `tests/acceptance/real_dw_support.py` | :235 `dw-real-market`, :269 `real-k200-benchmark`, :298 `real-k200-etf-constituents`, :331 `real-extension-market`, :348 `real-extension-sector` |
| `tests/acceptance/test_historical_strategy_scenarios.py` | :108 `peer-momentum-market`, :131 `peer-momentum-benchmark` |
| `tests/acceptance/test_analysis_scenarios.py` | :89 `real-analysis-return` |
| `tests/acceptance/test_research_scenarios.py` | :300 `shadow-k200-benchmark` |
| `tests/test_data_registration.py` | **:18 공유 `registration()` helper 1곳** — :37, :57, :95, :147, :163의 5개 naive CSV 테스트가 한 번에 해결 |
| `tests/test_cli.py` | :31 YAML payload에 `"source_timezone": "UTC"` |

`real_dw_support.py` 수정 시 각 `source_provenance` 문자열도 "물리 컬럼은 naive UTC이고 *규약*은
15:30 / 09:00 Asia/Seoul"임을 명시하도록 확장할 것. identity가 바뀌지만 무해(fresh tmp project)하고
같은 커밋에서 하면 identity churn이 정확히 한 번만 일어난다.

**naive→UTC 재해석을 assert하는 2개 테스트는 무변경으로 green 유지**되며, 이제 *가정*이 아니라
*선언된* 변환을 검증하게 된다:
- `tests/acceptance/test_extension_scenarios.py:131` — `max_available_at == datetime(2024, 2, 1, 9, 0, tzinfo=KST)`
- `tests/acceptance/test_lookthrough_scenarios.py:371-377` — `2024-01-03T09:00:00+09:00`

**Group B — 절대 건드리지 말 것.** 이미 offset 있음. 추가하면 `TIMESTAMP_TIMEZONE_UNUSED`가 된다:
- `src/qlibx/resources/samples/{basic,constraint_workflow,daily_closed_loop}/registration.yaml` + CSV
- `tests/test_public_daily.py:128`, `tests/test_public_constraints.py:106`, `tests/test_pit_research.py:24`

**신규 테스트 (`tests/test_data_registration.py`):**
1. `test_naive_source_timestamps_require_declared_timezone` — 동일 CSV, `source_timezone` 없음 →
   FAILED, `error_code == "TIMESTAMP_TIMEZONE_UNDECLARED"`,
   `stage_path == "dataset.register.timestamp_timezone"`, `commit_status.value == "NONE"`,
   `registry_snapshot().datasets == ()`
2. `test_declared_source_timezone_localizes_naive_timestamps` — `DATE=2025-01-02T15:30:00` naive +
   `source_timezone="Asia/Seoul"` → `evidence.available_at_min == "2025-01-02T06:30:00+00:00"`;
   `as_of=06:29Z` view는 0행, `06:30Z`는 1행. **필드 echo가 아니라 PIT 관측 가능한 증거여야 한다**
3. `test_declared_timezone_over_aware_timestamps_is_rejected` → `TIMESTAMP_TIMEZONE_UNUSED`
4. `test_unknown_source_timezone_is_a_validation_error` → `pytest.raises(ValidationError)`

#### F-04 (`os.rename`)

같은 파일·같은 책임(신뢰할 수 있는 append-only 등록)이므로 C2에 포함한다.

`os.rename` → `os.link(temporary, destination)` + `temporary.unlink()`. `os.link`는 **양 플랫폼
모두에서** `FileExistsError`를 던지고, 임시 파일이 `self._registry_dir`에 생성되므로 동일
파일시스템이 보장되어 POSIX에서 원자적이다. 기존 재귀 retry(`:251-253`)가 설계대로 동작하게 된다.
`os.link`를 못 쓰는 파일시스템 대비 `open(destination, "x")` 방식 fallback을 고려하고 레코드에 선택
근거를 남길 것.

기존 `test_registration_conflict_does_not_replace_existing_identity`(:145-158)가 이미 충돌을 커버하며
Windows에서 오늘도 통과하고 이후 POSIX에서도 통과한다. 개발 플랫폼에서 재현 불가한 결함이므로
신규 테스트 대신 플랫폼 근거를 주석으로 남긴다.

#### 문서

- `resources/skills/qlibx/references/error-recovery.md` — 3개 error code 행 추가
- `resources/skills/qlibx/SKILL.md` — "Register data" 5단계 확장: naive timestamp에 timezone을
  절대 가정하지 말고 `source_timezone`을 선언할 것
- PRD §15.5 — C3에서 통합 행 추가 (여기서는 없음)
- Architecture §17 — `### 2026-08-07 — 선언된 source timezone과 naive timestamp 거부`:
  `ConfirmedDelayRule.user_confirmed`와 같은 계열의 사용자 확인 선언이라는 점, identity churn migration

**Validation:** `pytest tests -q` → 146 passed (142 + 4).

### 4.2 C3 — `fix: filter sessions in the declared session timezone`

#### 새 시그니처

```python
# src/qlibx/context/scoped.py
def session(self, semantic_role: str, session_date: date, *, session_timezone: str) -> pd.DataFrame
def _read(self, semantic_role, *, session_date=None, session_timezone=None, observation_at=None)

# src/qlibx/data/store.py
def query(self, dataset, *, field, as_of, session_date=None, session_timezone=None, observation_at=None)
```

**default 없는 필수 keyword.** `"UTC"` default는 모든 사용자 strategy에서 오늘의 버그를 조용히
보존한다. 필수·keyword-only로 만들어 8개 호출부 전부가 자기 달력을 선언하게 강제한다 —
`source_timezone`과 같은 "가정하지 말고 선언하라" 속성. 0.1.0에서 허용 가능한 breaking change이며
그것이 요점이다.

`store.query`에 :28의 `as_of` 검사와 같은 계열의 guard 추가:
`session_date is not None and session_timezone is None` →
`ValueError("session query requires an explicit session_timezone")`.

#### 필터 구현

`store.py:90` 교체:

```python
visible["observation_time"].dt.tz_convert(ZoneInfo(session_timezone)).dt.date == session_date
```

미리 계산한 half-open UTC 구간이 아니라 `tz_convert`를 쓰는 이유: 여기 frame은 2~8행이고,
localize된 자정에 대한 `fold` 추론 없이 pandas가 DST로 길이가 달라지는 지역일을 올바로 처리한다.

#### session timezone의 경로

`DailyExecutionProfile.session_timezone`(`daily.py:256`) → `_profile` → 이미
`ZoneInfo(self._profile.session_timezone)`로 `session_date`를 계산하는 두 호출부:
`daily.py:887-888`, `:897`(`_on_execution` 가격·거래량 frame), `:1192-1193`(`_on_mark`).
`view.session(role, session_date, session_timezone=self._profile.session_timezone)`가 되면
날짜와 필터가 일치한다 — **그것이 F-01의 수정이다.**

#### `flow/analysis.py:223` — timezone 없는 bare date

`SignalAnalysisRequest.return_session: date`(`analysis/results.py:92`)에는 달력이 없다.
**필수** 필드 추가:

```python
return_session_timezone: str = Field(min_length=1)   # ZoneInfo 검증
```

구성 지점은 2곳뿐이고 둘 다 KRX 데이터라 `"Asia/Seoul"`이 된다:
`src/qlibx/resources/samples/basic/run.py:132`, `tests/acceptance/test_analysis_scenarios.py:48`.
assertion 중립(analysis fixture의 `observation_time`은 naive 자정 → 00:00 UTC → 같은 날 KST 09:00;
sample은 `09:00+09:00`. 둘 다 UTC/KST에서 같은 날짜). exported model의 public API break이므로 문서화.

#### `samples/basic/strategy.py:18` — UTC 날짜

현재 `view.session("decision_return", view.as_of.date())` — UTC 날짜이고 repo의 다른 모든
strategy와 이미 불일치. 다음으로 변경:

```python
KST = ZoneInfo("Asia/Seoul")
session = view.as_of.astimezone(KST).date()
frame = view.session("decision_return", session, session_timezone="Asia/Seoul")
```

번들 데이터에서는 동작 불변(`as_of` 15:30 KST → 두 달력 모두 2024-01-02; `date` 컬럼 09:00 KST →
두 달력 모두 2024-01-02)이므로 `manifest.json`의 `expected_direct_winner: A005930` 유지.
**레코드에 남길 부작용:** 파일 bytes가 바뀌므로 이미 `examples/qlibx_owned/basic/strategy.py`를
materialize한 사용자는 다음 `project sample --apply`에서 `ChangeAction.CONFLICT`를 만난다.
version-matched sample의 문서화된 안전 동작이지 회귀가 아니다. 테스트는 fresh tmp dir이라 무영향.

`samples/daily_closed_loop/strategy.py:25`는 이미 KST를 계산하므로 kwarg만 추가.

#### 깨지는 테스트 (전부 기계적 kwarg 추가)

`tests/acceptance/real_dw_support.py:408, :444, :467`,
`tests/acceptance/test_historical_strategy_scenarios.py:175` → `session_timezone="Asia/Seoul"`
`tests/acceptance/test_analysis_scenarios.py:48` → `return_session_timezone="Asia/Seoul"`

assertion 값은 하나도 바뀌지 않는다.

#### 신규 회귀 테스트 — `tests/test_session_timezone.py` (필수)

기존 fixture는 전부 두 달력의 날짜가 같아 **아무것도 증명하지 못한다.** 경계를 넘는 CSV를 만든다:
`observation_time`이 `2024-01-02T23:30:00+09:00`(= 14:30 UTC, 2024-01-02)와
`2024-01-03T00:30:00+09:00`(= 15:30 UTC, **UTC로는 2024-01-02**).

- `session(role, date(2024,1,3), session_timezone="Asia/Seoul")` → 두 번째 instrument만
- `session(role, date(2024,1,2), session_timezone="UTC")` → 둘 다
- `session(role, date(2024,1,3), session_timezone="UTC")` → 없음

구 코드에서는 KST 2024-01-03 조회에서 해당 행이 조용히 사라진다. **F-01이 고쳐졌음을 증명하는
유일한 테스트다.**

#### 문서

- PRD §15.5 — 신규 행 `GAP-TIME-001` (declared time semantics closed): "Naive source timestamps는
  declared `source_timezone` 없이 등록되지 않으며, session query는 declared session timezone의
  calendar day로 filter한다", closure fixture `tests/test_data_registration.py`와
  `tests/test_session_timezone.py`. **`UC-`가 아니라 `GAP-` 접두어를 쓸 것** —
  `tests/test_document_traceability.py`가 PRD의 모든 `UC-XXX-NNN`이 architecture 문서에도 있어야
  한다고 검증한다. 레코드 031이 쓴 것과 같은 기법.
- Architecture §17 — C2 항목에 session-calendar 결정을 확장(같은 날짜 heading 중복 생성 금지)
- README 변경 없음

**Validation:** `pytest tests -q` → 149 passed (146 + 3).

### 4.3 C4 — `refactor: extract pure order sizing and session performance`

#### 4a — `src/qlibx/execution/sizing.py` (신규)

`daily.py:904-943` 추출. `portfolio/construction.py:76`
(`construct_portfolio(request, source)` + `PortfolioConstructionError`) 패턴을 그대로 따른다.

```python
class SizingTarget(QlibxModel):   instrument_id: str; weight: float = Field(ge=0)
class SizingPrice(QlibxModel):    instrument_id: str; price: float
class SessionSizingRequest(QlibxModel):
    session_date: date
    sizing_price_role: str = Field(min_length=1)
    targets: tuple[SizingTarget, ...]
class SessionSizingInput(QlibxModel):
    account_state: StateAccessRecord         # qlibx.context — execution layer에서 합법
    prices: tuple[SizingPrice, ...]
@dataclass(frozen=True, slots=True)
class SessionSizing:
    sizing_nav: float
    required_instruments: tuple[str, ...]
    orders: tuple[Order, ...]
class SizingError(ValueError):  code, context
def size_session_orders(request, source) -> SessionSizing
```

설계 포인트:

- **`StateAccessRecord`를 account 대체물로 쓰는 것이 안전함을 확인했다.**
  `AccountSnapshot.holdings()`(`account/account.py:88-89`)와 `_state()`(`daily.py:372-380`)는 모두
  같은 `positions` 튜플의 직접 투영이므로
  `{h.instrument_id: h.quantity for h in account_state.holdings}`는 `before.holdings()`와 동일하다.
  zero-quantity 차이 없음. flow는 `match_batch(holdings=...)`(`daily.py:957`)용으로
  `holdings = before.holdings()`를 계속 계산한다 — 그 호출부는 변경하지 않는다.
- **`SessionSizing`은 `QlibxModel`이 아니라 frozen dataclass.** `Order`(`execution/exchange.py:74`)가
  frozen dataclass라 pydantic 필드로 쓰려면 `arbitrary_types_allowed`가 필요하다. `execution/`의
  기존 스타일과 일치.
- **실패 조건을 typed error로, payload는 byte-identical하게:**
  - `EXECUTION_SESSION_PRICE_MISSING`, context `{"session": str(session_date), "instruments": list(missing[:20])}`
  - `EXECUTION_SIZING_NAV_INVALID`, context `{"sizing_nav": sizing_nav}`

  flow가 `SizingError`를 잡아 `self._fail(event, "execution", exc.code, context=exc.context)`를
  호출한다. 방출되는 `OperationError`는 오늘과 동일.
- **모듈 docstring에 반드시 남길 것:** `sizing_nav`는 **execution-session 가격**에서 계산하며
  `before.nav`(mark 기반)가 아니다. 이것이 `ExecutionEvidence.sizing_price_role`(`daily.py:124`)이
  존재하는 이유다. **이 문장을 이동 중에 잃는 것이 이 리팩터의 가장 큰 위험이다.**
- 순서 정확히 보존: sell 우선, 그다음 alphabetical(`daily.py:943`), `±1e-12` dead band.
- `src/qlibx/execution/__init__.py`에 신규 이름 export.

`test_architecture.py` 변경 불필요 (`execution: {context, data, domain, models, errors}`가 이미
`context`를 허용).

#### 4b — `src/qlibx/analysis/sessions.py` (신규)

`daily.py:1301-1320` 추출 + **`SessionPerformanceEvidence`(`daily.py:141-200`,
`validate_reconciliation` 포함)를 analysis layer로 이동.** 근거: reconciliation validator가 곧
산술 계약이며, 계산과 레이어를 갈라놓으면 불변식이 중복된다.

```python
class SessionExecutionInput(QlibxModel):  event_id: str; trade_value: float; transaction_cost: float
class SessionPerformanceRequest(QlibxModel):
    event_id, event_time, source_mark_event_id, source_execution_event_ids
class SessionPerformanceInput(QlibxModel):
    opening: StateAccessRecord; closing: StateAccessRecord
    executions: tuple[SessionExecutionInput, ...]
class SessionPerformanceEvidence(QlibxModel):   # 필드 집합/순서 그대로 이동
def compute_session_performance(request, source) -> SessionPerformanceEvidence
```

- `flow/daily.py`는 `qlibx.analysis`에서 import하고 `flow/__init__.py:43,97`이 계속 re-export →
  `_PublishedSessionPerformance`(:324), :1948의 `ArtifactContract`, :2005의 `isinstance` 분기 churn 0
- **직렬화 불변**(같은 필드·같은 순서)이므로 저장된 `session_performance` artifact가 그대로 로드된다
  — §16.3 충족. 이동 전 생성된 artifact를 로드해 검증할 것
- `context/scoped.py:100-109`(`SessionPerformanceRecordState`)는 구조적 `Protocol`이라 계속 매치
- **신규 error code `SESSION_PERFORMANCE_NOT_RECONCILED`** — reconciliation identity 실패 시
  `AnalysisError`로 raise. 오늘은 이 조건이 raw pydantic `ValidationError`로 `_on_monitor`를
  빠져나가 run을 죽인다. 이 추출이 고치는 잠재 2차 버그이므로 레코드에 명시

#### 4c — `_on_monitor` (F-08)

`daily.py:1288-1295`: mark가 없을 때 **`_fail`을 부르지 않는다.** session performance 발행을
건너뛰고 `MonitorEvidence` 발행으로 진행한다. 누락을 관측 가능하게
`MonitorEvidence`(`daily.py:203-207`)에 추가:

```python
session_performance_status: Literal["published", "skipped_missing_mark"] = "published"
```

default가 있으므로 `monitor_observation` v1 artifact가 계속 로드된다.

**강등이 안전한 근거:** `_drain`(`daily.py:592-600`)이 첫 오류에서 break하므로 실패한 `_on_mark`는
`_on_monitor`에 도달하지 못한다. 그리고 `_restore_recovery_point`가
`_hydrate_run_evidence()`(`daily.py:1919`)를 호출해 발행된 `mark_result` artifact에서 `self._marks`를
재구성하므로 MARK와 MONITOR 사이 resume도 커버된다. 즉 `SESSION_MARK_EVIDENCE_MISSING`은 정상
경로에서 구조적으로 도달 불가이며, 오늘은 이미 기록된 root cause에 중복 2차 오류만 더한다.
`SESSION_SOURCE_ARTIFACT_MISSING`(:1359-1366)은 발행된 artifact에 대한 진짜 검사이므로 flow에 유지.

#### 테스트

- `tests/test_execution_sizing.py` (신규, ~8): sell 우선 후 alphabetical; 양쪽 `1e-12` dead band;
  보유 중인데 session price 없음 → `EXECUTION_SESSION_PRICE_MISSING` 20개 절단;
  `nan`/`inf`/`0`/음수 nav → `EXECUTION_SIZING_NAV_INVALID`; **`sizing_nav`가 `account_state.nav`가
  아니라 session price를 쓴다는 property 테스트**(stale mark와 session price가 다른 포지션을 두고
  결과 수량을 assert)
- `tests/test_analysis_sessions.py` (신규, ~4): opening NAV 0 → 4개 비율 전부 `None`; 양수 NAV →
  4개 전부 reconcile; `gross_return - transaction_cost_rate == portfolio_return`;
  reconcile 안 되는 입력 → `SESSION_PERFORMANCE_NOT_RECONCILED`
- **기존 daily/acceptance 테스트는 무변경 통과해야 한다 — 그것이 이 리팩터의 acceptance criterion이다**

**Validation:** `pytest tests -q` → 약 161 passed. 문서 변경 불필요(Architecture §17 선택).

### 4.4 C5 — `fix: keep operations pure and classify compute failures`

#### 5a — F-07 (`flow/composition.py`)

- netting/budget 계산을 `run()`(:154-226) 밖 module-level 순수 함수로 이동, frozen
  `_EnsembleComputation(weights, contributions, gross_before, gross_after, net)` 반환
- `EnsembleStrategyOperation.__init__`(:136-149)이 기존 `_validate_state_compatibility()` 옆에서
  **한 번** 계산. definition과 이미 로드된 immutable member result에만 의존한다 —
  `run()`이 `del view`(:155)를 하는 것이 view 입력이 없다는 증거
- `ENSEMBLE_GROSS_EXCEEDS_TARGET`, `ENSEMBLE_FIXED_BUDGET_INCOMPATIBLE`이 이제 생성자에서 raise.
  `run()`은 immutable computation으로 `StrategyDraft`를 만들고, `evidence()`(:228-244)는 순수 read.
  mutable `self._contributions/_gross_before/_gross_after/_net` 제거
- **`composition.py:346`의 probe(`operation.run(object())`) 삭제.** 기존
  `try/except EnsembleCompatibilityError`(:344-348)가 이제 :345의 생성자만 감싼다. 관측 순서는
  불변(compatibility error가 여전히 발행보다 앞선다)이고 `run()`은 `invoke_strategy` 안에서 정확히
  1회 실행된다
- `StoredSignalStrategyOperation.run`(:290+)은 이미 순수함을 레코드에 언급(독자의 의문 방지)

테스트: 기존 ensemble acceptance 결과 불변. 추가 — `run(view)` 2회 호출이 동등한 draft를 반환;
`evidence()`가 `run()` 호출 여부와 무관하게 동일(직접적 purity 회귀); gross 초과 definition이
생성 시점에 raise.

#### 5b — F-09 실패 분류 (3+1개 사이트)

| 파일 | 라인 | 변경 |
|---|---|---|
| `flow/constraints.py` | 75-99 (`adjust`) | `self._benchmark(...)`를 별도 try → `.data` / `CONSTRAINT_DATA_READ_FAILED`; `adjust_single_name_caps(...)`를 두 번째 try → `.compute` / `ConstraintEvaluationError.code` 또는 **`CONSTRAINT_COMPUTE_FAILED`** |
| `flow/constraints.py` | 144-168 (`validate`) | 동일 분리 |
| `flow/monitoring.py` | 63-90 | `view.account_snapshot()` + `_benchmark(...)`는 `.data` / `MONITORING_DATA_READ_FAILED`; `monitor_actual_single_name_caps(...)`는 `.compute` / **`MONITORING_COMPUTE_FAILED`** |
| `flow/analysis.py` | 222-261 | **D5로 범위 포함.** `view.session(...)`과 `analyze_signal(...)`이 한 try를 공유해 compute 실패가 `ANALYSIS_DATA_READ_FAILED`로 보고됨. **`ANALYSIS_COMPUTE_FAILED`** 추가 |

테스트: 기존 assertion 무영향(compute 실패에 `.data` stage를 assert하는 것이 없음). 추가 —
`tests/test_public_constraints.py`에 pure 함수를 monkeypatch해 `RuntimeError` → `.compute` stage의
`CONSTRAINT_COMPUTE_FAILED`; 소스 삭제 → `.data` stage의 `CONSTRAINT_DATA_READ_FAILED`.

#### 5c — F-10 (`daily.py:1159-1175`)

:1276-1286의 올바른 정상 경로와 같게 재정렬:

```python
published = self._publish_model(...)
if published is not None:
    self._marks.append(evidence)
return
```

테스트: 첫 session close가 어떤 decision보다 앞서는 spec(holdings 빈 상태)에서
`LocalArtifactBackend.publish_model`을 `artifact_type == "mark_result"`일 때 실패하도록 monkeypatch.
outcome이 `ARTIFACT_PUBLICATION_FAILED`로 FAILED이고 반환 diagnostics에 `mark_result`가 없음을
assert. 이 배치에서 가장 까다로운 테스트이며 이미 최소 spec을 구성하는 `tests/test_public_daily.py`가
자연스러운 위치.

문서: `resources/skills/qlibx/references/error-recovery.md`에 `*_COMPUTE_FAILED` 계열 추가
("A pure operation failed on validated input — report the bounded diagnostic; do not retry with the
same frozen input").

**Validation:** `pytest tests -q` → 약 166 passed.

### 4.5 C6 — `feat: expose bundled samples and constraint monitoring`

#### `ConstraintMonitoringSpec` 설계

`src/qlibx/constraints.py`, 30줄짜리 `ConstraintValidationSpec` 템플릿(:103-133) 그대로:

```python
class ConstraintMonitoringSpec(QlibxModel):
    """Frozen public input for independent monitoring of committed Account state."""
    spec_schema_version: Literal[1] = 1
    invocation_id: str = Field(min_length=1)
    checkpoint_artifact_id: str = Field(min_length=1)
    evaluation_time: datetime
    policy: MvpConstraintPolicy

    @model_validator(mode="after")  -> require_aware(self.evaluation_time)
    def frozen_config_fingerprint(self) -> str   # _fingerprint({spec_schema_version, policy})
    def to_request(self) -> ConstraintMonitoringRequest(invocation_id, config_fingerprint)
```

**request에 `evaluation_time`이 없는데 어떻게 다루는가:**
`ConstraintMonitoringRequest`(`portfolio/constraints.py:54-56`)는 `invocation_id` +
`config_fingerprint`만 갖고, 평가 시각은 오직 `clock.now`(`monitoring.py:57, 68, 71`)로 들어간다.
따라서 spec이 `evaluation_time`을 보유하고 facade가 clock을 만든다:
`MonitoringFlow(clock=BacktestClock(spec.evaluation_time), ...)`.
`ConstraintMonitoringRequest`는 **확장하지 않는다** — 내부 operation 계약으로 남기고 public spec이
instant를 공급한다. `ConstraintValidationSpec.evaluation_time`이 `flow/constraints.py:141`에서
`BacktestClock`을 먹이는 것과 정확히 같은 구조.

spec docstring에 반드시 남길 2가지:
1. 같은 instant가 account 평가(`Account.snapshot(evaluation_time=clock.now)`)와 PIT benchmark
   cutoff(`view.latest(...)`)를 **동시에** 결정한다. 이 단일 instant 의미론은 의도된 것이다
2. pure operation이 `valuation_status == "STALE"`을 거부한다(`portfolio/constraints.py:319`).
   checkpoint의 마지막 mark보다 한참 뒤의 `evaluation_time`은 account를 stale로 만들어
   `ACCOUNT_VALUATION_STALE`로 실패한다. **`evaluation_time`은 checkpoint가 mark된 session close여야
   한다**

**Idempotency:** `tests/acceptance/test_research_scenarios.py:530-535`가 고정 clock에서 반복
`flow.run`이 같은 `artifact_id`를 반환함을 assert한다. facade는 모든 입력이 frozen spec +
immutable artifact의 결정론적 함수이므로 이를 보존한다 — `BacktestClock(spec.evaluation_time)`(spec에서,
wall clock 아님), `Account.from_checkpoint(...)`(immutable artifact에서),
`logical_identity = f"constraint-monitoring:{spec.invocation_id}"`.
**이것이 `evaluation_time`이 spec에 사는 결정적 이유다.** facade 안에서 wall clock을 읽으면
idempotency가 깨지고 `test_production_source_does_not_read_wall_clock_directly`도 실패한다.

#### mutable Account 문제와 facade

`QlibxProject`에 `Account`를 얻을 public 경로가 없다. 유일한 경로:
`SimulationCheckpoint`(`daily.py:220-233`)의 `account_checkpoint: AccountCheckpoint` →
`QlibxProject.load_artifact`로 로드(`SIMULATION_CHECKPOINT_CONTRACT`, `flow/analysis.py:51`) →
`Account.from_checkpoint`(`account/account.py:207`).

```python
def monitor_constraints(self, spec: ConstraintMonitoringSpec) -> OperationOutcome:
    """Independently monitor committed Account state under the selected MVP policy."""
    loaded = self.load_artifact(spec.checkpoint_artifact_id, SIMULATION_CHECKPOINT_CONTRACT)
    if loaded.status is not OutcomeStatus.COMPLETE:
        return loaded
    try:
        account = Account.from_checkpoint(loaded.result.payload.account_checkpoint)
    except ValueError as exc:
        return _checkpoint_failure(spec, exc)     # MONITORING_ACCOUNT_CHECKPOINT_INVALID
    return MonitoringFlow(
        clock=BacktestClock(spec.evaluation_time),
        registry=self.registry_snapshot(),
        artifacts=self.artifacts,
        account=account,
    ).run(spec.policy.to_declaration(), spec.to_request())
```

`Account.from_checkpoint`는 4가지 무결성 위반(version/journal 길이, event identity, 시간 순서,
`as_of` 불일치)에서 `ValueError`를 던진다. 이를 새어나가게 두면 public facade의 유일한 untyped
실패가 된다. `_checkpoint_failure`는 `project.py`의 작은 private helper로
`OperationError(operation="monitoring.constraint", stage_path="monitoring.constraint.checkpoint",
error_code="MONITORING_ACCOUNT_CHECKPOINT_INVALID", commit_status=NONE,
idempotency_identity=spec.invocation_id)`를 만든다.

`project.py`는 이미 `Account`(:5)와 `BacktestClock`(:28)을 import하므로 신규 import는
`MonitoringFlow`와 `SIMULATION_CHECKPOINT_CONTRACT`뿐이다.

> **C6 착수 전 확인할 것:** `src/qlibx/account/account.py`의 정확한 `ValuationStatus` staleness
> 규칙(`snapshot()`의 `stale` 계산)을 읽고 `evaluation_time`이 checkpoint의 마지막 mark를 얼마나
> 촘촘히 따라야 하는지 확정한 뒤 docstring과 stale 테스트를 쓸 것.

#### 나머지 파일

| 파일 | 변경 |
|---|---|
| `src/qlibx/sample.py` | :30의 shadowed 클래스 속성 `sample_id = default_sample_id` 제거; `_samples`를 `dict[str, str]`로(source == destination이 항상 참이었음); `@classmethod sample_ids(cls) -> tuple[str, ...]` 추가; `default_sample_id`는 `project.py:107`의 기본 인자로 쓰이므로 유지 |
| `src/qlibx/cli.py` | :38-40에 `--sample-id` 추가 (`default=SampleMaterializer.default_sample_id`, `choices=sorted(...sample_ids())`); :111에서 전달 |
| `src/qlibx/project.py` | `monitor_constraints` + `_checkpoint_failure`; `cli.py`가 `sample.py`를 직접 건드리지 않도록 `available_sample_ids()` classmethod |
| `src/qlibx/__init__.py` | import + `__all__`(정렬 유지): `ConstraintMonitoringSpec`, `CostRule`, `EtfInstrument`, `KrxExchangeConfig`, `Side`, `StockInstrument` |
| `README.md` | :20-35 블록에 `--sample-id daily-closed-loop-v1`, `--sample-id constraint-workflow-v1` 예시 추가 |

#### 테스트

- `tests/test_sample.py` — 번들 id별 CLI 케이스(대상 폴더와 전부 `CREATE` assert);
  `run(["project","sample",root,"--sample-id","nope"])`를 `pytest.raises(SystemExit)`로
  (argparse `choices`는 exit 2이고 `run`의 `except Exception`에 잡히지 않는다);
  `SampleMaterializer.sample_ids()`가 3개 번들 디렉터리와 일치
- `tests/test_public_constraints.py` — `monitor_constraints` end-to-end(daily 시뮬레이션 실행 →
  발행된 `simulation_checkpoint` id 로드 → 마지막 session close를 `evaluation_time`으로 spec 구성 →
  COMPLETE + `constraint_monitoring_result` diagnostic). **추가로
  `test_research_scenarios.py:530-535`를 본뜬 idempotency 케이스**(같은 spec 2회 → 동일 결과, 동일
  `artifact_id`). stale 케이스(`evaluation_time`이 checkpoint보다 한참 뒤) → `ACCOUNT_VALUATION_STALE`.
  손상 checkpoint → `MONITORING_ACCOUNT_CHECKPOINT_INVALID`
- `tests/test_contracts.py` — `from qlibx import CostRule, EtfInstrument, KrxExchangeConfig, Side,
  StockInstrument, ConstraintMonitoringSpec`가 되고 **top-level `qlibx` 이름만으로
  `DailySimulationSpec`을 구성할 수 있음**을 assert

#### 문서

- README :20-35
- PRD §15.5 — 신규 행 `GAP-MONITOR-001` (public no-trade monitoring closed): "설치 project가
  committed Account checkpoint에서 독립 constraint monitoring을 frozen spec으로 실행하고, 같은
  spec의 반복 실행이 같은 artifact identity를 반환한다", closure fixture
  `tests/test_public_constraints.py`. **`GAP-` 접두어, 절대 `UC-` 아님**
- Architecture §17 — `### 2026-08-07 — public sample 선택과 constraint monitoring 노출`:
  `SimulationCheckpoint → AccountCheckpoint → Account.from_checkpoint`가 mutable `Account`로 가는
  공인 public 경로라는 점, `evaluation_time`이 spec에 사는 이유(idempotency + wall-clock 금지)

**의도적 범위 제외:** 4번째 번들 sample 없음, `constraint_workflow`에 monitoring 단계 추가 없음.
sample fingerprint와 테스트 표면만 늘고 추가 closure evidence가 없다. Remaining limitations에 기록.

**Validation:** `pytest tests -q` → 약 171 passed; `ruff check .`;
`uv build` + 설치된 wheel로 `qlibx project sample <root> --sample-id daily-closed-loop-v1` smoke.

---

## 5. Process 의무

### 5.1 ExecPlan

`.agent/plans/active/code-review-remediation.md`가 이미 작성되어 있다. `AGENTS.md:53-56`이
책임을 넘나드는 작업에 ExecPlan을 요구하며 이 작업은 `data`, `context`, `execution`, `analysis`,
`flow`, public facade, CLI, 문서 3개를 넘나든다. 각 커밋 후 `Progress` / `Validation` /
`Next action`을 갱신하고 C6 후 `.agent/plans/completed/`로 이동한다.

`.gitignore`가 `/.agent/plans/**`를 무시하므로 **commit 대상이 아니다** (최근 plan들도 untracked).

### 5.2 Implementation record

`AGENTS.md:89-105`. 파일명 `NNN-kebab-case-slug.md`, 현재 최고 번호는 **031**이므로 032부터.
번호는 재사용·재번호 금지. 구조(레코드 030·031 기준):

```
# NNN Title Case sentence
## Intent                      — 왜 존재하는가, 이전 상태가 못 하던 것
## Observable outcome          — 설치 사용자 관점의 가시적 동작, 구체적 실패 의미
## Responsibilities and flow   — 타입/컴포넌트별 bullet, 소유권과 데이터 흐름
## Alternatives and trade-offs — 기각한 설계와 이유
## Validation                  — verbatim 명령 + `-> N passed in T s`
## Remaining limitations       — 명시적으로 범위 밖인 것
```

**doc-only / harness-only 변경에는 레코드를 만들지 않는다** (`AGENTS.md:100-101`).

### 5.3 Commit 규약

Conventional Commits, **subject line만**. body 없음, trailer 없음, **`Co-Authored-By` 없음**
(최근 25개 커밋 확인). 소문자, 명령형, 마침표 없음, 4~6단어.
사용자가 커밋을 명시적으로 승인했다. **`push`는 승인하지 않았다.**

### 5.4 문서 동기화 의무

| 표면 | 위치 | 의무 |
|---|---|---|
| CLI 명령 | `README.md:20-35` — 유일한 사람이 읽는 목록 | CLI 변경과 같은 커밋에서 수작업 갱신 |
| Public export | `src/qlibx/__init__.py.__all__` | 미러링 문서 없음. 레코드 Validation에 import smoke 기재 |
| Readiness gap | PRD §15.5 표(`qlibx-prd.md:1697-1702`) | gap 종료 시 closure fixture 이름 명시 |
| 설계 결정 | Architecture §17 개정 이력(`:2435`) | `### YYYY-MM-DD — <title>` |

**`tests/test_document_traceability.py:12-16`이 PRD의 모든 `UC-XXX-NNN`이 architecture 문서에도
있어야 함을 검증한다. 새 `UC-` ID를 만들지 말고 `GAP-` 접두어를 쓸 것.**

---

## 6. 충돌·위험 요약

1. **F-03 ↔ `registration_identity` 소비자 전부.** identity churn은 불가피하며 재등록
   (`REGISTRATION_IDENTITY_CONFLICT`), 업그레이드 전 resume(`RESUME_BRANCH_REQUIRED`), 업그레이드 전
   naive 등록의 query(`DataSnapshotError`)에 영향. 셋 다 설계상 올바르지만 **기록해야 하고 사용자가
   발견하게 두면 안 된다.**
2. **F-08 ↔ F-10 (순서).** C4가 C5보다 먼저여야 한다 (§4.0).
3. **F-01 ↔ F-12 (순서).** C3가 C4보다 먼저여야 한다 (§4.0).
4. **F-05 ↔ F-13 (같은 커밋).** `--sample-id`의 `choices`가 F-13이 도입하는
   `SampleMaterializer.sample_ids()`를 필요로 한다.
5. **F-06 ↔ F-11 (같은 커밋).** `ConstraintMonitoringSpec`이 다른 신규 top-level 이름과 함께
   export되지 않으면 facade가 반쪽만 도달 가능하다.
6. **F-01 ↔ sample fingerprint.** `samples/basic/strategy.py` 수정으로 이미 materialize한 사용자
   사본이 `ChangeAction.CONFLICT`가 된다. version-matched sample의 올바른 동작이므로 레코드 034에
   명시.
7. **검증된 non-risk (재조사 불필요):** `StateAccessRecord.holdings`와 `AccountSnapshot.holdings()`는
   같은 `positions` 튜플의 직접 투영(`account/account.py:88-89`, `daily.py:372-380`)이므로
   operation layer의 account 대체물로 써도 order 집합이 달라질 수 없다.

### 이 작업 범위 밖의 미해결 항목

`docs/code-review/2026-08-06-1500-current-scope-engine-review.md`의 **F-02**(동일 semantic role
다중 후보를 실패 없이 알파벳순 선택, `:262`)와 **F-08**(`AccountCommitRejected`가 raw 예외로 전파,
intraday, `:719`)은 대응 implementation record가 없고 이번 범위에도 포함되지 않았다.
번호가 이 문서의 F-02/F-08과 겹치므로 혼동하지 말 것.
