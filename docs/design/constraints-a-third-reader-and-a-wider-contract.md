# Constraint — 점검값 하나, 범위 하나, 독자 셋

| | |
|---|---|
| **작성 시각** | 2026-09-03 KST (+09:00), 같은 날 2판. **2026-09-04 3판 — §9 소유자 보정** |
| **상태** | **제안.** §8의 1번(기록 `140`)만 구현되었고 나머지는 `src/`를 움직이지 않았다. §7의 열린 결정 4는 §9.4에서 닫혔고, 나머지와 §9.7의 7·8은 소유자 판단을 기다린다 |
| **근거** | `docs/vqapr-prd.md` §7·§7.1·§12.3·§12.4, `docs/vqapr-architecture.md` §5.7·§11.7, 기록 `130`, 이슈 `014`·`051` |
| **계기** | 0.3.0 릴리즈 뒤 소유자 질문 두 개 — 한국 공모펀드 동일종목 한도를 이 프레임워크로 표현할 수 있는가, 전략이 monitoring이 보는 수치를 판단 시점에 볼 수 있는가 |
| **소유자 ruling (2판의 이유)** | *모든 constraint는 "점검값이 범위 안에 있는가"로 추상화된다. constraint는 user가 꽂는 확장 모듈이고, 계산에 필요한 data는 lookback 있는 dataset일 수도, lookback 없는 mapping table일 수도, 코드에 박힌 규칙일 수도 있다. data가 없으면 그 constraint는 구현할 수 없고, 그것으로 족하다.* |
| **선례** | `docs/design/the-panel-the-surface-and-the-run.md`. 승인되면 architecture §5.7이 흡수한다 |

1판은 합산 제약을 위해 `ConstraintBounds`에 group bound를 더하고 optimize를 넓히자고 했다. 소유자 ruling이
그 방향을 뒤집었다 — **제약의 본질은 optimize에 줄 box가 아니라 measure ∈ range다.** box는 그 중 한 특수형이다.
2판은 그 위에서 다시 쓴 것이다.

---

## 0. 문서가 이미 말하는 것, 그리고 이 문서가 얹는 것

PRD §7·architecture §5.7이 정한 것은 유지된다.

- 선언 하나(run 소유), 소비자 둘 — 판단 시점의 bound와 별도 cadence의 committed account 판정.
- 판단을 채점하는 세 번째 member는 없다(기록 `130`, 이슈 `014`). 측정하는 자리는 하나다.
- finding은 어느 규칙·그때의 한도·점검값(+ `offenders`)만 싣는다.
- 제약은 자기 data를 선언하고, 없으면 결과를 만들기 전에 실패한다. 누락을 0으로 추정하지 않는다.
- 제약은 physical 보유에만 건다(PRD §8.2).
- monitoring은 선언된 제약만 판정한다. 전략의 구성 선택은 제약이 아니다.

이 문서가 얹는 것은 셋이다.

1. **계약을 "measure ∈ range"로 다시 쓴다.** `project`는 author member에서 사라지고, 종목 비중을 재는
   제약에 한해 framework가 box를 **유도**한다.
2. **전략이 같은 자로 잰 값을 본다.** 출발 장부의 reading, 그리고 후보 장부를 재 보는 `check`.
3. **occurrence별 finding을 record에 남긴다.** 지금은 집계만 남는다.

---

## 1. 현재 구현과 그 한계

`tests/constraints` + `tests/acceptance/test_enhanced_index.py` 22건 green (2026-09-03).

| 층 | 있는 것 | 파일 |
|---|---|---|
| 계약 | `inputs() / project(call) -> ConstraintBounds / monitor(call, account, bounds) -> ConstraintFinding` | `authoring.py:888` |
| bound | 종목별 box **만** | `authoring.py:423` |
| call | `evaluation_time`, `instruments`, `read/rows`. account 없음 | `authoring.py:800` |
| 전략이 받는 것 | `call.constraint_bounds` — 교집합 벡터 하나. 정체는 merge에서 사라진다 | `evaluation.py` |
| optimize | box + budget + frozen, 단일 λ 정확해 | `portfolio/optimize.py` |
| monitoring | occurrence마다 재투영 → `monitor` → `ConstraintReport` | `simulation.py:1354` |
| 기록 | `contract` 블록의 id별 `held/checked` 집계만. occurrence별 값은 in-memory에만 | `records.py` |

**계약의 한계는 하나로 요약된다 — 제약이 box여야 한다.** `project`가 종목별 상하한을 반드시 내야 하고
(`evaluation.py`가 전 종목 커버를 검사한다), `monitor`는 그 box를 받아 잰다. ETF 운용사 합산처럼 box로 쓸
수 없는 제약은 **계약상 작성이 불가능하다** — author가 measure 코드를 갖고 있어도 꽂을 자리가 없다.

