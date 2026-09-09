# 두 시계 캠페인 — 배선표를 문서에서 코드로 옮긴다

> **완료 (2026-09-10).** Stage 0-5 전부, records `201`-`214`. 설계 §8이 PRD·아키텍처에 흡수됐다. ExecPlan은
> `.agent/plans/completed/two-clocks-campaign.md`에 있다.

레이어링 캠페인(records `190`-`198`)이 트리를 DAG으로 만들었다. 이 캠페인은 그 위에서 **경계가
옳은지**를 묻는다. 무엇을 어떤 순서로 할 것인가.

**설계 근거는 이 문서가 아니라 [`docs/design/two-clocks-and-the-wiring-table.md`](../design/two-clocks-and-the-wiring-table.md)에 있다.**
왜 그렇게 정했는가는 거기, 무엇을 어떤 순서로 하는가는 여기, 어디까지 갔는가는
[`.agent/plans/completed/two-clocks-campaign.md`](../../.agent/plans/completed/two-clocks-campaign.md)에.

---

## 0. 소유자 결정

1. **breaking change 허용.** 사용자 확장점 계약이 바뀐다 — `Constraint`가 확장점에서 빠지고
   `Compliance`가 들어온다. major 경계로 나간다.
2. **`writes`는 필수다.** 안 적으면 창고에 안 들어간다.
3. **run은 전략 하나다.** `strategies:` 배열이 선언에서 사라진다.
4. **Compliance는 전략의 값을 물려받지 않는다.** 독립 파라미터를 갖는다.
5. **Accrual은 자리만 만든다.** 배당 · 대차수익 · funding · 정산은 MVP 밖.
6. **패키지 이름은 마지막에 정한다.** 무엇을 하는지가 끝난 뒤에.

---

## 1. 왜 지금인가

0.9.0의 트리는 순환이 없다. 그런데 **매 분 판단하고 매 분 체결하는 전략이 표현되지 않는다.**

```text
FillConvention    selector(SAME_DAY | NEXT_ELIGIBLE) + local_time + timezone
                  resolve_local_target(day) 가 날짜당 시각 하나를 만든다
                  → execution table 에 390 점이 있어도 convention 은 1 점만 본다
```

매 분 판단 전략(agenda 09:00~15:29)을 지금 어휘로 돌리면:

```text
09:00 ~ 15:19 의 320 번 판단이 전부 같은 15:20 을 노린다 → pending 이 서로를 교체한다
15:20 에 체결 1 회.  마지막 intent 만 살아남는다
15:21 부터 129 번은 execution_time <= decision_time → 콜백 실패
```

**모델은 이걸 이미 지원한다.** 동일 시각 우선순위(체결 → 반영 → 평가 → 판단), 최소 간격
(`execution_time > decision_time`), pending 교체 규칙이 전부 옳다. **빠진 것은 어휘 하나다.**

그 어휘를 고치는 과정에서 시계가 몇 개여야 하는지가 정리됐고, 그것이 이 캠페인의 나머지다.

---

## 2. Stage 0 — 확정과 기준선 (코드 변경 없음)

| | |
|---|---|
| 0a | 설계 문서 확정 — 완료 (`docs/design/two-clocks-and-the-wiring-table.md`) |
| 0b | 캠페인 문서 확정 — 이 문서 |
| 0c | 뒤집히는 PRD·아키텍처 절을 설계 문서 §8에 기록 — 완료 |
| 0d | ExecPlan 작성 — 완료 (`.agent/plans/completed/two-clocks-campaign.md`) |
| 0e | showcase 8개의 record를 회귀 기준선으로 캡처 |

**착수 전 측정은 하지 않는다** (소유자 결정 2026-09-09). Stage 4의 근거는 *"불변식이 세 벌에서 한
벌이 된다"*이고 그것은 구조적 사실이지 재서 정할 일이 아니다. 실제 감소량은 Stage 4가 끝난 뒤
ExecPlan의 `Progress`에 기록한다.

