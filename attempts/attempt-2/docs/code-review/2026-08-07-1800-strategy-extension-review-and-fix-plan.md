# 2026-08-07 18:00 Strategy-extension review and fix plan

Reviewer: coding agent (Claude Opus 5)
Scope: `src/qlibx` 전체 (13,839 LOC) + `tests/` + 번들 sample
Reviewed commit: `938b884` (`docs: document installed strategy extensions`)
Branch: `exp/2nd-attempt`
Baseline: **`1 failed, 206 passed`** (`.venv/Scripts/python.exe -m pytest tests -q`) — §1 참조
Canonical documents: `docs/qlibx-prd.md`, `docs/qlibx-architecture.md`
직전 리뷰: `docs/code-review/2026-08-07-1200-review-findings-and-remediation-plan.md`

> 이 문서는 감사 기록이며 canonical contract가 아니다. PRD와 Architecture가 정본이다.
> §3의 finding 중 `CONFIRMED`는 실제 실행으로 관측했고 `PLAUSIBLE`은 코드 경로 추적으로 판단했다.
> §4의 수정 계획은 **제안**이며 사용자 승인 전에는 확정이 아니다.

---

## 0. 후속 agent를 위한 사용법

1. §1의 **red suite**를 가장 먼저 처리한다. HEAD가 통과하지 않는 상태다.
2. §2에서 직전 리뷰 13건이 실제로 닫혔는지 확인한다. 전부 닫혔으므로 재작업하지 않는다.
3. §3의 finding을 §4의 커밋 순서대로 수정한다.
4. 각 커밋마다 `docs/implementations/NNN-slug.md`를 만든다. 현재 최고 번호는 **039**이므로 040부터.
5. 각 커밋 전 `pytest tests -q`와 `ruff check .`를 통과시킨다.

```powershell
.venv/Scripts/python.exe -m pytest tests -q
.venv/Scripts/python.exe -m ruff check .
```

---

## 1. HEAD 상태 — suite가 red다

```
.venv/Scripts/python.exe -m pytest tests -q
-> 1 failed, 206 passed, 1 warning in 191.98s

FAILED tests/test_strategy_extension_sample.py::
       test_uc_extension_002_installed_strategy_sample_validates_registers_and_executes
```

`ruff check .` 는 `All checks passed!`.

이 실패는 R-01로 다루며 **제품 결함이 아니라 test harness 결함**이다. 상세는 §3.1.
직전 리뷰의 6개 커밋(`ef92c3d`~`f9efdff`)이 끝난 시점에는 green이었을 가능성이 높고, 이후 추가된
strategy extension 작업(`0dab87a`~`938b884`)에서 들어온 것으로 보인다.

### 이번 리뷰 범위에서 새로 추가된 것

직전 handoff 이후 6개 계획 커밋 외에 **계획에 없던 7개 커밋**이 strategy extension 기능을 추가했다.

| 신규/확장 파일 | LOC |
|---|---|
| `src/qlibx/flow/strategy_extensions.py` | 896 (신규) |
| `src/qlibx/flow/artifact_inputs.py` | 366 (신규) |
| `src/qlibx/extensions/local_modules.py` | 85 (신규) |
| `src/qlibx/analysis/sessions.py` | 136 (신규) |
| `src/qlibx/context/scoped.py` | 404 → 504 |
| `src/qlibx/project.py` | 199 → 361 |
| `src/qlibx/resources/samples/strategy_extension/` | 신규 sample |

전체 `src/qlibx` 는 11,120 → 13,839 LOC. 이번 리뷰의 무게중심은 이 **미검토 신규 표면**이다.

---

## 2. 직전 리뷰 13건 검증 결과 — 전부 닫힘