### 발견 — `single_name_cap`이 누락을 0으로 추정한다

`single_name_cap.py:131`:

```python
return {instrument: latest.get(instrument, Decimal(0)) for instrument in call.instruments}
```

PRD §7과 `UC-CONSTRAINT-002`는 실패를 요구한다. panel read에서 "비구성 확인"과 "미전달"이 같은 부재로
보이므로 이 코드는 둘을 구분할 수 없고, 구분하지 않은 채 0을 택했다. `tests/constraints/test_builtin.py:128`의
지원 코드도 같은 모양이라 잡히지 않았다. §8의 3번.

---

## 2. 계약 — measure ∈ range

```python
class Subject(Enum):
    INSTRUMENT_WEIGHT = "instrument_weight"   # 피측정 대상이 종목이고 값이 NAV 대비 비중 → box 유도 가능
    CUSTOM = "custom"                          # 그 밖의 전부: 그룹 합산, 수량 비율, 계좌 전체 지표

@dataclass(frozen=True, slots=True, kw_only=True)
class Range:
    lower: Decimal
    upper: Decimal

@dataclass(frozen=True, slots=True, kw_only=True)
class Bounds:
    default: Range | None                 # subject별 값이 없을 때
    by_subject: Mapping[str, Range]       # subject → range

class ConstraintCall(ABC):
    evaluation_time: datetime
    instruments: tuple[str, ...]
    account: EconomicAccountView | None   # committed, 직전 mark로 값 매김. 첫 valuation 전 None
    def read(alias, field) -> PanelWindow
    def rows(alias) -> tuple[Observation, ...]

class Constraint(ABC):
    constraint_id: str
    subject: Subject
    def inputs(self) -> Mapping[str, DatasetInput]: ...               # 지금과 같다
    def measure(self, call: ConstraintCall) -> Mapping[str, Decimal]: # subject → 점검값
    def bounds(self, call: ConstraintCall) -> Bounds: ...             # subject → 범위
```

**author가 쓰는 것은 둘이다 — 무엇을 재는가, 어디까지 허용되는가.** 통과/위반은 author가 쓰지 않는다.

### 2.1 framework가 하는 것

- **판정.** subject마다 `lower ≤ measured ≤ upper`. 밖에 있는 subject가 `offenders`, 가장 많이 벗어난 것의
  값이 `measured/bound/excess`. `ConstraintFinding`의 모양은 지금과 같고, `passed`를 author가 쓰지 않게 된
  것만 다르다. 기록 `130`이 `constraint_id`를 finding에서 뺀 것과 같은 이유다 — author가 이미 준 두 값에서
  framework가 만들 수 있는 것을 author에게 다시 쓰게 하면, 틀리게 쓸 자리만 생긴다.
- **box 유도.** `subject is INSTRUMENT_WEIGHT`인 제약의 `bounds`는 그대로 종목별 box다. framework는 전
  종목 커버를 요구하고(`default`로 채워도 된다), 지금처럼 교집합해 `constraint_bounds`를 만든다. `CUSTOM`은
  box를 내지 않는다 — optimize는 그것을 모르고, 전략이 §3의 `check`로 다룬다.
- **account 공급.** `call.account`는 monitoring이면 그 occurrence의 committed account, 전략 callback이면
  직전 mark의 committed account, `check`면 후보 장부다(§3.2). 세 경우 **같은 `build_account_view`**로 만든다.

### 2.2 왜 `project`가 사라지는가

1판까지 `project`는 author가 반드시 써야 하는 member였고, 그래서 box가 아닌 제약은 쓸 수 없었다. 소유자
ruling대로 제약의 본질이 measure ∈ range라면 box는 *"subject가 종목이고 값이 비중일 때 range가 곧 box"*라는
**특수형**이고, 그것은 author가 쓸 일이 아니라 framework가 알아볼 일이다. 사라지는 것은 member이지 기능이
아니다 — `no_short`와 `single_name_cap`은 `INSTRUMENT_WEIGHT`로 선언되고 지금과 같은 box를 낸다.

**기록 `130`의 "account came off `project`"는 되돌아온다.** 그때의 근거는 *"nothing needed it"*이었고, 지금은
필요한 것이 있다 — 발행주식수 10%를 비중 range로 내려면 NAV와 가격이 필요하고, 운용사 합산을 재려면
보유가 필요하다. `measure`가 account를 받는 이상 `bounds`만 못 받게 할 이유가 없고, 둘 다 하나의 `call`로
받는 것이 `DataCall`·`StrategyCall`과 같은 모양이다.

### 2.3 있는 그대로 남는 것

