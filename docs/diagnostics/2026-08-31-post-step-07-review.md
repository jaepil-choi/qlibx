# Step 0–7 이후 재감사 — 앞 문서가 잡지 못한 10건

| | |
|---|---|
| **작성 시각** | 2026-08-31 KST (+09:00) |
| **기준 커밋** | `develop @ dd57e98a` (Step 7 머지 직후). 이 문서의 모든 행 번호는 그 커밋 기준이다 |
| **트리 상태** | `uv run pytest tests/ -q -m ""` → **1482 passed** (slow 14개 포함) · `uv run ruff check src/` → clean |
| **선행 문서** | `docs/diagnostics/2026-08-31-vqapr-structural-refactoring.md` (S1–S8, C1–C4) |
| **판정 기준** | `docs/vqapr-prd.md` → `docs/vqapr-architecture.md` → `docs/design/agent-first-surface.md` |
| **수정 여부** | **코드 수정 없음.** 진단과 등록 권고만 담는다 |

> **이 문서가 존재하는 이유.** 선행 문서는 `fix/029-one-door-into-internal @ 4078effa`에서 작성됐고,
> 그 뒤 Step 0–7이 실행되면서 S4·S5·S8과 C1·C2가 닫혔다. 여기 있는 10건은 **그 실행 결과를 다시 읽어서**
> 나온 것들이다. 세 종류가 섞여 있다 — (a) Step 7이 새로 만든 것, (b) `public.py`에서 이사만 하고
> 살아남은 기존 결함, (c) 선행 문서가 S1로 진단했지만 **사용자에게 도달하는 경로를 짚지 않은** 것.
> 각 항목이 어느 쪽인지 명시한다.

---

## 0. 총평 — 진단은 맞았고, 원인의 크기가 과소평가되어 있었다

선행 문서는 S1(두 protocol과 7개 bridge), S2(두 저장소), S6(110개 지연 import)을 각각 독립한
smell로 세웠다. 실행 6단계를 거치고 다시 재면, **셋은 독립이 아니다.** 하나의 덩어리가 셋 다를
혼자 만들어낸다.

```
project.py                1,036      <- CLI 여정에서 619줄 중 0줄 실행 (record 104의 측정)
simulation.py               547
materialization.py          161
venues.py                   206
_internal/catalog.py        233      <- S2의 "두 번째 저장소"
_internal/catalog_store.py  265         importer는 project.py 하나뿐
_internal/models/agent_first.py 499
_internal/*_bridge.py     1,573      <- S1의 번역층
                          ─────
                          4,520 lines = src/ 32,561줄의 13.9%
```

`grep`으로 확인한 각 모듈의 **비테스트 importer**:

```bash
grep -rn "_bridge\|_internal.catalog" --include=*.py src/ | grep import | grep -v "^src/vqapr/_internal/"
```

| 모듈 | src 안의 importer |
|---|---|
| `constraint_bridge` · `pit_bridge` · `registration_bridge` · `run_bridge` · `schedule_bridge` · `venue_bridge` | **`project.py` 하나** |
| `strategy_bridge` | `project.py` + **`extension/loading.py:337`** ← 유일하게 출하 경로에 있다 |
| `_internal/catalog.py` · `catalog_store.py` | **`project.py` 하나** |

따라서 **"bridge가 정말 필요한가"의 답은 하나를 빼고 아니다.** 6개는 제품이 한 줄도 실행하지 않는
모듈을 위해 존재하고, S2의 두 번째 저장소도 마찬가지다. `project.py`가 죽으면 S1의 6/7과 S2 전체와
S6의 지연 import 74개(111개 중)가 **같이** 죽는다. 선행 문서 §3의 "bridge를 작은 것부터 하나씩"보다
훨씬 싸다.

**단, 그 게이트는 owner만 열 수 있다.** `docs/design/agent-first-surface.md`의 `G008`이고,
record `104`가 그 문이 닫혀 있음을 확인했다. 이 문서는 그 결정을 요청하지 않는다 — 결정의 **대가를
숫자로 적어 둘 뿐**이다.

살아 있는 예외인 `strategy_bridge`가 왜 살아 있는지가 R5·R6이고, 그것이 S1의 사용자 가시 부분이다.

---

## 1. 즉시 고쳐야 하는 것 (correctness)

