# 213 — The wiring table is data, and a part is a tool plus a clock

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M13 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md`) — Stage 5 시작 |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §4 (배선표 — 이것이 아키텍처다) · §4.1-4.3 · §10.2 (배선표의 코드 모양: 아직 안 정한 것) |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `212` (One root builder, one account door) |

---

## 왜 이 변경이 있는가

설계 §4는 *"이 표는 프레임워크가 소유하고 닫혀 있다. 확장점을 하나 더 만들려면 배선을 하나 더 만들어야
한다"*고 했는데, 그 표는 문서에만 있었다. §4.2가 짚은 대로 `Component`는 추상 콜백이 없는 얇은 base라
정답이었고, 문제는 진짜 공통 개념(배선: 시계 · 수신자)이 코드 어디에도 한 곳으로 없었다는 것이다.
§4.3의 부품/도구 구분도 docstring에 산문으로만 있었다.

§10.2가 미룬 결정 — **표를 데이터로 둘 것인가, 타입으로 둘 것인가** — 를 여기서 정했다: **둘 다, 각자
한 가지씩.** 표는 데이터다(비교되고 나열되고 세어지는 것). 타입은 코드가 강제해야 하는 구조적 사실
하나 — 부품이냐 도구냐 — 만 나른다.

---

## 무엇이 어떻게 바뀌었는가

### `domain/wiring.py` — 닫힌 표

```python
Role      DATA_MODEL · STRATEGY_MODEL · ACCRUAL · EXCHANGE · COMPLIANCE
Clock     STRATEGY · MARKET
View      WINDOW · ACCOUNT · HISTORY · HOLDINGS · ORDERS · MARKET_STATE · INSTRUMENTS · COMMITTED_ACCOUNT
Receiver  WAREHOUSE · EXCHANGE · LEDGER · EVIDENCE
Wiring(role, clock, receives, answers_to, declares_clock)
WIRING: Mapping[Role, Wiring]        # §4의 다섯 줄, 글자 그대로
MARKET_CLOCK_ORDER = (ACCRUAL, EXCHANGE, COMPLIANCE)   # §3.1
parts() · tools() · roles_on(clock)
```

층 0 — 아무것도 import하지 않는다. `Receiver`는 §5의 목적지 셋(창고·통장·게시판)에 `EXCHANGE` 하나를
더한 것이다: 전략의 답(주문)을 받는 것은 Exchange이고, Exchange의 답이 통장으로 간다(§4 표의 "주문 →
Exchange").

### `Part` · `Tool` — `Component` 아래 두 base

```python
class Part(Component): ...     # 자기 시계를 선언한다. run당 하나.  DataModel · StrategyModel
class Tool(Component): ...     # 남의 시계에 붙는다.               Exchange · Compliance (· Accrual 자리)
Component.ROLE: ClassVar[Role]; Component.wiring() -> Wiring
```

**부품 = 도구 + 시계**(§4.3)가 상속 방향이다. 역할 클래스마다 `ROLE`이 자기 행을 가리키고,
`ComponentKind.role`이 등록 가능한 kind 넷을 행에 잇는다. `ACCRUAL`은 행은 있고 kind도 클래스도 없다 —
자리(§7.3).

### AC-13 — `tests/domain/test_the_wiring_table.py`

- `set(WIRING) == set(Role)`: `Role`을 늘리면 행 없이는 실패한다. 행을 늘리면 `Role` 없이는 실패한다.
- 표가 §4의 다섯 줄과 같다(행마다 시계·View·수신자).
- `parts() == (DATA_MODEL, STRATEGY_MODEL)`, `tools() == (ACCRUAL, EXCHANGE, COMPLIANCE)`; 전략 시계의
  역할은 부품, 시장 시계의 역할은 도구; `DataModel`·`StrategyModel`은 `Part`, `Exchange`·`Compliance`는
  `Tool`, 각자 `wiring()`이 자기 행.
- `ComponentKind` 넷 ↔ `Role` 다섯 − ACCRUAL.
- `_handle_market`의 소스에서 `._accrual.` → `._execution.fill(` → `._compliance.` 순서가
  `MARKET_CLOCK_ORDER`와 같다 — 순서가 코드(AC-8)와 데이터 두 곳에 있고 테스트가 둘을 묶는다.

### 표면

`authoring`·`public`에 `Part`·`Tool` export. export 고정 테스트 둘 갱신(public 튜플은 모듈에서 재생성).

---

## 무엇을 잃었나

- 없다. `Component`의 멤버는 그대로(`memory`·`inputs`·`requirements`); `ROLE`·`wiring()`이 더해졌다.
- 표를 **소비하는** 코드는 아직 테스트뿐이다. 루프는 여전히 순서를 호출로 쓴다(AC-8이 그것을 원한다 —
  "재배열이 눈에 보이는 diff가 되도록"). 표가 루프를 **구동**하게 하는 것은 하지 않았다: 순서표가 코드
  한 곳에 글자로 있는 것이 M7의 결정이고, 표는 그것을 검증한다.

---

## 검증

```
uv run python -m pytest tests/ -q -m ""       1660 passed (207s)
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
scripts/showcase_record_digest.py --check      83/83 — 재기록 없이
```

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **`Receiver.EXCHANGE`는 목적지가 아니라 중계다.** §5는 "목적지는 셋"이라 했고, 표의 "주문 → Exchange"를
  그대로 옮기려면 넷째 값이 필요했다. 셋으로 접으면 전략의 답이 통장으로 간다고 거짓말하게 된다.
- **export 고정 테스트는 모듈에서 재생성한다.** ruff의 isort 순서를 손으로 맞추지 않는다(M8 흔적 재확인).

---

## 다음 기록이 이어받을 것

- **M14 (Stage 5 완료).** 패키지 이름과 배치를 정한다(§10.1); `flow/datamodel`과 `flow/strategy`
  통합(시계가 하나냐 둘이냐만 남는다); `LAYERS` 표 갱신; `OPEN` 비어 있음.
- `domain/wiring.py`는 층 0이다. M14가 패키지를 옮기면 `Role`이 `ComponentKind`를 대체할 수 있다 —
  값이 같고(`Role(kind.value)`), 하나가 다른 하나의 부분집합이다.