- **monitoring은 한 자리에서 잰다.** `measure`는 하나이고 monitoring도 전략도 `check`도 그것을 부른다.
  이슈 `014`의 세 답은 세 member에서 나왔다. member가 하나면 답도 하나다.
- **breach는 run을 멈추지 않는다.** 기록 `130`과 같다.
- **제약은 physical에만.** `call.account`는 physical 보유다. look-through 노출은 여기 없다.

---

## 3. 전략이 보는 것 — 채점이 아니라 관측

PRD §7이 금지한 것은 **판단에 대한 framework의 두 번째 답**이지, 전략이 관측을 입력으로 받는 것이 아니다.

```text
금지된 것     decide() ──► framework 채점 ──► 통과/거절
제안하는 것   measure(출발 장부) ──► decide() ◄──► measure(후보 장부)      framework는 판정하지 않는다
```

### 3.1 `StrategyCall`에 셋

```python
class StrategyCall(ABC):
    constraint_bounds: ConstraintBounds
    """지금과 같다. INSTRUMENT_WEIGHT 제약의 교집합 box. optimize에 넣는 것."""

    constraints: tuple[DeclaredConstraint, ...]
    """제약별 (constraint_id, subject, bounds). 어느 상한이 어느 규칙에서 왔는지, 어느 제약이 box가 없는지."""

    constraint_readings: tuple[StampedConstraintFinding, ...] | None
    """출발 장부(committed, 직전 mark)에 대한 finding. mark가 없으면 None — 빈 tuple이 아니다."""

    def check(self, weights: Mapping[str, Decimal], cash: Decimal) -> tuple[StampedConstraintFinding, ...]:
        """후보 장부를 같은 자로 잰다. 기록되지 않고, 판정하지 않는다. mark가 없으면 refuse."""
```

**`constraint_readings`가 규정상 필요한 이유.** 시총비중 캡은 월말에 갱신되고, 갱신 직후 *이미 들고 있는*
포지션이 새 캡을 넘을 수 있다. "월초 기존 포지션도 캡을 넘지 않게" 하려면 전략은 그 callback에서 어느 이름이
얼마나 넘었는지 알아야 한다. 지금은 `constraint_bounds`와 `account.weights()`를 전략이 직접 대조해야 하고,
그 대조는 `monitor`의 재구현 — 두 번째 채점자를 전략 안에 들이는 것이다.

**`check`가 필요한 이유.** `CUSTOM` 제약은 box가 없으므로 optimize가 지켜 줄 수 없다. 운용사 합산 50%를
지키려면 전략은 후보를 만들고 → 재고 → 넘친 운용사의 ETF를 줄이고 → 다시 잰다. 그 "재기"가 제약의 `measure`
자체가 아니면 전략은 자기 measure를 따로 갖게 되고, 그것이 monitoring과 갈린다. `check`는 framework가 자를
**빌려주는** 것이지 판정하는 것이 아니다 — 결과는 evidence에 남지 않고, 전략이 원하면 자기 table에 적는다.

### 3.2 후보 장부는 어떻게 만드나

`check(weights, cash)`는 직전 mark의 NAV와 가격으로 가상의 `EconomicAccountView`를 만든다 — `value_i = w_i ×
NAV`, `quantity_i = value_i / price_i`, `cash = c × NAV`. 수량 기반 measure(발행주식수 비율)도 이것으로 잰다.
**직전 가격이므로 근사다.** 체결 뒤 실제 수량이 캡을 살짝 넘는 것은 `UC-CONSTRAINT-ADJUST-001` 그대로이고,
그것을 잡는 것은 여전히 monitoring이다. `check`는 monitoring을 대체하지 않는다.

### 3.3 evidence

callback evidence는 지금 `constraints=projected`를 싣는다(`simulation.py:1926`). 같은 자리에 `readings`를 붙인다.
사후 분석에서 *"그때 전략이 무엇을 보고 그렇게 했는가"*가 남는다. `check`는 싣지 않는다 — 전략의 내부 반복이고,
PRD §7.1의 *"판정마다 읽은 것을 전부 따라 적지 않는다"*와 같은 이유다.

---

## 4. 외부 monitor가 보는 것 — 기록의 결손

per-occurrence finding이 durable record에 없다. `contract` 블록의 `held/checked`는 *몇 번*을 답하지 *무엇이
얼마나*를 답하지 않는다. PRD §2는 monitoring finding을 first-class result라고 했다.

**제안.** 전략 record에 `monitoring` 테이블 하나. 행은 (occurrence_id, cutoff, constraint_id, subject, measured,
bound, excess, passed, offenders). 계약 변경이 아니라 기록 누락 수정이다.

---

## 5. data — 세 층, 그리고 없으면 없는 것

소유자 ruling의 두 번째 절반이다. 제약이 필요로 하는 data는 세 곳에서 온다.

