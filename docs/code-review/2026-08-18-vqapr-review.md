# vqapr code review — 2026-08-18

| | |
|---|---|
| **발견 시각** | 2026-08-18 13:59 KST (+09:00) |
| **리뷰 대상** | `src/vqapr/` 전체 (130 modules, 11,959 lines) |
| **브랜치 / HEAD** | `gjc/implement-operation-agendas` @ `67d363b` — *Produce recorder rows from a real run* |
| **작업 트리 상태** | `M src/vqapr/public.py`, `M tests/boundaries/test_public.py`, `?? showcases/show_006_ensemble_netting/` (리뷰 중 다른 agent가 동시 편집) |
| **테스트 기준선** | `uv run pytest -q` → **334 passed in 19.10s** |
| **판정 기준** | `docs/vqapr-prd.md` (canonical authority) 우선, `docs/vqapr-architecture.md` 참고, clean architecture / clean code |
| **수정 여부** | **코드 수정 없음.** 이 문서는 진단만 담는다. |

> **⚠ Staleness 주의.** 아래 모든 항목은 위 HEAD 기준이다. 현재 작업 중인 agent가 이후 커밋에서
> 고쳤을 수 있으므로, 착수 전에 각 항목의 **재현 절차 / 확인 명령**을 먼저 돌려 아직 살아 있는지
> 확인할 것. 이미 고쳐졌다면 해당 항목을 지우지 말고 `RESOLVED @ <sha>`로 표시해 이력을 남긴다.

---

## 0. 총평

**핵심 execution spine — PIT 경계, `intended ≠ requested ≠ dealt ≠ committed`, frozen run identity,
account authority, exact-rational optimizer — 은 설계 의도대로 구현되어 있다.** 타입 경계마다
`__post_init__` 불변식이 있고, `AccountState`/`AcceptedRunState`가 immutable root로 유지되며,
observation query의 rows-lookback이 (instrument × field)별로 SQL window function까지 내려간다.
PRD §2.4의 네 단계 구분과 §3.2의 PIT 술어는 실제로 코드가 지키고 있다.

문제는 세 방향에 몰려 있다.

1. **Execution time에 이미 알고 있는 사실(거래정지)을 order planning이 못 본다** → PRD가 "같은
   등급이 아니다"라고 못 박은 두 실패가 하나로 붕괴한다. (§1 EB-1)
2. **확장점 계약이 문서와 코드에서 어긋난다** → PRD §12.3의 "built-in만 쓸 수 있는 내부 capability가
   존재하지 않는다"가 성립하지 않는다. (§1 EB-3, §2 PB-1)
3. **패키지 표면의 절반이 0바이트 placeholder다** → CLI, agent surface, conformance suite,
   transforms, analysis가 전부 빈 파일이고 그중 일부는 이미 다른 곳에 살아 있는 모듈의 중복이다.
   (§3)

334개 테스트가 전부 통과한다는 점이 중요하다. **아래 evident bug들은 "깨진 빌드"가 아니라 "커버되지
않은 경로"다.** 각 항목에 재현 스크립트를 붙인 이유가 그것이다.

### 우선순위 요약

| # | 분류 | 위치 | 한 줄 |
|---|---|---|---|
| EB-1 | evident bug | `orders/planning.py:75` | 정지 종목 매도대금으로 매수를 짜서 batch 전체가 죽는다 |
| EB-2 | evident bug | `constraints/builtin/single_name_cap.py:127` | 실제 위반인데 `excess=0`으로 보고한다 |
| EB-3 | evident bug (요구사항 위반) | `extension/loading.py:161` | local Exchange를 whitelist로 거부한다 |
| EB-4 | evident bug | `pyproject.toml:21` | console script가 빈 모듈을 가리킨다 |
| EB-5 | evident bug (성능) | `data/store.py:26` | 조회마다 원천 parquet 전체를 다시 해싱한다 |
| EB-6 | evident bug (성능) | `exchange/conventions.py:148` | callback마다 run end까지 날짜를 전부 훑는다 |
| PB-1 | plausible bug | `flow/preflight.py:132` | Protocol에 없는 `exchange.listings`를 읽는다 |
| PB-2 | plausible bug | `flow/materialize.py` `materialize()` | component 경로를 CWD 기준으로 푼다 |
| PB-3 | plausible bug (동시성) | `workspace.py:357` | lock 없는 read-modify-write, 등록이 조용히 사라진다 |
| MS-1 | missing scope | `models/contexts.py:23` | Strategy가 actual state 이력을 볼 수 없다 (UC-ACCOUNT-HISTORY-001) |
| MS-2 | plausible bug (요구사항) | `constraints/builtin/single_name_cap.py:120` | cap만 걸어도 조용히 long-only가 된다 |
| OS-1 | obsolete/stale | `src/vqapr/**` | 0바이트 모듈 ~40개, 일부는 살아 있는 모듈의 중복 |
| OS-2 | obsolete/stale | `pyproject.toml:11` | 미사용 runtime dep 4개 (cvxpy 포함) |
| OS-3 | obsolete/stale | `flow/run_state.py:372` | 테스트만 부르는 production API 4개 |
| RF-1 | refactor needed | `workspace.py:702` | 8-tuple을 위치 인자로 16곳에 흘린다 |
| RF-2 | refactor needed | `flow/simulation.py:467` | `_execute_due` 250줄 + 죽은 필터 |