### R1 — 완주한 run이 roster 파일 하나 때문에 통째로 버려진다 (심각)

`src/vqapr/flow/orchestration.py:181`

```python
try:
    result = flow.run()
    if writer is not None:
        freeze_record(writer, result, frozen, as_loaded, roster_report(root_path, registry))
except BaseException:
    if writer is not None:
        writer.release()
    raise
```

`roster_report(...)`가 **인자로서 `try` 안에서 평가된다.** 그리고 `roster_report`는
`space.registered_instruments()`를 다시 읽으므로, pointer가 손상돼 있으면 typed
`workspace.instruments.unreadable`을 던진다 — 이는 추정이 아니라
`tests/flow/test_a_damaged_roster_pointer_is_not_no_roster.py:93`이 이미 단언하는 사실이다.

**재현 시나리오.** roster가 정상인 상태로 긴 run이 시작한다(`registered_roster` 성공, 모든 fill이
진짜 `kind`를 받는다). run이 도는 몇 분 사이 `.vqapr/instruments.json`이 손상된다 — 쓰기 중 크래시,
동시 `vqapr register`, 손편집. `flow.run()`은 **성공적으로 리턴한다.** 그 다음 `roster_report`가
던지고, `freeze_record`는 진입조차 못 하며, `writer.release()`가 락을 놓고 예외가 올라간다.

결과: rows는 append된 적이 없고, `record.json`이 없으니 `run_ids`가 이 run을 완료로 세지 않으며,
run id는 peer가 가져갈 수 있게 풀리고, CLI는 exit 1을 낸다. **몇 시간짜리 계산이 사라진다.**

**이것이 특히 나쁜 이유.** 같은 저장소가 이 시나리오를 이미 알고 있고, 막겠다고 적어 두었다.
`src/vqapr/cli/run.py:759-771`:

> *"**This runs after the run completed and its record is on disk.** ... Here it would be wrong:
> the tables can become unreadable in the minutes a real run takes, and letting that refusal escape
> would report exit 1 for a run that completed."*

그 방어는 `run()`이 **리턴한 뒤에** 돌기 때문에 절대 발동하지 않는다. 방어를 쓴 사람과 방어가 필요한
지점이 서로를 못 본 형태다.

**분류.** (b) 기존 결함. `public.py`에서 verbatim으로 이사했다 — Step 7의 diff는 이 줄에서
`_freeze_record` → `freeze_record` 이름만 바꿨다. Step 7이 만든 것이 아니지만, **주소가 바뀐 지금이
고치기 가장 싼 시점**이다.

**수정.** `roster_report`를 `try` 밖에서 평가하고, 실패를 `None`으로 흡수한 뒤 `freeze_record`에
넘긴다. 기록 블록의 `roster: null`이 "roster 없음"과 구별되지 않는 문제는 R3·R8과 함께 다뤄야
한다 — 최소한 완주한 run을 버리는 것보다는 낫다.

---

### R2 — `evidence/`가 `flow/`를 import한다 (층 역전)

`src/vqapr/evidence/records.py:15-17, 108`

```python
from vqapr.flow.run import FrozenRun
from vqapr.flow.run_records import RECORD_FIELDS, RunRecordWriter
from vqapr.flow.simulation import SimulationResult
```

```bash
grep -rn "from vqapr.flow" --include=*.py src/vqapr/evidence/ src/vqapr/analysis/ \
                                          src/vqapr/account/ src/vqapr/exchange/
```

→ **`evidence/records.py`가 유일한 결과다.** 척추 전체(evidence · analysis · account · exchange)에서
`flow`를 import하는 모듈은 이 하나뿐이고, 이번 Step 7이 만들었다.

**왜 문제인가.** 선행 문서 §2의 목표 구조는 `FLOW --> spine`만 그린다. 역방향 화살표는 없다.
그리고 이건 방향 취향의 문제가 아니라 **`pyproject.toml`이 import-linter를 거부한 근거를 무력화한다**:

> *"a misplaced type surfaces as a circular import, which Python reports without a tool."*