| 층 | 무엇 | 예 | 어떻게 |
|---|---|---|---|
| **코드** | 제약의 정체 일부인 규칙 | `TIGER*`→미래에셋, `KODEX*`→삼성, `KIWOOM*`→키움 | constraint 안의 함수. source fingerprint에 접힌다 |
| **config** | run에 frozen되는 매개변수와 작은 표 | cap `"0.10"`, prefix→운용사 dict | `ComponentRef.config` — strict JSON이라 nested dict가 된다 |
| **dataset** | 날짜가 있는 것 | 벤치마크 비중, 시총비중, 발행주식수, 계열사 편입 | `inputs()`로 선언. PIT. lookback 없는 mapping table은 `RowsLookback(rows=1)`, instrument axis 없는 표는 기록 `123`으로 등록 가능 |

**선 긋기.** 바뀌는 날짜가 있으면 dataset이다 — 계열사 편입·분리는 날짜가 있고, 그날 이전의 판정이 그날 이후의
표로 바뀌면 안 된다. prefix 규칙처럼 바뀌면 *제약이 바뀐 것*인 규칙은 코드나 config다.

**없으면 없다.** 발행주식수 10%는 발행주식수 dataset 없이 쓸 수 없다. 그것은 결손이 아니라 계약이다 —
`inputs()`가 선언하고, 등록되지 않았으면 preflight가 거절한다(`UC-CONSTRAINT-002`). framework가 할 일은 그
거절이 *어느 제약이 어느 dataset을 요구했는지*를 말하게 하는 것뿐이다.

**"비구성 확인"과 "미전달".** panel read에서 둘은 같은 부재다. `single_name_cap`의 현재 버그(§1)와 시총비중
캡(§6.2)이 같은 답을 기다린다. dataset 등록이 coverage를 약속하는 방식이라 이 문서 범위 밖이다 — **열린
결정 3**.

---

## 6. 이 계약으로 한국 규정을 쓰면

| 규칙 | subject | measure | bounds | data |
|---|---|---|---|---|
| no-short | INSTRUMENT_WEIGHT | 종목 비중 | `[0, 1]` | 없음 |
| 동일종목 ≤ max(10%, 지수비중) | INSTRUMENT_WEIGHT | 종목 비중 | `[−c_i, c_i]`, `c_i = max(cap, bm_i)` | 벤치마크 panel |
| 동일종목 ≤ max(10%, 전월 일평균 시총비중), 월중 불변 | INSTRUMENT_WEIGHT | 종목 비중 | `c_i = max(0.10, mean_{M−1} share_i)` | 시총비중 panel, 전월을 덮는 `CalendarLookback` |
| 발행인 합산(보통+우선+DR) ≤ 10% | CUSTOM | 발행인별 Σ비중 | default `[0, 0.10]` | 종목→발행인 mapping (dataset 또는 config) |
| ETF 운용사 합산 ≤ 50% | CUSTOM | 운용사별 Σ비중 | default `[0, 0.5]` | prefix 규칙 (코드/config) |
| ETF 하나 ≤ 20%(패시브 30%) | INSTRUMENT_WEIGHT | ETF 비중, 주식은 제외 | ETF `[0, 0.2/0.3]`, 주식 `default [−1, 1]` | 종류·패시브 여부 mapping |
| 발행주식수 ≤ 10% | CUSTOM (또는 INSTRUMENT_WEIGHT로 환산) | `qty_i / shares_out_i` | `[0, 0.10]` | 발행주식수 dataset |
| 계열사 25% & 단일 5% | CUSTOM | 계열별 Σ비중, 계열 내 종목 비중 | `[0, 0.25]`, `[0, 0.05]` | 계열사 mapping dataset (PIT) |
| 자산총액 분모 | — | `account.total_assets`로 나눈다 | — | §7 결정 4 |
| 파생 기초자산 10% | 범위 밖 | look-through | — | PRD §8.2 |
| 개별 펀드 규약 | 위 어느 것이든 config가 더 좁을 뿐 | | | |

### 6.1 예 — ETF 운용사 합산

```python
class EtfManagerCap(Constraint):
    subject = Subject.CUSTOM

    def __init__(self, *, cap: str, manager_by_prefix: dict[str, str], constraint_id="etf-manager-cap"): ...

    def measure(self, call):
        total = defaultdict(Decimal)
        for name, weight in call.account.weights().items():
            manager = self._manager(name)          # prefix 규칙. ETF가 아니면 None
            if manager is not None:
                total[manager] += weight
        return total

    def bounds(self, call):
        return Bounds(default=Range(lower=Decimal(0), upper=self._cap), by_subject={})
```

`inputs()`는 비어 있다. data는 config다. 전략은 `call.check(candidate)`로 이 finding을 받아 넘친 운용사의 ETF를
줄인다. monitoring은 committed account에 같은 `measure`를 돌린다.