---

## 1. Evident bug — 재현했고, 고쳐야 한다

### EB-1. 정지 종목의 매도대금을 현금으로 계산해 batch 전체를 죽인다 🔴 최우선

**위치** — [`src/vqapr/orders/planning.py:74-80`](../../src/vqapr/orders/planning.py) (`_apply_venue_rules`),
[`src/vqapr/flow/simulation.py:510-512`](../../src/vqapr/flow/simulation.py) (`_execute_due`)

**무엇이 잘못됐나.** `_execute_due`가 execution snapshot에서 `prices`를 만들 때 **`is_tradable`을
버린다.**

```python
# flow/simulation.py:510-512
prices = {row.instrument: row.price for row in snapshot.rows if row.price is not None}
selected_prices = {
    instrument: price for instrument, price in prices.items() if price is not None
}   # ← 위에서 이미 거른 조건을 그대로 다시 거른다 (RF-2 참고)
```

`plan_orders`에는 tradability가 아예 전달되지 않으므로, `_apply_venue_rules`의 현금 누적 루프가
**정지 종목의 매도대금까지 `available`에 더한다.**

```python
# orders/planning.py:75-80
for instrument_id in ordered:
    delta = _delta(instrument_id)
    if delta >= 0 or instrument_id not in prices:
        continue
    notional = abs(delta) * prices[instrument_id]
    available += notional - rules.charge(Side.SELL, notional).total   # ← 정지 종목도 포함
```

그 결과 매수가 과대 계획되고, Exchange가 정지 종목을 `NONTRADABLE` zero-dealt로 돌려준 뒤
`Account.prepare_fill`이 `"fill batch would make cash negative"`로 **결정 전체를 거부**한다.
이것은 `_due_boundary`에서 PRE_COMMIT `SimulationFailure`가 되어 **run 전체가 중단된다.**

**재현 (실행 확인함).**

```bash
uv run python - <<'PY'
from decimal import Decimal as D
from datetime import datetime, UTC
from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.exchange.execution_table import ExactExecutionRow, ExactExecutionSnapshot
from vqapr.exchange.venues.krx import KrxExchange
from vqapr.orders.planning import plan_orders
from vqapr.portfolio.budgets import Budget, PortfolioDirection

t = datetime(2024, 1, 3, 6, 30, tzinfo=UTC)
before = AccountSnapshot(version=0, cash=D("0"), positions={"A": D("100")})
snap = ExactExecutionSnapshot(t, (
    ExactExecutionRow(t, "A", False, D("1000")),   # 정지, 그러나 가격은 있다
    ExactExecutionRow(t, "B", True,  D("1000")),
), (), (), ())
prices = {r.instrument: r.price for r in snap.rows if r.price is not None}   # Flow와 동일
nav = before.cash + before.positions["A"] * prices["A"]
ex = KrxExchange(["A", "B"])
orders = plan_orders(account=before, execution_time_nav=nav, prices=prices,
                     weight_targets={"A": D("0"), "B": D("0.99")}, quantity_targets={},
                     cash_target=D("0.01"),
                     budget=Budget(PortfolioDirection.LONG_ONLY, D(0), D(1), D(0), D(1)),
                     rules=ex.rules.at(t))
fills = ex.execute(orders, before, snap)
Account(mode=AccountMode.LONG_ONLY).prepare_fill(AccountState(before), fills, expected_version=0)
PY
```

```text
NAV 100000
  order A delta -100
  order B delta 99
  fill A dealt 0  reason nontradable  cash 0
  fill B dealt 99 reason None         cash -99029.7000
ABORTED: ValueError fill batch would make cash negative
```

**어느 요구사항을 깨나.**

- **PRD §14.3 / `UC-TRADABILITY-002`** — *"판단 이후 발생한 거래정지가 그 종목의 체결 수량 0과
  사유로 남고 같은 결정의 나머지 종목 체결을 막지 않는다. 반대로 `UC-FILL-001`의 체결 가격 부재는
  그 결정의 주문 집합 전체를 mutation 전에 중단시킨다. **두 실패는 같은 등급이 아니다.**"*
  현재 구현은 두 실패를 같은 등급(=batch 전체 중단)으로 붕괴시킨다.
- **PRD §14.3** — *"어느 종목이 왜 줄었거나 체결되지 않았는지가 결과에서 확인된다."*
- **architecture §11.6 ④** — *"A 매도 실패(정지) → 현금 3,000만원 부족 → C 부분체결, D·E 미체결"* —
  문서는 **매수 clipping + 인과 진단**을 명시하는데 코드는 run을 죽인다.