**0e는 측정이 아니라 검증 자산이다.** Stage 2와 4가 척추를 바꾸므로, 같은 선언이 같은 record를
남기는지 대조할 기준이 필요하다.

---

## 3. Stage 1 — 선언과 preflight (척추 안 건드림)

| | 내용 | 건드리는 곳 |
|---|---|---|
| 1a | `writes` 필수 · 이름만 · 그래프 관계 저장 | 선언 문서 · `project/` · `flow/declaration/preflight.py` |
| 1b | run 선언에서 `strategies:` 배열 제거. run = 전략 하나 | 선언 문서 · `project/run.py` · `flow/orchestration.py` |
| 1c | agenda 어휘 `every`/`from`/`to`/`at`. preflight가 execution table의 거래일 위에서 전개 | 선언 · `preflight.py` · `domain/agendas.py` |
| 1d | 체결 시각 어휘: 기본 "결정 이후 첫 시장 시계 점" + `at`/`after`/`within` | `exchange/conventions.py` · `preflight.py` |
| 1e | instrument 선언 0개면 preflight 거부 | `preflight.py` · `flow/roster.py` |

**왜 먼저인가.** 다섯 다 값과 판정이지 실행 경로가 아니다. `tests/boundaries/test_the_layers_hold.py`가
그대로 지켜 주고 되돌리기 쉽다. 그리고 **1c·1d 없이는 Stage 2를 검증할 수 없다** — 매 분 전략을
표현할 수 없으면 시장 시계가 제대로 도는지 확인할 방법이 없다.

**완료 판정.** 매 분 판단 · 매 분 체결 전략이 showcase로 돌아간다. `test_all` 통과.

---

## 4. Stage 2 — 시계 둘과 단계 재배치 (척추)

| | 내용 |
|---|---|
| 2a | 시장 시계를 1급 이벤트 소스로. execution table의 모든 instant |
| 2b | VALUATION을 시장 시계 위 단계로. **`PendingValuation` 제거** |
| 2c | Hold가 아무것도 예약하지 않게 |
| 2d | 단계 순서 고정: ACCRUE(빈 자리) → EXECUTE → VALUATION → COMPLIANCE → DECIDE |
| 2e | pending 슬롯이 체결 대기만 담게 |

**건드리는 곳.** `flow/engine/loop.py` · `flow/strategy/{loop,callback,valuation}.py` ·
`flow/engine/run_state.py`

**위험.** 이 캠페인에서 가장 크다. 동일 시각 우선순위와 pending 의미가 바뀐다.

**완료 판정.** `test_all` 통과 + showcase 8/8 + **기존 run의 record 회귀 비교** — 같은 선언으로 돌린
run이 같은 record를 남기는지.

---

## 5. Stage 3 — 역할 재편 (사용자 영향)

| | 내용 |
|---|---|
| 3a | `Constraint` 확장점 제거. built-in 둘을 순수 함수로 이동 |
| 3b | `Compliance` 신설. 시장 시계, VALUATION 직후, 구독 + 기억, 독립 파라미터 |
| 3c | `Exchange` 계약 좁힘: 주문 + 시장상태 + 계좌 + **종목 사전** |
| 3d | 미등록 종목 주문 → runtime 실패. 미등록 종목을 **전부 모아서** 보고 |
| 3e | venue 설정(규칙 on/off) 스키마를 venue가 소유 |

**건드리는 곳.** `authoring/component.py` · `constraints/`(해체) · `exchange/venue.py` ·
`exchange/venues/krx.py` · `extension/` · `flow/strategy/{callback,valuation}.py`

**사용자 영향이 가장 큰 단계다.** `Constraint`를 쓰던 코드가 전부 바뀐다. 시점상 major 버전 경계이며,
shipped skills · scaffold · showcase가 함께 움직인다.