| 직전 finding | 검증 |
|---|---|
| F-01 session filter timezone | **닫힘.** `store.py:108-113`이 `.dt.tz_convert(ZoneInfo(session_timezone)).dt.date`로 비교. `store.py:33-34`에 explicit guard. `tests/test_session_timezone.py` 신규 |
| F-02 Python floor | **닫힘.** `requires-python = ">=3.11,<3.13"` |
| F-03 naive timestamp | **닫힘** (단, R-04 회귀 발생 — §3.4). `data/timestamps.py` 신규, `store.py:59/:61` 중복 라인 제거됨 |
| F-04 `os.rename` | **닫힘.** `registry.py`가 `os.link` + `unlink`, `FileExistsError`를 `OSError`보다 먼저 catch (순서 올바름). `REGISTRY_PUBLICATION_FAILED` fallback 추가 |
| F-05 CLI `--sample-id` | **닫힘** |
| F-06 monitoring facade | **닫힘.** `project.py:196-214` `monitor_constraints`, 설계대로 checkpoint → `Account.from_checkpoint` 경로 |
| F-07 ensemble 순수성 | **닫힘.** `composition.py:126`이 `__init__`에서 `_compute()` 1회, `run(object())` probe 제거됨 |
| F-08 `_on_monitor` | **닫힘.** `session_performance_status` 필드, mark 없을 때 `_fail` 하지 않음, `AnalysisError` 번역 |
| F-09 실패 stage 분류 | **닫힘.** `flow/analysis.py` 포함 3+1 사이트 전부 |
| F-10 빈 mark 순서 | **닫힘** |
| F-11 public export | **닫힘** |
| F-12 표적 추출 | **닫힘.** `execution/sizing.py`, `analysis/sessions.py` 신규. `daily.py` 2184 → 2161줄 |
| F-13 sample.py 정리 | **닫힘** |

구현 품질은 전반적으로 계획에 충실하다. `os.link`의 예외 순서, `_artifact_models`의
`model.__module__` 검사(`strategy_extensions.py:606`), `StrategyArtifactContractRegistry`의 중복
거부 등 계획서에 없던 방어도 스스로 추가했다.

---

## 3. Diagnostics — 신규 finding 9건

| # | 심각도 | 판정 | 위치 | 요약 |
|---|---|---|---|---|
| R-01 | high | CONFIRMED | `tests/test_strategy_extension_sample.py:73` | suite가 red. subprocess stderr strict UTF-8 decode 실패 |
| R-02 | high | CONFIRMED | `flow/strategy_extensions.py:360` | source-drift guard가 실행한 것과 다른 read를 검사 |
| R-03 | high | CONFIRMED | `extensions/local_modules.py:40` | 모듈이 `sys.modules`에 없어 pydantic forward ref 실패 |
| R-04 | medium | CONFIRMED | `data/timestamps.py:49` | 파싱 불가 컬럼을 timezone 미선언으로 오보고 (회귀) |
| R-05 | medium | CONFIRMED | `flow/strategy_extensions.py:312` | `registered()`가 catalog 전체를 역직렬화 |
| R-06 | medium | CONFIRMED | `flow/constraints.py:317` 외 | `_failure` helper가 7개 flow에 중복 |
| R-07 | low | PLAUSIBLE | `flow/strategy_extensions.py:632` | local artifact type이 package 소유 이름을 점유 가능 |
| R-08 | low | PLAUSIBLE | `flow/strategy_extensions.py:200` | determinism 검사가 artifact payload를 공유 |
| R-09 | low | CONFIRMED | `flow/artifact_inputs.py:320` | 빈 줄 3개, `_duplicates` O(n²) |

### 3.1 R-01 — suite가 red다 (CONFIRMED, 실행 확인)

**재현:**
```powershell
.venv/Scripts/python.exe -m pytest tests/test_strategy_extension_sample.py -q
```

**관측:**
```
>       assert "refusing to overwrite modified" in refused.stderr
E       TypeError: argument of type 'NoneType' is not iterable
tests\test_strategy_extension_sample.py:73

PytestUnhandledThreadExceptionWarning: Exception in thread Thread-6 (_readerthread)
  UnicodeDecodeError: 'utf-8' codec can't decode byte 0xc3 in position 53
```