**왜 테스트가 못 잡았나.** `docs/implementations/013`의 showcase는 정지 종목이 **보유 유지(hold)**
이거나 현금이 넉넉한 경우만 돌린다. "정지된 종목을 팔아서 다른 걸 사는" 리밸런싱 경로가 없다.

**고칠 때 고려할 것.**

- `plan_orders`가 tradability를 알아야 한다. 다만 이것을 `prices`에서 종목을 빼는 식으로 처리하면
  안 된다 — `missing_held` 검사가 걸려 또 다른 이유로 batch가 죽는다. **가격은 있으나 팔 수 없는
  상태**를 별도 입력(예: `nontradable: frozenset[str]`)으로 전달해, 매도대금 누적에서만 제외하고
  NAV 계산과 marking에는 그대로 쓰는 것이 architecture §11.6의 *"정지 종목의 평가는 문제가 되지
  않는다"*와 맞는다.
- 그 결과 줄어든 매수는 이미 있는 clipping 경로를 타므로 `OrderRequest`에 사유가 남는다.

---

### EB-2. `SingleNameCap`이 실제 위반을 `excess = 0`으로 보고한다 🔴

**위치** — [`src/vqapr/constraints/builtin/single_name_cap.py:127-139`](../../src/vqapr/constraints/builtin/single_name_cap.py) (`_worst`)

**무엇이 잘못됐나.** `_worst()`는 **가장 큰 weight**를 추적하는데, `offenders`는 **각자의 ceiling**과
비교해 따로 모은다. 벤치마크로 상향된 ceiling을 가진 대형주가 최대 weight일 때, 진짜 위반한 소형주는
`measured`/`bound`/`excess` 어디에도 나타나지 않는다.

```python
for instrument, weight in sorted(weights.items()):
    ceiling = bounds.upper.get(instrument, self._cap)
    if weight > ceiling:
        offenders.append(instrument)      # ← 위반 판정은 종목별 ceiling 기준
    if weight > measured:
        measured, bound = weight, ceiling # ← 보고 값은 "최대 weight" 기준
return measured, bound, tuple(offenders)
```

**재현 (실행 확인함).**

```bash
uv run python - <<'PY'
from decimal import Decimal as D
from vqapr.constraints.builtin.single_name_cap import SingleNameCap
from vqapr.constraints.constraint import ConstraintBounds
from vqapr.account.snapshot import AccountSnapshot
from vqapr.valuation.marks import Mark, MarkBatch
cap = SingleNameCap(cap="0.05", benchmark_dataset_id="bm", tolerance="0.01")
bounds = ConstraintBounds({"A": D(0), "B": D(0)}, {"A": D("0.30"), "B": D("0.05")})
acct = AccountSnapshot(0, D("0.64"), {"A": D("0.28"), "B": D("0.08")})
marks = MarkBatch((Mark("A", D("0.28"), D(1), D("0.28")),
                   Mark("B", D("0.08"), D(1), D("0.08"))), D("0.36"))
f = cap.evaluate(None, acct, marks, bounds)
print(f.passed, f.measured, f.bound, f.excess, dict(f.input_lineage)["offenders"])
PY
```

```text
passed: False   measured: 0.28   bound: 0.30   excess: 0   offenders: ('B',)
# 실제로는 B가 0.08 vs ceiling 0.05 → excess 0.03 이어야 한다
```

**어느 요구사항을 깨나.** PRD §14.4 — *"constraint 선언이 정체를 유지해 **어느 constraint가 얼마나
초과했는지**가 결과에 남고"*. `UC-EXEC-003`의 monitoring finding과 `UC-CONSTRAINT-ADJUST-001`의
사후 위반 진단이 모두 이 값을 읽는다. `passed=False, excess=0`은 downstream이 해석할 수 없다.

**부수 문제 (같은 파일).**

- `evaluate()`의 `abs(mark.value) / nav` — short −6%가 cap 6% 위반으로 잡힌다. `NoShort`가 담당해야
  할 판정과 섞인다. (MS-2 참고)
- `nav <= 0`이면 `weights = {}`가 되어 **조용히 `passed=True`**. 명시적 실패가 맞다 (PRD §10.2).
- `_benchmark()`가 `batch.rows`를 순회하며 `latest[instrument] = weight`로 덮어쓴다. `RowsLookback(1)`
  이라 실제로는 1행이지만, "latest"라는 이름이 보장하는 순서 근거가 코드에 없다.

**고칠 때.** `_worst`는 `weight - ceiling`의 최대값을 추적해야 한다. 위반이 없을 때만 "가장 큰
weight"를 보고하는 것이 자연스럽다.

---

### EB-3. Local Exchange를 whitelist로 거부한다 — `UC-EXTENSION-003` 정면 위반 🔴

**위치** — [`src/vqapr/extension/loading.py:161-195`](../../src/vqapr/extension/loading.py)