**완료 판정.** enhanced-index showcase가 순수 함수 + Compliance 조합으로 같은 결과를 낸다.

---

## 6. Stage 4 — 통장 (척추)

| | 내용 |
|---|---|
| 4a | `LedgerEntry` 한 모양 (`at` · `cash` · `positions` · `origin` · `detail`) |
| 4b | `Account` = append 권한. 결과 상태만 검사, 출처별 불변식은 생산자가 |
| 4c | `Prepared*` 셋 → 하나 |
| 4d | `flow/freeze.py` 축소 — 엔진 값과 record 모델이 같은 사실이 된다 |
| 4e | ACCRUE 단계에 빈 handler. 구현 없음 |

**건드리는 곳.** `account/` · `domain/account_state.py` · `flow/engine/run_state.py` ·
`flow/freeze.py` · `record/`

**Stage 2 뒤에 오는 이유.** 시계가 정리되기 전에 통장을 고치면 두 큰 변경이 겹친다. Stage 2가
`PendingValuation`을 없애 놓으면 통장에 붙는 경로가 이미 단순해져 있다.

**완료 판정.** 기준선 record 회귀 비교. 실제 감소량을 ExecPlan `Progress`에 기록한다 — 예측이
빗나갔으면 그 사실도.

---

## 7. Stage 5 — 구조

| | 내용 |
|---|---|
| 5a | 배선표를 코드로. `Role` base 얇게 (구독 + 기억 + 콜백 하나) |
| 5b | 부품/도구 구분을 타입에 |
| 5c | 패키지 재배치. **이름은 Stage 4 완료 시점에 결정** |
| 5d | `flow/datamodel`과 `flow/strategy` 통합 — 시계가 하나냐 둘이냐의 차이만 남는다 |

**마지막인 이유.** 의미가 다 정해진 뒤에 이름과 위치를 정한다. 반대로 하면 이름을 두 번 바꾼다.
아키텍처 §10이 적은 *"이름이 무엇을 하는지를 말하는가"* 를 지키려면 무엇을 하는지가 먼저 끝나야 한다.

---

## 8. 순서와 위험

```text
0 ─── 1 ─────── 2 ─────── 3 ─────── 4 ─────── 5
      │         │         │         │         │
      안전      척추      사용자     척추      기계적
      되돌리기  회귀비교  major     회귀비교  이름만
      쉬움      필수      경계      필수
```

**2와 4 사이에 3을 끼운 이유:** 척추 변경 둘을 연속으로 하지 않는다. 사이에 역할 재편을 넣어 각
척추 변경이 독립적으로 검증되게 한다.

**각 Stage는 독립적으로 착지 가능해야 한다.** Stage 1까지만 하고 멈춰도 트리는 일관되고, 매 분
전략이 표현된다.

---

## 9. 게이트

```text
매 Stage   uv run pytest tests/ -q -m ""     (test_all)
           uv run ruff check src/
           uv run pyright
Stage 2·4  기존 run 의 record 회귀 비교
Stage 3    showcase 8/8 + shipped skills · scaffold 갱신
```

`tests/boundaries/test_the_layers_hold.py`의 `OPEN`은 비어 있고 그대로 비어 있어야 한다. 한 Step이
간선을 열어야 하면 그 표에 적고 같은 커밋에서 닫는다.

---

## 10. 범위 밖

```text
Accrual 구현            Stage 4e 는 자리만
origin 구조화           지금은 라벨
다중 venue              run 당 Exchange 하나
partial fill · child order · TWAP     PRD §13 그대로
live                    아키텍처 §15-5 그대로
```

---

## 11. 진행

| Stage | 상태 | 기록 |
|---|---|---|
| 0 | 문서 · ExecPlan 확정 완료. 0e 기준선 미착수 | |
| 1 | 미착수 | |
| 2 | 미착수 | |
| 3 | 미착수 | |
| 4 | 미착수 | |
| 5 | 미착수 | |