**원인.** `tests/test_strategy_extension_sample.py:64-70`:
```python
refused = subprocess.run(
    [sys.executable, str(script), str(root)],
    check=False, cwd=root,
    capture_output=True, text=True, encoding="utf-8",   # errors= 없음 → strict
)
```
child가 의도적으로 실패하며 traceback을 stderr에 쓴다. traceback에는 interpreter 경로
`C:\Users\<한글>\AppData\Roaming\uv\python\...`가 들어가고, Windows child는 이를 console
codepage(여기서는 cp949)로 인코딩한다. parent는 strict UTF-8로 디코드하려다 reader thread에서
`UnicodeDecodeError`로 죽고, `refused.stderr`가 `None`이 되어 다음 줄에서 `TypeError`.

**판정 기준.** line 72의 `assert refused.returncode != 0`은 **통과한다.** 즉 제품 동작(수정된
파일 덮어쓰기 거부)은 올바르고, 실패는 순수하게 harness 문제다. 그러나 사용자 자신의 머신에서
suite가 통과하지 않는다는 사실은 그대로다. `AGENTS.md`의 환경 규칙이 non-ASCII 경로를 명시적으로
다루라고 요구한다.

**범위는 4개 파일이다.** 같은 strict-decode 패턴이
`tests/test_public_constraint_sample.py`, `tests/test_public_daily_sample.py`,
`tests/test_sample.py`에도 있다. 이들은 subprocess가 성공해 traceback을 내지 않기 때문에 우연히
통과한다. child가 실패하는 순간 같은 방식으로 깨진다.

### 3.2 R-02 — source-drift guard가 실행 대상과 다른 read를 검사한다 (CONFIRMED, 실행 확인)

`flow/strategy_extensions.py:348-378`:
```python
current_source_hash = self._module_loader.registered_source_hash(registration.module_path)  # read #1
...
if current_source_hash != registration.source_hash:      # :360  guard
    return ... STRATEGY_EXTENSION_SOURCE_DRIFT
...
loaded_module = self._module_loader.load_registered(registration.module_path, ...)          # read #2 + exec
contract = self._module_contract(loaded_module, registration.strategy_id)
```

`registered_source_hash`는 파일을 읽어 해시만 낸다(`local_modules.py:51-53`).
`load_registered` → `load`는 파일을 **다시 읽어**(`local_modules.py:34`) 자기 해시를 계산하고
`exec_module`로 **실행한다**(`local_modules.py:40`).

`load()`가 반환하는 `LoadedLocalModule.source_hash`는 실행된 바이트의 해시인데,
`load_registered`는 이 값을 `registration.source_hash`와 **한 번도 비교하지 않는다.**
:387-412에서 비교하는 것은 `spec` / `dataset_requirements` / `artifact_requirements` /
`artifact_models` 즉 **선언된 contract**뿐이다.

**재현 (실행하여 확인함):**
```python
loader = LocalModuleLoader(project_root=root, extension_root=ext)
registered_hash = loader.registered_source_hash("extensions/s.py")   # read #1
mod.write_text("VALUE = 'SWAPPED'\n")                                # 사이에 파일 교체
loaded = loader.load_registered("extensions/s.py")                   # read #2 + exec
# guard hash   : c74b7c007d7d071e
# loaded hash  : 47f4358dbd7e79fc
# hashes equal : False
# EXECUTED VALUE: SWAPPED
```

**영향.** `STRATEGY_SPEC`과 declared requirements만 유지하면 본문을 바꿔도 drift가 감지되지 않고
실행된다. registration artifact는 여전히 원래 `source_hash`와 `validation_output_hash`를 증언한다.
`docstring`이 "trusted project-local"이라고 밝히므로 sandbox escape는 아니지만,
`STRATEGY_EXTENSION_SOURCE_DRIFT`가 존재하는 이유 자체 —
**검증된 코드와 실행된 코드가 같다는 보장** — 가 성립하지 않는다.
PRD §2.8(누적 연구)과 §12.2(dependency graph and identity)가 요구하는 lineage 신뢰성 문제다.

### 3.3 R-03 — 모듈이 `sys.modules`에 등록되지 않는다 (CONFIRMED, 실행 확인)