```python
SHIPPED_EXECUTION_PROFILES: tuple[type, ...] = (AcademicExchange, KrxExchange)

def load_exchange(ref, *, project_root=None) -> Exchange:
    profile = next((b for b in SHIPPED_EXECUTION_PROFILES if isinstance(exchange, b)), None)
    if profile is None:
        raise _failure(..., "registered Exchange object must be one of the shipped profiles: ...")
    if type(exchange).execute is not profile.execute:
        raise _failure(..., f"{profile.__name__} subclasses must retain {profile.__name__}.execute()")
```

**무엇이 잘못됐나.** 사용자가 자기 venue의 체결 규칙을 표현하려면 `execute`를 바꿔야 하는데,
그 순간 등록이 거부된다. built-in을 상속하지 않으면 애초에 통과하지 못한다.

**어느 요구사항을 깨나.**

- **PRD §12.3** — *"**built-in과 project-local extension은 같은 등록·검증 경로를 통과한다.**
  package가 자기 built-in에만 허용하는 내부 접근이 있으면 built-in은 §2.7이 약속한 executable
  example이 아니라 재현할 수 없는 예시가 된다."*
- **PRD §14.4 / `UC-EXTENSION-003`** — *"local Exchange와 local Constraint가 built-in과 같은 경로로
  등록되고, frozen run input에서 built-in과 구분되지 않는다. **built-in만 쓸 수 있는 내부
  capability가 존재하지 않는다.**"*
- **architecture §10.2** — *"`academic`과 `krx`는 `ComponentRef`로 주입되고 preflight는 그것이
  내장인지 사용자 것인지 **구분하지 않는다.**"*

**docstring이 이유를 말하지만 그 이유가 요구사항을 이긴다고 볼 근거가 없다.** 주석은 *"realism
claim이 unverified가 된다"*고 하는데, PRD가 요구하는 해법은 whitelist가 아니라 **conformance
suite로 §6.3 불변식을 deterministic하게 판정하는 것**이다 (PRD §12.3 마지막 문단:
*"package는 그것이 §6.3의 불변식을 지키는지 deterministic하게 판정한다"*).

그리고 그 suite가 있어야 할 자리 — **`src/vqapr/testing/conformance/exchange.py` — 는 0바이트다**
(OS-1). 즉 whitelist는 미구현 conformance suite의 임시 대체물이고, 그 임시 대체물이 요구사항을
어기고 있다.

**고칠 때.** `testing/conformance/exchange.py`를 구현하고 whitelist를 그것으로 대체한다. 그 전까지는
최소한 `Constraint`/`StrategyModel`과 같은 `isinstance(x, Exchange-Protocol)` 수준 검사 +
`ExchangeRulesView` 노출 검사로 낮추는 것이 요구사항에 가깝다.

---

### EB-4. 배포된 console script가 빈 모듈을 가리킨다 🔴

**위치** — [`pyproject.toml:21`](../../pyproject.toml)

```toml
[project.scripts]
vqapr = "vqapr.cli:main"
```

`src/vqapr/cli/__init__.py`, `main.py`, `new.py`, `check.py`, `register.py`, `run.py`, `data.py`,
`report.py`, `agent.py` — **9개 전부 0바이트다.**

**확인.**

```bash
find src/vqapr/cli -name "*.py" -size -1c | wc -l   # → 9
```

`uv add vqapr` 후 `vqapr --help`는 `AttributeError: module 'vqapr.cli' has no attribute 'main'`로
즉시 죽는다.

**어느 요구사항을 깨나.**

- **`UC-FACADE-001`** — *"installed documentation, bundled agent skill, public API/CLI만 사용해
  … 수행할 수 있다."*
- **`UC-ONBOARD-001`**, **PRD §11.2** — *"Skill entrypoint — **normative product contract**"*
- **architecture §10.2** — `vqapr new` / `vqapr check` / `vqapr register` 흐름 전체

**고칠 때.** CLI를 구현할 계획이 아직 없다면 **`[project.scripts]` 항목을 지우는 것이 먼저다.**
지금 상태는 "있다고 선언했는데 없는" 것이라 PRD §10.2의 명시적 실패 원칙과도 어긋난다.

---

### EB-5. 관측 조회마다 원천 parquet 전체를 다시 해싱한다 (성능) 🟠

**위치** — [`src/vqapr/data/store.py:26-46`](../../src/vqapr/data/store.py)

```python
def _physical_digest(path: Path) -> str:
    files = (path,) if path.is_file() else tuple(sorted(path.glob("**/*.parquet")))
    ...
    for file_path in files:
        with file_path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)     # ← 전체 바이트를 매 query마다
```

`DuckDbObservationStore.query()`가 매번 호출한다. `__slots__ = ("__catalog",)` — **캐시가 없다.**

**비용.** 한 occurrence당: strategy requirement N개 + constraint requirement M개 + valuation mark
1회 + monitoring 1회. `UC-SCALE-001`(3,000종목 × 15년, multi-GB parquet) 기준 occurrence 약 3,900개
× 3~5회 = **원천 전체를 1만 회 이상 재해싱**한다.