`flow.orchestration:31` → `evidence.records` → `flow.simulation`은 **패키지 수준에서 순환**이다.
지금 터지지 않는 유일한 이유는 `flow/__init__.py`와 `evidence/__init__.py`가 **둘 다 비어 있기
때문**이다. 둘 중 하나가 re-export를 하나라도 얻는 날 — 예를 들어 `evidence/__init__.py`에
`from vqapr.evidence.records import freeze_record`가, `flow/__init__.py`에
`from vqapr.flow.orchestration import run`이 들어가면 — `import vqapr.evidence`가
`ImportError: cannot import name 'freeze_record' from partially initialized module`로 죽는다.
Python이 이 순환을 지금 보고해 주지 않는 것은 안전해서가 아니라 **`__init__.py`가 비어 있어서**다.

**분류.** (a) Step 7이 새로 만들었다.

**목표.** `freeze_record`/`contract_report`는 `FrozenRun`과 `SimulationResult`를 소비한다 — 그것들의
소유자는 `flow/`다. `flow/records.py`로 옮기면 역전이 사라지고 Step 7의 나머지 성과는 그대로다.
`evidence/`에 두는 판단을 유지하려면, 두 함수가 `flow` 타입을 받지 않도록 입력을 평범한 매핑으로
낮추는 쪽이어야 한다. 지금 형태는 두 선택지 중 어느 쪽도 아니다.

---

### R3 — `except Exception`이 "workspace 손상"을 다시 "roster 없음"으로 붕괴시킨다

`src/vqapr/flow/roster.py:43` (그리고 `:120`)

```python
try:
    space = Workspace.open(root_path)
except Exception:
    return None
```

`Workspace.open`은 `_read()`를 부르고, `_read()`는 `.vqapr/workspace.yaml`을 decode한다. 그 파일이
손상되거나 절반만 쓰였으면 **typed `VqaprError`를 던진다.** 이 `except Exception`이 그것을 삼켜
`None`으로 만든다.

**왜 문제인가.** 바로 네 줄 아래 주석이 이 모듈의 존재 이유를 이렇게 적는다:

> *"OUTSIDE the guard above, deliberately. ... 'no roster' and 'a roster whose record is damaged'
> are different states, and only the first is ordinary."*

**pointer** 손상에 대해서는 그 원칙이 지켜졌다(C1 / `docs/issues/archive/042`가 닫은 것). **workspace 손상**에
대해서는 지켜지지 않았다. preflight와 `run()` 사이에 workspace.yaml이 손상되거나, 긴 run 중
`vqapr register`가 재작성하는 순간에 걸리면, `registry=None`으로 run이 계속되고 모든 fill이
`kind: None`을 기록한다 — KRX 형태 venue에서 ETF sleeve가 주식 세율로 과금되는
`docs/issues/archive/007`이 **다른 문으로** 되살아난다.

**분류.** (b) 기존 결함. `docs/issues/archive/042`가 pointer 쪽만 닫고 `Workspace.open` 쪽 guard는 넓은 채로
남겼다 — 그 이슈의 종결 문구가 *"only `Workspace.open` itself is guarded"*라고 정확히 적고 있다.
그 guard가 의도한 것은 "workspace가 **없는** 경우"인데 코드는 "workspace를 못 읽는 모든 경우"를
덮는다.

**수정.** guard를 workspace 부재로 좁힌다(또는 `VqaprError`를 제외한다). pointer 읽기에 이미 적용한
바로 그 처리다.

---

### R4 — `roster_report`가 pointer를 두 번째로 읽는다

`src/vqapr/flow/roster.py:127`

docstring은 이렇게 주장한다:

> *"The per-category counts come from the roster already loaded for this run rather than from a
> second read, so what is reported is what was bound to the venue, not what the file says now."*

**`by_kind`에 대해서만 참이다.** `digest`와 `tables`는 `space.registered_instruments()`를 다시 읽어서
가져온다 — `registered_roster`가 카테고리를 묶고 몇 분이 지난 뒤의 값이다.

**재현 시나리오.** 긴 run 도중에 `vqapr register <instruments>.yaml`이 들어온다. frozen record는
**새** roster의 digest를 적으면서, 그 옆의 fill들은 **옛** roster로 분류돼 있다. `source_digest` /
`declared_digest` 쌍이 다른 곳에서 드러내려고 존재하는 바로 그 불일치를, 이 블록이 조용히 만든다.

**분류.** (b) 기존 결함.