`extensions/local_modules.py:36-40`:
```python
module_spec = importlib.util.spec_from_file_location(name, module_path)
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)          # sys.modules[name] = module 이 없다
```

pydantic은 deferred annotation을 `sys.modules[cls.__module__]`에서 해석한다. 모듈이 등록되지
않으므로 **`from __future__ import annotations`를 쓴 사용자 모듈의 중첩 model이 깨진다.**

**재현 (실행하여 확인함):**
```python
# extensions/s.py
from __future__ import annotations
from qlibx.models import QlibxModel
class Row(QlibxModel):
    instrument: str
class Payload(QlibxModel):
    rows: tuple[Row, ...]
```
```
module in sys.modules: False
PydanticUserError: `Payload` is not fully defined; you should define `Row`,
                   then call `Payload.model_rebuild()`.
```

사용자에게는 `_artifact_models`(`strategy_extensions.py:611-622`)를 거쳐
`STRATEGY_EXTENSION_ARTIFACT_MODEL_INVALID: cannot materialize JSON schema for Payload`로 보인다.
즉 loader 결함이 **사용자 model 탓으로 보고된다.** `from __future__ import annotations`는 매우
흔하고 린터가 권장하기도 하는 스타일이므로 실사용에서 부딪힐 가능성이 높다.

**수정 검증됨:** `exec_module` 앞에 `sys.modules[name] = module` 한 줄을 넣으면 동일 모듈이
정상 로드되고 schema가 생성된다(실행 확인). 실행 실패 시 `finally`에서 pop 해야 한다.

### 3.4 R-04 — 파싱 불가 컬럼을 timezone 미선언으로 오보고한다 (CONFIRMED, 회귀)

`data/timestamps.py:34`가 `errors="coerce"`이므로 전혀 파싱되지 않는 컬럼은 **전부 NaT인 naive
`datetime64[ns]` series**가 된다. 따라서 :49의 `source_timezone is None` 분기에 걸린다.

**재현 (실행하여 확인함):** `pd.Series(['N/A','unknown','N/A'])`
```
CODE: TIMESTAMP_TIMEZONE_UNDECLARED
CONTEXT: {'field': 'DATE', 'naive_rows': 0, 'samples': ()}
```

`naive_rows: 0`인데 "naive라서 timezone을 선언하라"는 자기모순이고, offending example도 비어 있다.
`registry.py:174-190`이 붙이는 retry는 "declare source_timezone for the naive source"인데, 사용자가
그대로 따르면 이번엔 `AVAILABLE_AT_INVALID`(`registry.py:206`)가 뜬다. **2단계 오진.**

이는 직전 리뷰 F-03 수정이 만든 **회귀**다. 수정 전에는 `AVAILABLE_AT_INVALID`가 바로 떴다.
PRD §2.6은 "실패한 requirement identity"와 "bounded offending example"을 요구한다.

### 3.5 R-05 — `registered()`가 catalog 전체를 역직렬화한다 (CONFIRMED)

`flow/strategy_extensions.py:313-328`이 `list_envelopes()`로 **catalog 전체**를 열거하고, 타입이
맞는 envelope마다 별도 `load_model`로 payload를 읽어 pydantic 검증한다. 타입 필터가 backend
query가 아니라 Python 루프에 있고 캐시도 없다.

PRD §2.8은 catalog가 성공·실패·diagnostic·user decision을 **누적**한다고 규정한다. 즉 이 비용은
프로젝트 수명에 걸쳐 단조 증가한다. daily simulation을 수백 번 돌린 연구자가 등록된 strategy 몇
개를 나열하려고 전체 catalog scan + 역직렬화를 지불한다. `daily.py::_hydrate_run_evidence`도 같은
형태다.

### 3.6 R-06 — `_failure` helper가 7개 flow에 중복 (CONFIRMED)

| helper | 위치 |
|---|---|
| `_failure` | `analysis.py:384`, `composition.py:405`, `constraints.py:317`, `extensions.py:229`, `monitoring.py:204`, `portfolio.py:85`, `strategy_extensions.py:858` |
| `_resolution_failure` / `_publish_errors` | `constraints.py:306`, `monitoring.py:193`, `research.py:328`, `strategy_extensions.py:808` |