**논리적으로도 불필요하다.** digest는 `AccessRecord.source_digest`를 채우는 데만 쓰이고, frozen run
동안 원천 바이트는 상수여야 한다 (`FrozenRun.physical_source_guarantee`가 명시적으로 *"physical
source bytes are not [frozen]"*이라고 하지만, 그렇다면 run 중 바뀌는 것을 **탐지**해야지 매번 재계산할
이유가 되지는 않는다). `(source_id, path, mtime, size)`별 memoization으로 충분하다.

---

### EB-6. `select_target`이 callback마다 run end까지 날짜를 전부 훑는다 (성능) 🟠

**위치** — [`src/vqapr/exchange/conventions.py:146-151`](../../src/vqapr/exchange/conventions.py)

```python
first_date = decision_date
last_date = decision_date if self.selector is FillSelector.SAME_DAY else final_date
day = first_date
while day <= last_date:
    self._local_target(day)      # ZoneInfo 생성 + astimezone 왕복 2회
    day += timedelta(days=1)
```

`NEXT_ELIGIBLE`에서 `last_date`는 **run end**다. 15년 daily run이면 첫 callback이 ~5,475일,
둘째가 ~5,474일 … 누적 **약 1,500만 회**의 `_local_target` 호출.

**이 루프가 답하는 질문은 decision date에 의존하지 않는다** — "이 horizon 안에 존재하지 않거나
모호한 local target time이 있는가"는 frozen `start`/`end`에 대해 **preflight에서 한 번** 판정하면
된다. EB-5와 합쳐 `UC-SCALE-001`의 지배적 비용이다.

---

## 2. Plausible bug — 조건이 맞으면 터진다

### PB-1. preflight가 `Exchange` Protocol에 없는 `exchange.listings`를 읽는다

**위치** — [`src/vqapr/flow/preflight.py:132`](../../src/vqapr/flow/preflight.py), [`:203`](../../src/vqapr/flow/preflight.py)

```python
rule = exchange.listings.get(instrument_id)                    # _validate_initial_account
... if instrument_id not in exchange.listings ...              # _validate_instrument_universe
```

그런데 문서화된 계약([`exchange/venue.py:18-30`](../../src/vqapr/exchange/venue.py))은 이렇다.

```python
class Exchange(Protocol):
    exchange_id: str
    @property
    def rules(self) -> ExchangeRulesView: ...
    def execute(self, orders, account, snapshot) -> FillBatch: ...
```

`listings`는 **계약에 없다.** 계약상 접근 경로는 `exchange.rules.listings`다. 두 built-in이 우연히
`listings`를 직접 노출해서 테스트가 통과할 뿐이다.

**터지는 조건.** Protocol만 만족하는 Exchange가 initial account와 함께 preflight에 들어오면
`AttributeError: 'X' object has no attribute 'listings'` — **typed `VqaprError`가 아니라 raw
AttributeError**다. PRD §2.6/§10.1이 요구하는 stage·error code·retry precondition이 하나도 없다.

(EB-3의 whitelist가 지금은 이 경로에 도달하기 전에 막지만, EB-3를 고치면 즉시 드러난다.
**EB-3와 함께 고쳐야 한다.**)

### PB-2. `materialize`가 component 경로를 CWD 기준으로 푼다

**위치** — [`src/vqapr/flow/materialize.py`](../../src/vqapr/flow/materialize.py), `materialize()` 안
(리뷰 시점 `:681`, 동시 편집으로 `:733`으로 밀림 — `grep -n "load_data_model(ref)"`로 찾을 것)

```python
model = load_data_model(ref)          # ← project_root= 없음
```

`preflight_run`과 `public.run`은 모두 `project_root=`를 넘긴다. `_load`는 `project_root is None`이면
`ref.path`를 그대로 쓰므로 **process CWD 기준**이 된다.

**터지는 조건.** 두 등록 경로가 경로 처리에 대해 서로 다르게 동작하는 것이 근본 원인이다.

| 등록 경로 | 저장되는 경로 |
|---|---|
| `register_data_model()` ([`extension/registration.py:86`](../../src/vqapr/extension/registration.py)) | `Path(path).resolve()` — **절대** |
| `public.component_ref()` ([`public.py`](../../src/vqapr/public.py)) → `ComponentRef.of` | `Path(path)` — **준 대로** |

후자로 DataModel을 상대경로 등록한 뒤 다른 디렉터리에서 `materialize(project_root=...)`를 부르면
`component.load.source_unreadable`이 등록과 무관한 경로를 가리키며 뜬다. 같은 이유로 workspace의
이식성도 등록 경로에 따라 달라진다.

**고칠 때.** `load_data_model(ref, project_root=project_root)` 한 줄이면 이 버그는 막히지만,
**두 등록 경로의 경로 정규화 정책을 하나로 통일하는 것**이 진짜 수정이다.

### PB-3. workspace 등록이 lock 없는 read-modify-write다 (동시성)

**위치** — [`src/vqapr/workspace.py:357`](../../src/vqapr/workspace.py) 외 `register_*` 전부