### 6.2 예 — 월 1회 고정 시총비중 캡

`single_name_cap`과 **별개의 built-in**으로 둔다 — 지수 내 비중과 시장 전체 대비 시총비중은 다른 숫자이고, 한
클래스의 정책 스위치로 두면 어느 숫자였는지가 config 안으로 숨는다.

- 입력은 일별 `market_cap_share` 필드 하나. 분모(그 시장 전 종목 시총)는 universe 밖이라 constraint가 계산할
  수 없고 해서도 안 된다 — *compliance reference data의 applicability는 user 소유*(PRD §12.4).
- `bounds`는 `call.evaluation_time`의 **전월**에 속하는 instants만 골라 평균한다. 월중 어느 날 불러도 같은
  전월이므로 **월중 불변은 상태 없이 따라온다.** 전월 행의 `available_at`은 전월 말일 이전이라 look-ahead가
  없다.
- 전월 행이 없는 종목(신규 상장)은 규정상 시총비중이 없어 10%가 맞다. 그러나 "없음"과 "미전달"의 구분은 §5의
  열린 결정 3이다.

---

## 7. 열린 결정

| # | 결정 | 추천 | 왜 지금 안 정하는가 |
|---|---|---|---|
| 1 | `Subject` enum 두 값 vs author가 `project`를 선택적으로 override | **enum 두 값** | 필요한 순간이 오면 세 번째 값을 더한다. override는 두 번째 측정 자리를 다시 연다 |
| 2 | `check`를 framework가 제공 vs 전략이 constraint 인스턴스를 직접 부름 | **framework** | run이 제약을 소유하고, 후보 장부 view를 한 곳에서 만들어야 `014`가 안 돌아온다 |
| 3 | "비구성 확인" vs "미전달"을 dataset이 어떻게 약속하는가 | 등록 시 coverage 선언 | 데이터 등록 설계. 이 문서 밖 |
| 4 | `EconomicAccountView.total_assets` 추가 — **닫힘, §9.4** | **추가** (= cash + Σ max(value, 0)) | 작다. 규정이 분모를 명시했으니 author마다 계산하게 두면 `014`가 다른 축에서 돌아온다 |
| 5 | `monitoring_history()` 선언 | **하지 않음** | use case 없음. path-dependent 규칙은 `self.memory` |
| 6 | `no_short`의 measure를 비중으로 옮기는 것 | **옮긴다** | 지금은 수량으로 잰다(NAV 무관이 이유). box를 유도하려면 INSTRUMENT_WEIGHT여야 하고, 가격>0이면 부호는 같다 |

---

## 8. 착수 순서

| 순서 | 무엇 | 계약 변경 | 크기 |
|---|---|---|---|
| 1 | §4 — occurrence별 finding을 record에 | 없음 | 작음 — **완료, 기록 `140`** (`vqapr.monitoring` 테이블) |
| 2 | §2 — `measure/bounds/subject`, `call.account`, framework 판정·box 유도. built-in 둘 이식. scaffold·conformance 갱신 | **breaking** (authoring) | 중간 |
| 3 | §3 — `StrategyCall.constraints`·`constraint_readings`·`check` + evidence | authoring 확장 | 작음 (2 위에서) |
| 4 | §1 발견 — `single_name_cap` 누락→0 (결정 3 이후) | 없음 | 작음 |
| 5 | §6.2 — 시총비중 캡 built-in | 없음 | 중간 |
| 6 | §6.1 — 운용사 합산을 showcase로 (built-in 아님: mapping은 user 소유) | 없음 | 작음 |

2가 breaking이다 — 0.3.0을 testbed에서 쓰는 에이전트들의 constraint scaffold가 `project/monitor`로 나온다.
그 결과가 돌아오기 전에 계약을 바꾸면 그들의 finding이 어느 버전 얘기인지 흐려진다. **1은 지금 해도 되고,
2부터는 testbed 회신 뒤가 맞다.**

---

## 9. 소유자 보정 (2026-09-04, 3판) — 동일종목 한도의 정확한 모양

소유자가 §6 표의 첫 두 행을 규정 원문 수준으로 정정했다. 정정은 사실 하나가 아니라 **이 규칙이 어느
subject에 속하는가**를 바꾸고, 그래서 §8의 순서까지 바꾼다.

### 9.1 사실 (소유자 제공. 이 문서는 법령을 검증하지 않는다 — PRD §12.4, applicability는 user 소유)