전부 `sha256(f"{identity}:{stage_path}:{code}")[:24]` → `OperationError` → `publish_failure` →
`OperationOutcome` 시퀀스를 반복하고 각자 `retry_preconditions`를 하드코딩한다.

**구체적 비용은 이미 발생했다.** PRD §7.5가 균일해야 한다고 규정한 error contract가 사본마다
갈라지는 중이다 — 최신 사본(`strategy_extensions.py:858`)은 기존 사본에 없는 `context` 파라미터를
갖는다. 새 flow가 추가될 때마다 블록이 복제되며, 이번 리팩터에서만 2개가 늘었다.

### 3.7 R-07 — local artifact type이 package 소유 이름을 점유할 수 있다 (PLAUSIBLE)

`_artifact_models`(`strategy_extensions.py:599-638`)는 사용자 `STRATEGY_SPEC`이 선언한
`artifact_type` / `artifact_schema_version`을 그대로 `ArtifactContract`로 만든다. namespace 제약이
없다. `StrategyArtifactContractRegistry.extended`(`artifact_inputs.py:52-56`)는 정확히 같은
`(type, version)` 중복만 거부하므로, 오늘 프로젝트는 `strategy_result:v2`나 `mark_result:v1`을
자유롭게 점유할 수 있다.

훗날 qlibx가 해당 타입을 그 버전으로 출시하면 `built_in().extended(custom)`이
`duplicate Strategy artifact contract`를 던지고, 사용자에게는
`STRATEGY_EXTENSION_ARTIFACT_MODEL_INVALID`로 보인다 — package 업그레이드가 자기 namespace와
충돌했다는 정보도, migration 경로도 없는 메시지다.

`model.__module__` 검사(:606)와 중복 거부는 잘 되어 있어 **오늘 악용 가능하지는 않다.**
빠진 것은 PRD §12.1의 portable artifact contract에 package 소유 / project-local을 가르는
reserved prefix 규칙이다.

### 3.8 R-08 — determinism 검사가 artifact payload를 공유한다 (PLAUSIBLE)

`strategy_extensions.py:200-211`이 `first_view`와 `second_view`를 **같은**
`artifact_resolution.projections` 튜플로 만들고, `scoped.py:238`은 `projection.payload`를 참조로
반환한다.

`QlibxModel`은 `frozen=True`(`models.py:12`)지만 이는 속성 재대입만 막고 컨테이너 필드를 deep-freeze
하지 않는다. 사용자 artifact model이 `dict[str, float]`나 `list[float]` 필드를 선언하면(제약 없음)
Strategy는 공유 mutable 객체를 받는다. 첫 run에서 in-place 변경하면 두 번째 run이 그 변경을 보고,
변경이 idempotent하면 두 draft가 일치해 `STRATEGY_EXTENSION_NONDETERMINISTIC`이 뜨지 않는다 —
이 gate가 막으려던 바로 그 상황이다.

built-in payload는 전부 tuple이라 **현재는 도달 불가**이며 latent다.

### 3.9 R-09 — 형식과 미시 비효율 (CONFIRMED)

`flow/artifact_inputs.py:320-322`에 클래스 본문 안 빈 줄 3개가 남아 있다. 프로젝트 ruff `E`
선택이 `E303`을 포함하지 않아 잡히지 않았다.
`_duplicates`(:311-312)는 원소마다 `values.count(value)`를 호출해 O(n²)이다. 리스트가 작아 런타임
문제는 아니지만 resolution마다 3회 호출되며 `collections.Counter`가 더 짧고 명확하다.

---

## 4. 수정·리팩터 계획 (제안)

| # | Record | Subject | Findings | 선행 |
|---|---|---|---|---|
| C1 | 040 | `fix: decode sample subprocess output safely` | R-01 | — |
| C2 | 041 | `fix: execute only validated strategy source` | R-02, R-03 | C1 |
| C3 | 042 | `fix: report unparseable timestamps precisely` | R-04 | C1 |
| C4 | 043 | `refactor: share flow failure evidence` | R-06, R-09 | C2, C3 |
| C5 | 044 | `perf: query artifacts by type` | R-05 | C4 |
| C6 | 045 | `feat: reserve package artifact namespaces` | R-07, R-08 | C4 |