**수정.** 첫 번째 읽기에서 digest와 table 목록을 함께 들고 내려온다 — `registered_roster`가 그 둘을
같이 반환하면 두 번째 읽기 자체가 없어진다. R1의 수정과 같은 지점을 건드리므로 **한 커밋으로 묶는
것이 맞다.**

---

### R5 — `authoring.Constraint`와 `authoring.DataModel`은 loader가 거절한다

`src/vqapr/extension/loading.py:274` (`load_data_model`) · `:349` (`load_constraint`)
vs `:296` (`load_strategy_model`) · `:319` (`_adapt_authored_strategy`)

런타임 확인:

```bash
uv run python -c "
import vqapr.authoring as va
from vqapr.constraints.constraint import Constraint as EC
from vqapr.models.data_model import DataModel as ED
print(issubclass(va.Constraint, EC), issubclass(va.DataModel, ED))"
# False False
```

`load_strategy_model`에는 `_adapt_authored_strategy`가 있고, 그 docstring이 이유를 정확히 적는다:

> *"Refusing the authoring one here would mean a model that runs perfectly through
> `Project.simulate` cannot be registered by the CLI that exists to register it."*

**`load_constraint`와 `load_data_model`에는 그 대응물이 없다.** 두 함수는
`component.load.wrong_type`을 던지고, fix 문구로 *"make the registered object a subclass of
`vqapr.constraints.constraint.Constraint`"* 를 준다.

**재현 시나리오.** 저자가 strategy scaffold가 가르쳐 준 관용구 — `from vqapr import authoring as va`
— 를 constraint에도 그대로 적용해 `class MyCap(va.Constraint)`를 쓴다. 등록이 거절되고, 거절 메시지는
**프레임워크가 방금 쓰라고 emit한 모듈이 틀렸다고 말한다.**

**왜 이것이 새로운 항목인가.** 선행 문서 §S1은 "세 확장점이 각각 두 번 정의되어 있다"까지만 갔다.
그것은 내부 중복의 진술이다. 여기서 확인된 것은 **출하된 loader가 세 확장점 중 하나에 대해서만
agent-first 계약을 받아들인다**는 것 — S1이 사용자에게 도달하는 지점이고, 3단계 계획이 bridge를
"작은 것부터" 지우는 순서를 잡을 때 반드시 알아야 하는 비대칭이다.

**분류.** (c) 선행 문서가 진단했지만 경로를 짚지 않은 것.

---

### R6 — scaffold 3개가 protocol 2개를 emit한다

`src/vqapr/extension/scaffold.py`

| 명령 | emit되는 import | 계약 |
|---|---|---|
| `vqapr new strategy` | `:21` `from vqapr import authoring as va` → `class X(va.StrategyModel)` | **agent-first** |
| `vqapr new datamodel` | `:65` `from vqapr.public import DataModel, DataRequirement, ...` | **engine** |
| `vqapr new constraint` | `:174` `from vqapr.public import (..., Constraint, ...)` | **engine** |

**왜 문제인가.** `docs/design/agent-first-surface.md`가 record `104`를 통해 판정한 규칙이 있다:

> *"an emitted import is the most-copied artifact in the package; it must name the surface that will
> still exist after this ruling."*

**scaffold 3개가 표면 2개를 지명하면 그 규칙을 동시에 만족시킬 수 없다.** 한 프로젝트에 세 component를
scaffold한 저자는 import 관용구 두 벌과 base class 계열 두 벌을 갖게 되고, 어느 쪽이 현재인지 말해 주는
문장은 어디에도 없다. R5와 합치면, strategy scaffold에서 일반화한 독자는 constraint에서 거절을 받는다.

**분류.** (c). 3단계(protocol 통합)의 완료 조건에 *"scaffold 3개가 같은 표면을 emit한다"* 가 들어가야
한다.

---

## 2. 게이트와 계약의 문제

### R7 — facade tripwire가 위반 7건을 면제 목록에 넣어 두었고, 만료일이 없다

`tests/boundaries/test_the_facade_is_not_reached_up_to.py:28-46`

`PERMITTED` 12개(작업 중인 Step 8에서 11개로 내려가는 중)의 내역:

| 분류 | 수 | 판정 |
|---|---|---|
| CLI verb (`check`, `register`, `run`) | 3 | **정당.** CLI는 facade가 존재하는 이유인 제품 표면이다 |
| 출하 sample (`agent/sample/*`) | 2 | **정당.** 사용자가 쓰는 방식대로 쓴 코드다 |
| `_internal/*_bridge.py` | 6 | **이것이 위반이다** |
| `project.py` | 1 | **이것이 위반이다** |

§0의 측정과 합치면: facade 규칙이 **1,573줄의 번역 코드와, 제품 여정에서 0줄 실행되는 모듈 하나를
위해 유예되어 있다.**

같은 파일의 docstring이 궤적을 12 → 10 → 6으로 적어 두었다. **6에서 멈춘다** — 나머지 4개 bridge는
*"reachable only from frozen `project.py` and cannot move before `G008`"*. 즉 이 목록은 `project.py`
삭제 게이트가 열리기 전에는 절대 비지 않는다.

**목표.** 면제를 없애자는 것이 아니라, **면제에 만료 조건을 붙이자**는 것이다. 지금은 `PERMITTED`가
"이 파일들은 facade를 import해도 된다"고 읽히고, 그 이유(= `project.py`가 아직 살아 있다)는 주석에만
있다. 6개 bridge 항목을 `G008` 하나에 명시적으로 묶으면 — 게이트가 열리는 날 이 목록이 자동으로
틀려지고, 그때 지워야 할 것이 무엇인지 테스트가 말해 준다.

---

### R8 — Step 7의 인수 조건(250줄)이 그것을 재는 테스트에서 420으로 완화됐다

`tests/boundaries/test_the_facade_does_not_orchestrate.py:27`

goal `G008`의 인수 조건:

> *"ACCEPTANCE: `public.py` 775 -> **under 250 lines** with `__all__` UNCHANGED"*

실측:

```bash
wc -l src/vqapr/public.py      # 351
grep -n "MAX_LINES =" tests/boundaries/test_the_facade_does_not_orchestrate.py   # 420
```

`__all__`은 약속대로 **완전히 동일하다**(132개, 추가·삭제 0 — AST로 확인). 그것은 지켜졌다.
줄 수는 지켜지지 않았고, 그것을 고정해야 할 테스트가 현재값보다 **69줄 위**, 목표보다 **170줄 위**에
상한을 놓았다.

**왜 문제인가.** 선행 문서 §S8의 판정 문장이 그대로 적용된다 — *"설정된 게이트가 열려 있으면 게이트가
아니다."* 지금 상태에서는 다음 단계가 documented surface에 69줄을 아무거나 더해도 ratchet이 green이다.

이 파일의 다른 절반인 `MAX_BODY_STATEMENTS = 6`은 **제대로 작동한다** — 함수 몸통이 다시 자라는 것을
실제로 막는다. 문제는 줄 수 상한 하나다.

**수정.** 둘 중 하나. (a) `MAX_LINES`를 실측값 351로 내려 ratchet으로 만든다. (b) 250이라는 인수
조건을 record `111`에서 **명시적으로 수정**한다 — 앞 문서의 §2 목표 1번이 erratum으로 뒤집힌 것과
같은 방식으로. 지금처럼 테스트가 조용히 완화하는 형태만 피하면 된다.

---

## 3. 사소하지만 적어 둘 것

### R9 — `contract` 블록이 constraint id 키스페이스에 스칼라를 섞는다

`src/vqapr/evidence/records.py:149`

```python
for constraint_id, counts in sorted(findings.items()):
    report[constraint_id] = entry       # {"held": .., "checked": .., "ok": ..}
report["accepted_intents"] = accepted   # int
```

**재현 시나리오.** `constraint_id`가 `"accepted_intents"`인 constraint를 등록하면, 그 증거 항목이
149행에서 정수로 덮인다. 이 블록을 순회하는 reader — `vqapr show`의 렌더, 또는
`record["contract"][cid]["held"]`를 읽는 연구 스크립트 — 는 `TypeError: 'int' object is not
subscriptable`을 받고, 그 constraint의 증거는 **아무 말 없이 사라진다.** constraint id는 저자가 정하는
자유 문자열이고 이 이름을 예약하는 코드는 없다.

가능성은 낮다. 하지만 이 블록의 존재 이유가 *"a declaration checked zero times is not a declaration
that held"* — 즉 **증거가 조용히 사라지는 것을 막는 것**이므로, 그 자신이 조용히 사라지는 경로를
갖는 것은 어울리지 않는다.