| 무엇 | 근거 | 주의할 점 |
|---|---|---|
| 공모펀드는 동일종목 증권을 **자산총액의 10%**까지 | 법 §81①1가목 + 영 §80④ | 분모가 **순자산이 아니라 자산총액**이다 |
| "동일종목"은 회사가 아니라 **증권 종류 단위** | 같은 위 | 같은 회사 보통주·우선주·DR은 **합산**, 그 회사 회사채는 **별개로 또 10%** |
| 10%는 하한이고 캡은 `max(10%, 시총비중)` | 영 §80①3 | 삼성전자 때문에 인덱스 추종이 막히는 것을 푸는 장치 |
| 시총비중은 **월 1회 확정, 월중 불변** | 금융투자업규정 §4-51①② | `캡_i,M = max(0.10, mean_{d∈M−1월}( 시총_i,d / 그 시장 전 종목 시총_d ))`. M−1월 말일 산정 → M월 전체 동일 적용 |
| 그 비중은 **시장별**로 계산 | 같은 위 | KOSPI 종목은 KOSPI 전체가 분모. 유동주식 미조정. **지수 구성종목 합이 분모가 아니다** — KOSPI200 내 비중과 다른 숫자 |
| ETF 보유분은 이 한도 **밖** | 법 §81①1이 집합투자증권을 제외 | ETF 안의 종목을 꺼내 합산하라는 규정이 없다 = look-through 없음 |
| ETF는 별도 한도 | 법 §81①3 | 같은 운용사 펀드 합계 50%, 같은 ETF 하나 20%(패시브 30%), 같은 ETF 증권총수 50% |
| 함께 걸리는 축 | 법 §81①1나·다목, §84④→영 §86①, §81①1바목 | 발행주식수 기준 개별 펀드 10%·운용사 전체 20%, 계열사 25%&5%, 파생 기초자산 동일법인 10% |
| 개별 펀드 규약이 더 좁으면 그쪽이 실제 제약 | — | config가 좁히는 것으로 족하다 |

**주식 한도와 ETF 한도는 서로 다른 두 계산 경로다.** 하나의 제약의 두 분기가 아니다.

### 9.2 §6이 틀린 곳 — 이 캡은 box가 아니다

§6 표는 이것을 두 행으로 적었다: `동일종목 ≤ max(10%, 지수비중)`을 `INSTRUMENT_WEIGHT`로, `발행인
합산(보통+우선+DR) ≤ 10%`를 `CUSTOM`으로. **규정에는 규칙이 하나뿐이다** — 합산된 동일종목의 비중이
`max(10%, 시총비중)` 이하. subject는 종목이 아니라 (발행인 × 증권종류군)이고, 따라서 이 캡은 **`CUSTOM`이다.**
두 행으로 쪼갠 §6은 어려운 절반을 선택 사항처럼 보이게 했다.

결과 셋:

1. **box가 유도되지 않는다.** optimize는 이 한도를 지켜 주지 못한다. 오늘의 계약(`project`가 전 종목
   box를 반드시 낸다)으로는 이 규칙을 **쓸 수 없다** — §1의 결론이 다른 예가 아니라 바로 이 규칙에 걸린다.
2. **§3의 `check`는 편의가 아니라 이 규칙의 유일한 사전 집행 수단이다.** §8에서 3번은 2번에 딸린
   선택이 아니게 된다. 합산 캡을 지키는 유일한 길은 전략이 후보를 만들고 → 재고 → 줄이고 → 다시 재는 것이다.
3. **완화된 box를 별도 constraint로 함께 등록할 수 있다.** "구성원 각각 ≤ 그룹 캡"은 필요조건이므로
   optimize에 안전하게 줄 수 있고, 정확한 합산 판정은 `CUSTOM`이 한다. 둘은 *서로 다른 것*을 재므로
   이슈 `014`의 "한 규칙 두 자"가 아니다. **열린 결정 7.**

### 9.3 월중 불변은 계약 변경 없이 따라온다 — lookback 하나만 정확히

§6.2의 방향이 맞다. 보정 넷:

- **`CalendarLookback(months=1)`은 전월을 덮지 못한다.** 9월 15일에서 1개월 전은 8월 15일이라 8월 1–14일이
  빠진다. 전월 전체를 **항상** 덮는 최소는 `months=2`이고, 제약은 그 창에서 **전월에 속한 instant만** 골라
  평균한다. 앞에 남는 부분은 버린다.
- **상태를 두면 틀린 구현이다.** 캡은 `call.evaluation_time`이 속한 달의 순수 함수이므로 월중 어느 날
  불러도 같은 값이다. `self.memory`에 캡을 얼려 두는 구현은 재현을 *캡을 언제 처음 계산했는가*에
  의존하게 만든다. 월초 갱신 코드도 필요 없다.
