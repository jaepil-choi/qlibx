# Decision clock과 rebalance trigger — 현재 구조 조사

- 상태: 조사 기록 (thoughts). 결정된 설계가 아니다.
- 대상 브랜치/커밋: `exp/one-shot` @ `7776c6a`
- 계기: "PRD에 전략이 closed loop로 돈다는 것만 있고, 어떤 trigger로 어떤 주기로 도는지가 없다"는 질문.
  구체적으로 minute bar를 consume하면서 조건 충족 시 진입/청산하는 전략, 또는 10분마다 리밸런싱하는
  전략이 지금 qlibx로 구현 가능한지.

## 1. 한 줄 결론

**지금 qlibx에는 trigger도 rebalance 주기도 개념 자체가 없다.** decision clock이 데이터 축에 암묵적으로
붙어 있고, 문서에 그 사실이 적혀 있지 않다.

## 2. Decision clock은 어디서 오는가

단 한 곳이다: **`execution_price` matrix의 `DatetimeIndex`**.

`src/qlibx/_vendor/qlib_backend/backend.py:199`의 루프가 그 index를 순회하며 매 offset마다

1. strategy 호출
2. target weight vector 수령
3. 현재 보유와의 delta로 주문 생성 (`backend.py:382-392`)

을 수행한다. 즉 그 index의 **모든 행 = decision time = execution time = rebalance**다. 셋이 분리되어
있지 않고, 분리할 파라미터도 없다.

`_require_matrix` (`backend.py:913`)가 요구하는 것은 "`DatetimeIndex`이고 unique·정렬됨"뿐이다.
날짜 단위라는 제약은 없다. `_normalize_targets` (`backend.py:925`)는 target index가
execution_price index와 **정확히 일치**할 것을 요구한다. 이것이 두 clock을 묶어버리는 지점이다.

### `clock` 필드는 스케줄러가 아니다

`config/qlibx/execution.yaml`과 `src/qlibx/profiles.py:38`에 `clock`이 있다.

```yaml
clock:
  signal_cutoff: t_minus_1_close
  decision_time: t_close
  execution_time: t_close
  valuation_time: t_close
```

이것은 **semantic label이며 requirement 검증에만 쓰인다.** 어떤 시점도 생성하지 않는다. 현재
프로파일은 `daily_close_v1` 하나뿐이고, `profiles.py:221`은 그 ID가 기본 clock과 일치하는지만 본다.

## 3. 실행 경로가 두 개이고 능력이 다르다

| | manifest 경로 (plain pandas) | adaptive 경로 (`DecisionContext`) |
| --- | --- | --- |
| 진입점 | `run_manifest_strategy_execution` (`strategy_manifest/invocation.py:142`) | `run_strategy_execution(program=...)` (`execution.py:168`) |
| strategy가 보는 것 | canonical pandas input + parameter **뿐** (`invocation.py:110-140`) | + feedback, account, memory, checkpoint (`execution.py:217`, `:270`, `:316`) |
| memory | **없음** | 있음 |
| 데이터 로딩 | decision마다 registered dataset **전량 재로드** (`strategy_manifest/resolution.py:97`, `data.py`에 캐시 없음) | 인메모리 DataFrame을 decision time으로 슬라이스 |