모든 `register_*`가 `_read()` → 메모리에서 한 항목 병합 → `_write()`(전체 재작성)이다.
`_write`는 `NamedTemporaryFile` + `fsync` + `os.replace`로 **파일 쓰기 자체는 원자적**이지만,
**트랜잭션은 아니다.**

**터지는 조건.** 두 process(agent 둘, 또는 `materialize` 발행과 수동 `register_dataset`)가 같은
project root에 붙는다. 둘 다 상태 S를 읽는다. P1이 `S+{alpha}`를 쓰고, P2가 `S+{benchmark}`를 쓴다.
최종 파일에는 benchmark만 남는데 **P1의 `register_dataset`은 `True`를 반환했다** — 호출자는 등록이
성공했다고 믿는다.

**어느 요구사항을 깨나.** PRD §9.3 *"Publication은 원자적이다"*, `UC-ARTIFACT-003`
*"동시 publication과 중단"*, PRD §12.5 *"process-global provider를 concurrent run 사이에서 무보호
mutation"* 금지.

**고칠 때.** lock 파일, 또는 `_read()` 시점 상태를 `_write()` 직전에 재확인하는 compare-and-swap.
현재 구조상 후자가 더 작다.

---

## 3. Missing scope — PRD가 요구하는데 코드가 없다

### MS-1. Strategy callback이 actual state 이력을 볼 수 없다 (`UC-ACCOUNT-HISTORY-001`)

**위치** — [`src/vqapr/models/contexts.py:23-42`](../../src/vqapr/models/contexts.py)

```python
@dataclass(frozen=True, slots=True)
class StrategyModelContext:
    occurrence: OperationOccurrence
    window: ModelWindow
    account: AccountSnapshot          # ← version, cash, positions 뿐
    constraint_bounds: ConstraintBounds = ...
```

`AccountState`는 `fill_history`, `mark_history`를 **가지고 있다.** 그런데 callback에 투영되지 않는다.
`src/vqapr/account/history.py`는 **0바이트**다.

**요구사항.**

- **`UC-ACCOUNT-HISTORY-001` / PRD §14.3** — *"strategy state 없이 actual state 이력만으로 stop-loss와
  cooldown을 표현할 수 있고, **이력 접근이 strategy state 보유 여부에 종속되지 않는다.**
  계좌 evaluation-time 시계열과 instrument panel을 선택해 구독할 수 있다."*
- PRD §6.6 *"이력으로서의 actual state"*

현재 유일한 우회는 Model memory에 이력을 직접 복제하는 것인데, **그것이 바로 use case가 배제하라고
한 strategy-state 종속**이다. `UC-CLOSED-LOOP-001`의 feedback 절반도 같은 이유로 미완성이다.

### MS-2. `SingleNameCap`이 조용히 long-only를 강제한다

**위치** — [`src/vqapr/constraints/builtin/single_name_cap.py:120-125`](../../src/vqapr/constraints/builtin/single_name_cap.py)

```python
def project(self, window, instruments) -> ConstraintBounds:
    benchmark = self._benchmark(window, instruments)
    return ConstraintBounds(
        {instrument: Decimal(0) for instrument in instruments},              # ← lower = 0
        {instrument: max(self._cap, benchmark[instrument]) for instrument in instruments},
    )
```

`merged_constraint_bounds`가 lower를 `max`로 교집합하므로, **cap 하나만 선언해도 전 종목 lower=0**
이 되어 short leg 전체가 사라진다.

**모순 두 개.**

1. **PRD §2.1** — *"실제 borrow 가능성이나 선택한 execution profile의 long-only 제약 때문에
   **research intent를 미리 long-only로 축소하지 않는다.**"*
2. `no_short.py` 자신의 docstring — *"This is the constraint that makes long-only an **emergent
   property of the constraint set**"*. `SingleNameCap`이 이미 그것을 하고 있으므로 두 built-in의
   역할 분담이 코드에서 무너져 있다.

`evaluate()`의 `abs(mark.value)/nav`도 같은 혼동이다 — short 위반이 cap 위반으로 보고된다.
PRD §14.4가 요구하는 "어느 constraint가" 구분이 깨진다.

**고칠 때.** cap constraint의 lower는 `-max(cap, benchmark)` 또는 "무제한"이어야 하고, long-only가
필요하면 `NoShort`를 함께 선언하게 하는 것이 두 built-in의 선언된 역할과 맞는다.

---

## 4. Obsolete / stale — 지우거나 채워야 한다

### OS-1. 0바이트 모듈 ~40개가 패키지 안에 배포된다

**확인.**

```bash
find src/vqapr -name "*.py" -size -1c | wc -l    # → 47 (__init__.py 포함)
```