**순서 근거.** C1이 먼저여야 이후 커밋의 suite 결과를 신뢰할 수 있다(현재 red). C2와 C3는 서로
독립이며 C1 이후 아무 순서나 가능하다. C4는 error contract를 통합하므로 새 error code를 추가하는
C2·C3 이후여야 사본이 한 번만 수렴한다. C5·C6는 C4의 helper를 사용한다.

### C1 — `fix: decode sample subprocess output safely` (R-01)

4개 파일 전부 수정: `tests/test_strategy_extension_sample.py:13,64`,
`tests/test_public_constraint_sample.py`, `tests/test_public_daily_sample.py`, `tests/test_sample.py`.

```python
subprocess.run(
    [sys.executable, str(script), str(root)],
    check=False, cwd=root, capture_output=True, text=True,
    encoding="utf-8", errors="replace",                       # strict 디코드 제거
    env={**os.environ, "PYTHONIOENCODING": "utf-8"},          # child가 UTF-8로 쓰도록
)
```

두 가지를 함께 하는 이유: `PYTHONIOENCODING`은 child가 협조할 때 정확한 텍스트를 보장하고,
`errors="replace"`는 child가 협조하지 않는 경로(native crash, 3rd-party 출력)에서도 assertion이
`None`을 만나지 않게 한다.

공통 helper(`tests/support/subprocess_utils.py` 또는 기존 conftest)로 뽑아 4개 호출부가 같은
규약을 쓰게 하는 편이 낫다 — 다음에 sample 테스트가 추가될 때 또 복제되지 않는다.

**검증:** `pytest tests -q` → **207 passed**. 비-ASCII 경로에서 실행해야 의미가 있다.
**record 불필요** (test-only 변경, `AGENTS.md:100-101`).
→ 그렇다면 C1은 record 없이 `test:` 접두어를 쓰는 편이 관행에 맞다:
`test: decode sample subprocess output safely`.

### C2 — `fix: execute only validated strategy source` (R-02, R-03)

두 finding 모두 `local_modules.py`의 로딩 계약 문제이므로 한 커밋으로 묶는다.

**R-03 (`sys.modules`)** — `local_modules.py:36-46`:
```python
module = importlib.util.module_from_spec(module_spec)
sys.modules[name] = module
try:
    module_spec.loader.exec_module(module)
except BaseException:
    sys.modules.pop(name, None)
    raise
```
모듈 이름이 `f"{module_prefix}_{source_hash[:24]}"`라 내용이 같으면 이름도 같다. 등록 후에는
재로드 시 기존 항목을 덮어쓰게 되는데, 이는 의도된 동작(같은 내용 = 같은 모듈)이다. 다만
**같은 이름으로 두 번 exec하면 class 객체가 교체되어** 이전에 만든 인스턴스의 `isinstance` 검사가
깨질 수 있으므로, 이미 `sys.modules`에 있으면 재사용할지 재실행할지 명시적으로 결정하고 record에
남길 것. determinism 검사가 `create_strategy()`를 2회 호출하는 것과는 별개 문제다.

**R-02 (source drift)** — 가장 단순하고 확실한 수정은 **한 번만 읽는 것**이다:
```python
def load(self, relative, *, module_prefix=..., expected_source_hash: str | None = None):
    module_path = self._resolve_module_path(relative)
    payload = module_path.read_bytes()                 # 단일 read
    source_hash = hashlib.sha256(payload).hexdigest()
    if expected_source_hash is not None and source_hash != expected_source_hash:
        raise SourceDriftError(source_hash)            # exec 이전에 중단
    ...
```
그리고 `strategy_extensions.load_registered`가 `expected_source_hash=registration.source_hash`를
넘긴다. `registered_source_hash()`의 선행 호출은 남겨도 되지만(빠른 실패 + 명확한 진단 컨텍스트),
**실행 직전의 검사가 진실의 원천**이 되어야 한다.