`docs/qlibx-architecture.md` §8은 이 이원화를 의도된 것으로 기술한다("기존 adaptive
`DecisionContext`/`DecisionResult` 경로는 feedback, memory, checkpoint와 Qlib closed loop를 위해 유지한다").
문제는 PRD가 이 구분 없이 **모든 StrategyAgent가 memory와 feedback을 갖는다고 약속한다**는 점이다
(`docs/qlibx-prd.md:69-82`, §7.2 `:1109-1118`). manifest 경로에서는 그 약속이 성립하지 않는다.

## 4. 시나리오별 판정

### 4.1 "10분에 한 번 리밸런싱" — 가능

execution_price / valuation_price / universe 등을 10분봉 index로 등록하면 그것이 곧 decision calendar가
된다. 코드에 daily 하드코딩은 없다. 다만 두 가지 걸림돌:

- **`freq="day"`가 하드코딩되어 있다** (`backend.py:148`, `:1104`, `:1120`). `ScenarioExchange`가
  `get_quote_from_qlib`을 override해서 quote 조회는 우회하므로 체결 자체는 돌지만, Qlib
  `Account`/`portfolio_metrics`의 기간 라벨링이 틀어진다.
- **lookback이 row 수로만 선언된다** (`lookback: {kind: rows, value: 20}`, `strategy_manifest/contracts.py:66`).
  10분봉 20행 = 200분이라는 환산을 사람이 해야 한다. 서로 다른 frequency의 dataset을 섞으면
  role마다 다른 실시간 길이를 갖게 된다.

### 4.2 "minute bar를 consume하되 매분 리밸런싱은 안 함" — 구조적으로 불가

observation clock과 decision clock을 분리할 방법이 없다. 분봉을 보려면 execution 축도 분봉이어야 하고,
그러면 매 분이 rebalance다.

매분 호출해놓고 strategy 내부에서 "10분마다만 바꾼다"로 gating하려면 "지난 리밸런스가 언제였나"를
기억해야 한다. manifest 경로에는 memory가 없으므로 adaptive 경로로 내려가야 한다. 그리고 4.3의
no-op 문제를 그대로 만난다.

### 4.3 "조건 충족 시 즉시 진입 / 청산" (event-driven) — 가장 안 맞음

세 가지 이유가 겹친다.

**(1) no-op 계약이 없다.** 매 bar 반드시 전체 target weight vector를 반환해야 하고, backend는 무조건
delta를 계산해 주문을 낸다. "이번 bar는 아무것도 안 한다"를 표현하려면 *현재 실제 physical weight*를
그대로 되돌려줘야 하는데, 그 값은 adaptive 경로의 account feedback
(`current_physical_weight`, `backend.py:370`)에만 있다. 그러지 않고 "직전에 결정한 weight"를 반복하면
**가격 drift만큼 매 bar 미세 리밸런싱**이 발생하고, lot rounding 때문에 실제 주문까지 나간다
(`_round_target_quantity`). 일봉에서는 잡음이지만 분봉에서는 치명적이다.

**(2) intrabar trigger가 불가능하다.** 결정은 bar 경계에서만 일어난다. "장중 -3% 터치하면 즉시 청산"은
bar를 더 잘게 쪼개는 것 외에 표현할 방법이 없다.

**(3) 종목별 상태를 들고 갈 수 없다.** 언제 진입했나, 쿨다운이 남았나 같은 상태는 memory가 필요하고,
manifest 경로에는 없다. PRD §1.2가 명시적으로 약속한 stop-loss 예시(`qlibx-prd.md:74`)가 바로 이
경우다.

### 4.4 성능

manifest 경로는 decision마다 registered dataset을 `as_of`로 전량 재로드한다
(`resolution.py:97-110`). `data.py`에 캐시가 없다. 일봉 250회/년은 견디지만 분봉 약 10만 회/년은
못 쓴다. adaptive 경로는 인메모리 프레임을 슬라이스하므로 그쪽이 낫다.

## 5. PRD에 빠져 있는 것

1. **Decision clock의 출처와 정의.** PRD는 "decision time"을 반복해서 쓰면서 그것이 어디서 생성되는지
   한 번도 정하지 않는다. 실제로는 execution_price index다.
2. **Observation clock과 decision clock의 분리.** 분봉 관측 / 10분 결정 같은 조합을 지원할지 여부.
3. **Hold(no-op) 결과 계약.** `DecisionResult`가 "이번엔 변경 없음"을 표현할 수 있어야 drift·lot
   rounding으로 인한 의도치 않은 재트레이딩을 막을 수 있다.
4. **Event-driven trigger의 지위.** 지원할지, out of scope로 명시할지. 현재 §2.2는 "기본 closed-loop
   backtest schedule"을 Qlib에 맡긴다고만 하고 넘어간다.
5. **Intraday frequency에서의 lookback 의미**(rows vs duration)와 loader 성능 요구.
6. **manifest 경로와 adaptive 경로의 능력 차이.** PRD가 모든 StrategyAgent에 memory/feedback을
   약속하지만 manifest 경로는 제공하지 않는다. 의도된 축소라면 PRD가 그렇게 말해야 하고,
   갭이라면 채워야 한다.

## 6. 열려 있는 선택지

아직 결정하지 않았다. 두 방향이 비용 차이가 크다.

**A. Dense calendar + hold 반환.** decision calendar를 촘촘하게(예: 분봉) 만들고, strategy가 "변경
없음"을 명시적으로 반환한다. 필요한 변경은 hold 계약 추가와 manifest 경로에 memory/feedback 노출
정도로 국소적이다. 대신 매 bar strategy가 호출되므로 loader 캐싱이 전제가 된다.

**B. Trigger를 1급 개념으로.** decision calendar와 execution calendar를 분리하고 조건부 trigger를
도입한다. `backend.py`의 루프 구조와 `_normalize_targets`의 index 일치 요구를 모두 바꿔야 한다.
intrabar trigger까지 가면 Qlib exchange 계약도 건드려야 한다.

A가 4.1과 4.2를 덮고 4.3을 bar 해상도까지 근사한다. 진짜 intrabar event가 필요한지가 B로 갈지를
가르는 기준이다.