- **look-ahead가 없는 이유는 `available_at`이 아니라 이 산식이다.** M월 어느 시점에도 M월 행을 쓰지 않는다.
- **결측은 완화가 아니라 하한이다.** 전월 행이 없는 이름(신규 상장)은 규정상 시총비중이 없어 캡이 10%다.
  §1이 지적한 `single_name_cap`의 `latest.get(name, 0)`과 **모양은 같고 성질이 다르다** — 거기서 0은
  "벤치마크를 못 봤다"를 "벤치마크가 0이다"로 추정한 버그이고, 여기서 10%는 규정이 정한 값이다. 그러므로
  이 제약은 그 진술을 코드에 **명시**해야 하고, 우연히 같은 숫자가 나오는 것에 기대면 안 된다. 열린 결정 3이
  답을 주면 "이 dataset은 전 종목을 약속한다/아니다"가 둘을 갈라 준다.

**대안을 셋으로 갈라야 한다 (§9.9).** 이 문단은 원래 *"미리 만든 월별 캡 dataset은 평균이 프레임워크
밖에서 계산되어 아무도 검증하지 않는다"*며 제약 안에서 유도하는 쪽을 권했다. 그 판단은 **틀렸다** — 벤더가
건네는 파일과 DataModel이 발행하는 dataset을 같은 것으로 셌기 때문이다. 셋째 모양이 있고 그것이 최선이다.
분모(그 시장 전 종목 시총)가 universe 밖이라 user 소유 field라는 것만 세 경우 모두에 그대로 남는다.

### 9.4 열린 결정 4가 닫힌다 — 분모는 자산총액

규정이 분모를 명시했으므로 `EconomicAccountView.total_assets`를 더한다(= `cash + Σ max(value, 0)`).
단 이것은 **정의된 대용**이다 — 미수금·미수수익·차입금이 이 모델에 없다. 계약 docstring이 그 사실을 말하지
않으면, 나중에 실제 펀드 회계와 숫자가 갈릴 때 어느 쪽이 틀렸는지 가릴 수 없다.

### 9.5 못 보는 것 — "없으면 없다"가 걸리는 세 곳

| 축 | 왜 못 보는가 |
|---|---|
| 운용사 전체 20%(발행주식수, 다목), 같은 운용사 펀드 합계 50% | run 하나는 계좌 하나만 본다. 다른 펀드의 보유는 이 프레임워크 안에 없다 — dataset으로 들여오지 않으면 표현 불가 |
| 파생 기초자산 동일법인 10%(바목) | look-through. PRD §8.2가 제약을 physical 보유에만 걸었다 |
| 회사채 별도 10% | 채권 instrument가 오늘 universe에 없다. 종목→증권종류 mapping의 *종류* 축이 생기면 그때 열린다 |

### 9.6 공통 입력 하나가 셋을 먹인다

동일종목 합산 · ETF 별도 한도 · 계열사 — 셋이 같은 표를 요구한다: 종목 → (발행인, 증권종류, ETF면
운용사·패시브 여부). 발행인 귀속과 계열 편입·분리는 **날짜가 있으므로 dataset**이고(§5의 선 긋기),
증권종류는 사실상 불변이라 config여도 된다. 표 하나가 셋을 먹이므로 §8 순서에서 이것이 앞선다.

### 9.7 열린 결정 — 7·8 추가

| # | 결정 | 추천 |
|---|---|---|
| 7 | 합산 규칙에 완화된 box("구성원 각각 ≤ 그룹 캡")를 별도 constraint로 함께 등록하는가 | **한다.** optimize가 아무것도 모르는 것보다 필요조건이라도 아는 편이 낫고, 두 제약이 재는 것이 다르므로 `014`가 아니다 |
| 8 | 그룹의 캡에 쓰는 시총비중이 **그룹 구성 증권 시총의 합**의 비중인가, **보통주 하나**의 비중인가 | **닫힘 (2026-09-04) — 보통주.** §9.8 |

### 9.8 소유자 결정 — 보통주 해석 (2026-09-04)

**시총비중은 우선주를 빼고 보통주 기준으로 해석한다.** 열린 결정 8이 닫혔다.

이 결정이 푸는 것과 **풀지 않는 것**을 갈라 둔다. 둘은 캡의 서로 다른 쪽이다.

| | 무엇 | 이 결정 뒤 |
|---|---|---|
| **캡 값 (한도)** | `max(0.10, 전월 일평균 보통주 시총비중)` | **풀렸다.** 종목별 스칼라 하나. §9.3대로 계산되고 계약 변경이 필요 없다 |
| **점검값 (분자)** | 규정상 보통주+우선주+DR의 비중 **합** | **안 풀렸다.** 이건 분모 해석이 아니라 subject 문제다 |

**그러므로 이 규칙이 오늘 계약에 들어가는지는 유니버스가 정한다.**