`spec_from_file_location`은 경로에서 다시 읽으므로 엄밀한 원자성은 아니다. 최소한
"검사한 해시 = 실행 직전 해시"를 보장하고, 완전 원자성이 필요하면 `loader.exec_module` 대신
읽어둔 `payload`를 `compile()` 후 `exec`하는 방안을 record에 근거와 함께 남길 것.

**테스트:** 검사와 로드 사이에 파일을 바꾸는 회귀 테스트(§3.2 재현 코드가 그대로 골격),
그리고 `from __future__ import annotations` + 중첩 model을 쓰는 sample strategy 검증 테스트.

**검증:** `pytest tests -q` → 207 + 신규 2~3.

### C3 — `fix: report unparseable timestamps precisely` (R-04)

`data/timestamps.py`의 timezone 분기 **이전에** 파싱 실패를 판정한다:

```python
parsed = local.notna().sum()
if parsed == 0 and len(local):
    raise TimestampNormalizationError(
        "TIMESTAMP_VALUES_UNPARSEABLE",
        {"field": field, "row_count": int(len(local)),
         "samples": tuple(str(v) for v in values.head(3))},
    )
```

새 code를 만들지, 기존 `AVAILABLE_AT_INVALID`를 재사용할지는 선택이다. `normalize_timestamps`는
`available_at`과 `observation_time` 양쪽에 쓰이므로 `AVAILABLE_AT_INVALID`는 후자에 부적절하다 →
**신규 code 권장**, `registry.py`의 retry dict(`:174-182`)에 항목 추가.

부분 파싱 실패(`0 < parsed < len`)는 현행 유지: naive 판정 후 `registry.py:205`의
`AVAILABLE_AT_INVALID`가 잡는다. 다만 `registry.py:174-182`의 `retry[exc.code]` dict lookup은
등록되지 않은 code가 오면 `KeyError`를 던진다 — `.get(exc.code, <기본 retry>)`로 바꿀 것.

**테스트:** 완전 파싱 불가 컬럼 → 새 code, `samples`에 실제 값 포함, `registry_snapshot()` 비어 있음.

### C4 — `refactor: share flow failure evidence` (R-06, R-09)

`errors.py`에 공통 builder를 만든다 — 모든 flow가 이미 `qlibx.errors`를 import하므로 layer 규칙상
안전하다.

```python
def operation_failure(*, operation, stage_path, error_code, idempotency_identity,
                      retry_preconditions, context=None, requirement_id=None,
                      expected=None, commit_status=CommitStatus.NONE) -> OperationError
```

그리고 `publish_failure` → `OperationOutcome(FAILED, diagnostics, errors)` 시퀀스를 감싸는
flow-side helper 하나(예: `flow/failures.py`의 `publish_operation_failure(artifacts, error)`).
7개 `_failure`와 4개 `_resolution_failure`/`_publish_errors`를 여기로 수렴시킨다.

**주의:** 사본마다 `retry_preconditions` 문구와 `stage_path` 규약이 다르다. 통합하면서 **문구를
바꾸면 안 된다** — `tests/`에 stage_path/code를 assert하는 곳이 있고, 번들 skill의
`references/error-recovery.md`가 code 목록을 문서화한다. 문구 보존을 acceptance criterion으로 삼을 것.

R-09도 같은 커밋에서: `artifact_inputs.py:320-322` 빈 줄 정리, `_duplicates`를
`collections.Counter` 기반으로. 선택적으로 ruff `E` 선택에 `E303`을 추가할지 검토(다른 파일에
기존 위반이 없는지 먼저 확인).

**검증:** 기존 테스트가 **무변경 통과**해야 한다. 그것이 이 리팩터의 acceptance criterion이다.

### C5 — `perf: query artifacts by type` (R-05)

`LocalArtifactBackend`에 타입 필터를 받는 열거를 추가한다. 백엔드가 DuckDB이므로
(`evidence/local.py:756` 부근 스키마) `WHERE artifact_type = ?`를 push down할 수 있다.