| 영역 | 파일 | 무엇이 없어지나 |
|---|---|---|
| `cli/` | 9개 전부 | console script (EB-4), `vqapr new/check/register/run` |
| `testing/`, `testing/conformance/` | 11개 | architecture §10.3 conformance suite = 등록 게이트 (EB-3의 정답) |
| `agent/` | 4개 | PRD §11 bundled agent skill 표면 |
| `analysis/` | 6개 | PRD §9.4 report / renderer (`UC-REPORT-001/002`, `UC-MONITOR-001`) |
| `transforms/` | 5개 | PRD §5.6 / `UC-EXTENSION-001`의 built-in 예제, `UC-LOOKTHROUGH-*` |
| `evidence/` | `catalog.py`, `lineage.py`, `publication.py` | PRD §9.2 dependency graph, §9.6 reuse 판정 |

**그중 일부는 살아 있는 모듈의 중복이다 — 이건 채울 게 아니라 지울 것이다.**

| 빈 파일 | 실제 구현 위치 |
|---|---|
| `data/stores/duckdb.py`, `data/stores/memory.py` | `data/store.py`의 `DuckDbObservationStore` |
| `constraints/projection.py` | `constraints/evaluation.py`의 `project_constraints` |
| `account/journal.py` | `account/account.py`의 `JournalEntry` |
| `account/history.py` | (없음 — MS-1) |
| `exchange/venues/academic.py` | `exchange/venue.py`의 `AcademicExchange` |
| `domain/instruments.py` | `domain/identifiers.py` / `exchange/listings.py`에 분산 |
| `extension/scaffold.py` | (없음 — `vqapr new`용) |

**왜 문제인가.** 읽는 사람도, 레이아웃을 따라가는 agent도 **placeholder와 모듈을 구분할 수 없다.**
`data/stores/duckdb.py`를 열어본 사람은 store가 미구현이라고 결론 내린다. architecture §10 package
layout이 "계획"인지 "현황"인지 코드만 봐서는 알 수 없다.

**권고.** ① 중복 7개는 **즉시 삭제**. ② 나머지는 삭제하고 미구현 scope로 문서에 남기거나, 최소한
`raise NotImplementedError`와 한 줄 docstring을 넣어 "의도된 미구현"임을 코드가 말하게 한다.

### OS-2. 미사용 runtime dependency 4개

**위치** — [`pyproject.toml:11-16`](../../pyproject.toml)

```bash
for m in cvxpy pydantic pytz pandas; do echo "$m: $(grep -rl "import $m" src/ tests/ showcases/ | wc -l)"; done
# cvxpy: 0   pydantic: 0   pytz: 0   pandas: 0
```

실제 사용: `pyarrow`(`flow/materialize.py`), `duckdb`(`data/scan.py`), `pyyaml`(`workspace.py`). 끝.

**`cvxpy`가 특히 나쁘다.** 설치할 때마다 numpy/scipy/osqp/clarabel/ecos 스택이 딸려 오고, 무엇보다
`portfolio/optimize.py`의 첫 줄과 정면으로 모순된다.

> *"Constrained allocation solved exactly, **with no solver package**."*

의존성 목록을 감사하는 사람은 cvxpy가 최적화 경로에 있다고 결론 내린다. `pytz`는 코드가 실제로 쓰는
`zoneinfo`와 중복이다.

### OS-3. 테스트만 부르는 production API 4개

**위치** — [`src/vqapr/flow/run_state.py:372-406`](../../src/vqapr/flow/run_state.py), [`:439-446`](../../src/vqapr/flow/run_state.py)

`accept_no_decision`, `accept_intent`, `capture_live_memory`, `restore_live_memory` —
**production 호출자가 없다.** `SimulationFlow`는 `prepare_callback`/`publish`를 직접 쓰고,
live memory 복원도 `_restore_callback_state`로 자체 처리한다. 유일한 호출자는
`tests/flow/test_acceptance.py`다.

**왜 위험한가.** callback publication 계약을 바꾸는 사람이 `SimulationFlow`와 `prepare_callback`만
고치고 이 넷은 테스트가 통과하니 그냥 둔다. 그 순간 "callback이 어떻게 accept되는가"에 대한 서술이
코드베이스에 **두 벌** 생기고, 그 테스트들은 **Flow가 더 이상 타지 않는 경로**를 검증하게 된다.

**권고.** Flow가 이것들을 타게 하거나, 테스트와 함께 지운다.

---

## 5. Refactor needed — 동작은 하지만 다음 변경에서 사고가 난다

### RF-1. `workspace.py` — 8개 선언 map을 위치 인자로 16곳에 흘린다

**위치** — [`src/vqapr/workspace.py:702-733`](../../src/vqapr/workspace.py) (`_register_declaration`), `_read`/`_write`/`_replace_state`, 그리고 `register_*` 9개

```bash
grep -c "monitoring_policies," src/vqapr/workspace.py   # → 16
```

같은 8개 이름이 **같은 순서로** 16번 반복된다. `_register_declaration`은 그 튜플을 **정수 인덱스**로
건드린다.

```python
merged = list(state)
updated = dict(declarations)
updated[key] = detach(value)    # type: ignore[operator]
merged[position] = updated      # ← position: int
self._write(*merged)            # type: ignore[arg-type]
self._replace_state(*merged)    # type: ignore[arg-type]
```