- 유니버스가 **보통주만** 담으면 발행인당 상장 라인이 하나이므로 합산 = 개별 비중이고, 이 제약은 **순수한
  box**다. `project/monitor` 그대로, **계약 변경 없이 builtin 하나로 끝난다.**
- 우선주·DR을 하나라도 담으면 그 이름에서만 합산이 되살아나고, box는 §9.2의 필요조건만 표현한다.

**프레임워크는 그 조건을 검사해 주지 못한다.** `InstrumentKind`는 `{stock, etf, index, factor}` 넷뿐이라
보통주·우선주·DR을 한 값으로 뭉개고, roster는 `ConstraintCall`에서 보이지 않는다(exchange/cost 경로 전용).
그래서 "우리 유니버스는 보통주만"은 **검사되지 않는 전제**다. §5의 "없으면 없다"가 그대로 적용된다 —
종목→발행인 mapping이 없으므로 합산 버전은 구현할 수 없고, 구현 가능한 것은 보통주 버전이다.

**전제를 숨기지 않는 방법.** 제약의 *이름과 docstring이 범위를 말한다* — 이것은 보통주 유니버스에서
동일종목 한도와 일치하며, 우선주·DR이 유니버스에 들어오는 순간 필요조건으로 약해진다. 그 문장이 코드에
없으면, 나중에 우선주를 담았을 때 제약은 조용히 **덜 세는 자**가 된다. 그날 필요한 것은 종목→발행인
mapping 하나이고, 같은 표가 §9.6의 셋을 함께 먹인다.

**계약 변경(§8의 2번)은 이 결정으로 사라지지 않는다.** ETF 별도 한도·계열사·발행주식수는 여전히 `CUSTOM`이고
box가 없다. 바뀐 것은 *동일종목 캡이 더 이상 그 변경을 기다리지 않는다*는 것뿐이다 — §8 순서에서 5번(시총비중
캡 built-in)이 **2번 앞으로 나온다.**


### 9.9 채택 — 캡은 DataModel이 발행하고 constraint는 구독한다

**testbed의 에이전트가 시킨 적 없는 모양을 냈고, 소유자가 그것을 모범으로 판정했다 (2026-09-04):** 월마다
확정되는 캡을 **먼저 DataModel로 뽑아 dataset으로 발행**하고, constraint는 그 dataset을 구독해 읽는다.

| 모양 | 산식이 어디서 도는가 | 검증되는가 | 판정 |
|---|---|---|---|
| 벤더 파일 | 프레임워크 밖 | 아니다 — 신뢰할 뿐 | 거부 |
| constraint 안에서 유도 | occurrence마다 다시 | 그렇다 | 되긴 한다 |
| **DataModel이 발행 → constraint가 구독** | 한 번, 자기 run에서 | 그렇다 | **채택** |

**왜 이게 낫다고 판정하는가.**

- **DataModel은 프레임워크 밖이 아니다.** 등록되고, fingerprint가 찍히고, PIT로 묶이고, 자기 run으로
  돈다(기록 `148`). 평균은 신뢰되는 것이 아니라 **재현되는 것**이다. 앞 문단의 반론이 겨눈 것은 벤더 파일이지
  이것이 아니었다.
- **캡 벡터가 일급 산출물이 된다.** *"그 달에 어느 캡을 썼는가"*가 기록에서 답해진다. constraint 안에서
  유도하면 그 값은 어느 occurrence의 중간 계산으로만 존재하고, 두 run의 캡을 diff할 수 없다.
- **바뀌는 이유가 다른 둘이 분리된다.** 산식(규정 해석)은 DataModel이 소유하고, 판정(범위 안인가)은
  constraint가 소유한다. 규정이 개정되면 DataModel만 바뀌고, 한도 축이 늘면 constraint만 바뀐다.
- **constraint가 순수 조회로 줄어든다.** `RowsLookback(rows=1)` + `latest()` 하나. §9.3의 `months=2` 함정도,
  전월 instant를 골라내는 코드도 constraint에서 사라진다 — **월중 불변이 dataset의 instant 간격 자체가 된다.**
- **비용.** 일별 시총비중 panel을 occurrence마다 두 달치 읽고 평균하는 일이 월 1회로 준다.

**일반화 — 이것은 캡만의 이야기가 아니다.** *정해진 주기로 확정되어 그 사이 불변인 파생값*은 전부 이 모양이다.
constraint 안에서 유도하지 말고 DataModel이 발행하게 하라. constraint는 구독한다. `inputs()`가 그 dataset을
선언하므로 등록되지 않았으면 preflight가 거절한다(`UC-CONSTRAINT-002`) — 결손이 아니라 계약이다(§5).

**우선주는 지금 범위 밖이다 (소유자, 2026-09-04).** §9.8의 보통주 해석으로 충분하고, `max(10%, 전월 일평균
보통주 시총비중)`이 착수 대상이다.