**수정.** 카운트를 별도 키 아래로 내리거나, 등록 시점에 이 이름을 예약한다.

---

### R10 — `_registered_roster_for_report` 래퍼가 존재 이유를 잃었다

`src/vqapr/cli/run.py:803`

이 래퍼는 **private한 facade 이름(`_registered_roster`)을 CLI의 import 블록에서 감추기 위해** 있었다.
Step 7이 그 함수를 소유 layer에서 public으로 만들었으므로, 지금은 한 줄 호출을 감싼 함수 지역 import일
뿐이다.

그리고 그 결과 `_roster_envelope` 한 함수 안에서 형제 호출 둘이 **서로 다른 문**으로 간다:

```python
report = roster_report(project_root, _registered_roster_for_report(project_root))
#        ^ vqapr.public 경유                ^ vqapr.flow.roster 경유
```

**수정.** `_roster_envelope` 상단에 `from vqapr.flow.roster import registered_roster, roster_report`
하나를 두고 래퍼를 지운다. 이 모듈이 S6 ratchet에 기여하는 지연 import 4개 중 2개가 같이 없어진다.

---

## 4. 등록 권고

| # | 성격 | 권고 |
|---|---|---|
| **R1** | correctness, 심각 | **`docs/issues/`로 승격.** 완주한 run이 사라지는 결함이고 재현 경로가 명확하다. `docs/issues/archive/042`의 형제 |
| **R3** | correctness | **`docs/issues/archive/042`를 재개**하거나 그 후속 이슈로 등록. 042가 닫은 것은 pointer 문 하나뿐이다 |
| **R4** | correctness | R1과 같은 지점. **한 커밋으로 묶는다** |
| **R2** | 구조 | Step 7의 후속 수정. 별도 이슈 없이 `flow/records.py` 이동으로 닫는다 |
| **R5 · R6** | 구조, 사용자 가시 | **3단계(protocol 통합)의 완료 조건에 편입.** 별도 이슈보다 계획 수정이 맞다 |
| **R7** | 게이트 | `PERMITTED` 항목을 `G008`에 명시적으로 묶는다. 코드 변경 없이 테스트 주석과 구조만 |
| **R8** | 게이트 | `MAX_LINES` 351로 하향, 또는 record `111`에서 250 인수 조건을 명시 수정 |
| **R9 · R10** | 사소 | 다음에 해당 파일을 건드리는 단계에 편승 |

**선행 문서에 대한 수정 요청은 없다.** §1의 S1–S8 진단은 유효하고, §3의 단계 순서도 유효하다.
다만 §3의 3단계 완료 조건에 R5·R6가, §5의 진척 지표에 §0의 "frozen island 총량"이 들어가는 편이
낫다 — bridge 1,573줄만 세면 같은 원인이 만든 나머지 2,947줄이 지표에 잡히지 않는다.

---

## 부록 — 이 문서가 근거로 쓴 명령

```bash
# 기준 커밋과 게이트
git rev-parse --short HEAD                       # dd57e98a
uv run ruff check src/                           # clean
PYTHONUTF8=1 uv run pytest tests/ -q -m ""       # 1482 passed

# frozen island의 실제 소비자 (§0)
grep -rn "_bridge\|_internal.catalog" --include=*.py src/ | grep import | grep -v "^src/vqapr/_internal/"

# 척추가 flow를 import하는 유일한 지점 (R2)
grep -rn "from vqapr.flow" --include=*.py src/vqapr/evidence/ src/vqapr/analysis/ \
                                          src/vqapr/account/ src/vqapr/exchange/

# authoring 계약이 engine 계약의 subclass가 아님 (R5)
uv run python -c "
import vqapr.authoring as va
from vqapr.constraints.constraint import Constraint as EC
from vqapr.models.data_model import DataModel as ED
print(issubclass(va.Constraint, EC), issubclass(va.DataModel, ED))"

# scaffold가 emit하는 표면 (R6)
grep -n "from vqapr import authoring as va\|from vqapr.public import" src/vqapr/extension/scaffold.py

# 인수 조건 대 테스트 상한 (R8)
wc -l src/vqapr/public.py
grep -n "MAX_LINES =" tests/boundaries/test_the_facade_does_not_orchestrate.py
```