**다음 변경에서 무슨 일이 나나.** 9번째 선언 종류를 추가하려면 signature 4개 + `register_*` 9개 +
모든 unpack 지점을 **같은 순서로** 고쳐야 한다. 한 군데에서 `strategy_configs`와
`valuation_configs`를 바꿔 넣으면 **타입 체크를 통과하고 workspace가 조용히 오염된다.**
`# type: ignore` 3개가 이미 그 위험을 말하고 있다.

**권고.** named field를 가진 frozen `WorkspaceState` 하나 + `with_(...)` 교체 메서드. 인자 8개가
1개가 되고, 순서를 틀리는 것이 **표현 불가능**해진다.

### RF-2. `flow/simulation.py` — `_execute_due` 250줄 + 죽은 필터

**위치** — [`src/vqapr/flow/simulation.py:467-720`](../../src/vqapr/flow/simulation.py) (모듈 전체 1,287줄)

**죽은 코드.**

```python
prices = {row.instrument: row.price for row in snapshot.rows if row.price is not None}
selected_prices = {
    instrument: price for instrument, price in prices.items() if price is not None
}   # ← 두 번째 comprehension은 절대 아무것도 걸러내지 못한다
```

이 중복이 **EB-1의 진짜 문제(빠진 `is_tradable` 필터)를 가리고 있다** — 읽는 사람은 "필터가 두 번
있으니 걸러지고 있구나" 하고 넘어간다.

**구조.** `_execute_due`는 `_due_boundary(...)` 15연발이고, 각 호출이 `stage` / `cutoff` /
`owner` / `family` / `kind`를 매번 다시 적는다. `cutoff`는 전부 `pending.target.target_at`이고,
`kind`는 특정 지점부터 `FAILED_AFTER_COMMIT`으로 바뀐다 — **그 전환이 코드에서 한 줄로 보이지 않고
15개 인자에 흩어져 있다.** post-commit 단계를 하나 추가하는 사람이 `kind`를 손으로 기억해서 바꿔야
한다.

**권고.** `(cutoff, pending)`에 바인딩된 phase helper 두 개(pre-commit / post-commit)를 만들면
그 경계가 **한 줄**이 된다. `_dispatch_callback`(약 200줄)도 같은 처방이 필요하다.

---

## 6. 잘 되어 있는 것 (건드리지 말 것)

리팩터링할 때 아래는 **의도된 설계**이므로 "단순화" 대상이 아니다.

- **`portfolio/optimize.py`의 exact rational solve.** `Fraction` breakpoint scan + 12자리 canonical
  grid + cash를 유일한 residual sink로 두는 설계는 tolerance 없는 정확성을 실제로 달성한다.
  `_absorb_grid_residual`이 interior weight만 건드리는 것도 box 보장을 지키기 위한 것이다.
- **`data/scan.py:425-443`의 rows-lookback SQL.** (instrument × field)별 non-null 카운트를 window
  function으로 밀어 넣어 PRD §3.5 / `UC-LOOKBACK-001`의 "store까지 강제되는 exact lookback"을
  만족한다.
- **`prepare_* → commit_*` 2단 구조** (`Account`, `RunStateRepository`). 모든 실패 가능한 작업이
  commit 전에 끝나고 pointer swap만 남기는 구조가 PRD §2.4의 authority 경계를 지킨다.
- **`portfolio/weighting.py`의 sizing / `rescale` 분리.** PRD §5.5의 flexible↔fixed budget 구분을
  호출부 소스에 드러내는 결정이 명시적으로 문서화되어 있다.
- **`domain/errors.py`의 `Failure`/`Diagnosis`/`collector`.** 한 단계에서 실패를 전부 모아 주는 설계가
  PRD §2.6의 agent-readable 요구와 정확히 맞는다.

---

## 7. 착수 순서 제안

1. **EB-1** — run을 죽이는 유일한 항목. `UC-TRADABILITY-002` acceptance test를 먼저 쓴다
   (정지 종목 **매도** → 나머지 매수 clipping → run 완주).
2. **EB-4 / OS-2** — 선언과 현실을 맞추는 것뿐이라 한 커밋에 끝난다.
3. **EB-2** — `_worst` 로직 교체 + `nav<=0` 명시 실패.
4. **EB-3 + PB-1 + OS-1(중복 7개)** — 묶어서. conformance suite를 채우고 whitelist를 걷어내면
   PB-1이 즉시 드러나므로 함께 고쳐야 한다.
5. **EB-5 / EB-6** — `UC-SCALE-001`을 실제로 돌려보기 전에.
6. **MS-1 / MS-2** — 새 capability라 별도 ExecPlan 대상.
7. **RF-1 / RF-2 / OS-3** — 위 작업 중 해당 파일을 열었을 때 함께.

---

*이 문서는 리뷰 시점의 스냅샷이다. 항목을 처리하면 `RESOLVED @ <sha>`로 표시하고, 재현 절차가 더
이상 재현되지 않으면 그 사실을 함께 적어 다음 리뷰가 같은 지점을 다시 파지 않게 한다.*