```python
def list_envelopes(self, *, include_failure=False,
                   artifact_type: str | None = None) -> tuple[ArtifactEnvelope, ...]
```

`strategy_extensions.registered()`(:313)가 이를 사용하고, 가능하면 payload 역직렬화도 지연시킨다
(`RegisteredStrategyExtension`이 실제로 필요로 하는 필드만 우선 노출).
`daily.py::_hydrate_run_evidence`도 같은 필터를 쓸 수 있는지 확인 — 다만 그쪽은 여러 타입을
동시에 필요로 하므로 `artifact_types: tuple[str, ...]`가 나을 수 있다.

**검증:** 기존 테스트 무변경 통과. 가능하면 catalog에 N개 artifact를 넣고 `registered()`의
`load_model` 호출 횟수가 등록 수에 비례하고 catalog 크기에 비례하지 않음을 assert.

### C6 — `feat: reserve package artifact namespaces` (R-07, R-08)

**R-07:** `StrategyExtensionSpec.artifact_models`의 `artifact_type`에 project-local prefix를
강제하거나(예: `local.` / `project.`), 최소한 built-in 집합과 충돌하는 이름을 등록 시점에
거부한다. 후자가 덜 침습적이고 기존 sample을 깨지 않는다. PRD §12.1에 규칙을 한 줄 추가할 것.

**R-08:** `_strategy_view` 호출마다 projection을 새로 만들거나(권장), payload를 deep-copy한다.
`StrategyArtifactResolver.resolve`를 두 번 호출하면 artifact를 두 번 로드하므로,
`ArtifactInputProjection`만 `model_copy(deep=True)` 하는 편이 싸다.

**검증:** mutable 필드를 가진 artifact model을 in-place 변경하는 fixture strategy가
`STRATEGY_EXTENSION_NONDETERMINISTIC`으로 거부되는 테스트.

---

## 5. Process 의무

- **Implementation record:** 현재 최고 번호 **039**. 다음은 040. 형식은 `NNN-kebab-case-slug.md`,
  구조는 `## Intent` / `## Observable outcome` / `## Responsibilities and flow` /
  `## Alternatives and trade-offs` / `## Validation`(verbatim 명령 + `-> N passed in T s`) /
  `## Remaining limitations`. test-only·docs-only 변경에는 만들지 않는다(`AGENTS.md:100-101`).
- **Commit:** Conventional Commits, **subject line만**. body·trailer·`Co-Authored-By` 없음.
- **ExecPlan:** 이 작업도 data / extensions / flow / tests를 넘나드므로 `AGENTS.md:53-56` 기준
  ExecPlan 대상이다. `.agent/plans/active/`에 만들고 완료 후 `completed/`로 옮긴다.
  해당 디렉터리는 `.gitignore`되어 commit 대상이 아니다.
- **문서 동기화:** 새 error code는 `src/qlibx/resources/skills/qlibx/references/error-recovery.md`에
  추가한다. PRD §15.5 gap 표를 건드릴 경우 closure fixture 이름을 명시하고, 새 `UC-` ID를 만들지
  말고 `GAP-` 접두어를 쓴다(`tests/test_document_traceability.py`).

---

## 6. 범위 밖 미해결 항목

- `docs/code-review/2026-08-06-1500-current-scope-engine-review.md`의 **F-02**(동일 semantic role
  다중 후보를 알파벳순 선택)와 **F-08**(`AccountCommitRejected` raw 전파)은 여전히 대응
  implementation record가 없다. 번호가 이 문서의 R-xx 및 직전 문서의 F-xx와 겹치므로 인용 시
  출처를 명시할 것.
- `.agent/tmp/`가 `.gitignore`에 없어 `git add -A` 시 pytest scratch가 딸려 들어간다.
  별도 정리 대상.
- `daily.py`는 표적 추출 후에도 2,161줄이다. 직전 리뷰 F-12의 전체 분해는 사용자 결정으로
  범위에서 제외되었고 여전히 열려 있다.
