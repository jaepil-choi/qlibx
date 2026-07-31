# Qlib native lifecycle을 더 깊게 활용하는 qlibx 실행 구조 조사

- 상태: 조사·설계 제안. 승인된 PRD 또는 구현 명세가 아니다.
- 조사 기준 qlibx commit: `f22fa12`
- 조사 기준 Qlib: `pyqlib==0.9.7`
- Qlib release: [`v0.9.7`](https://github.com/microsoft/qlib/releases/tag/v0.9.7)
- 정본 제품 문서: [`docs/qlibx-prd.md`](../qlibx-prd.md)
- 작성 목적: qlibx가 Qlib의 native Strategy/Executor/Account lifecycle을 더 많이 재사용하고,
  qlibx 고유 책임을 point-in-time Strategy contract와 hypothetical signed execution compatibility로
  축소할 수 있는지 fact-check한다.

## 1. 판정 기준

이 문서는 주장을 세 종류로 구분한다.

- **확인된 사실**: 현재 qlibx source, test, 정본 PRD 또는 설치된 Qlib 0.9.7 source에서 직접 확인된다.
- **분석적 추론**: 확인된 계약에서 논리적으로 도출되지만 아직 구현·실험으로 검증되지 않았다.
- **권고**: 목표 구조 또는 이행 순서에 관한 설계 판단이다.

`references/`는 `.agent/project.yaml`에서 non-authoritative directory로 선언되어 있으므로 근거로 사용하지
않았다. Qlib source line은 repository의 `.venv/Lib/site-packages/qlib/`에 설치된 0.9.7 source와 공식
`v0.9.7` tag를 함께 대조했다.

### 1.1 이번 조사에서 실제로 검증한 것

다음 명령으로 현재 qlibx의 Qlib closed-loop, adaptive Strategy feedback, signed execution과
checkpoint/resume test를 다시 실행했다.

```powershell
$env:UV_CACHE_DIR='<repository>/.agent/runs/uv-cache-deeper-integration'
uv run --locked pytest -q -p no:cacheprovider `
  --basetemp '<repository>/.agent/runs/pytest-deeper-integration' `
  tests/test_qlib_closed_loop.py `
  tests/test_strategy_qlib_integration.py `
  tests/test_signed_execution_journey.py
```

결과는 `12 passed`였다. Qlib/NumPy timedelta deprecation warning과 pandas future warning은 있었지만
test failure는 없었다.

이 결과가 증명하는 것은 **현재 backend의 동작**이다. 이 문서가 제안하는 native-first 구조는 아직
구현되지 않았으므로 이 test 결과를 새 구조의 검증으로 오해하면 안 된다.

## 2. 요약 결론

### 2.1 확인된 사실

현재 qlibx는 Qlib의 `Account`, `Position`, `Order`와 `Exchange.deal_order`를 사용하지만, Qlib native
`BaseStrategy -> TradeDecision -> Executor -> Account bar-end update` lifecycle은 사용하지 않는다.
qlibx의 `QlibClosedLoopBackend.run_targets`가 다음을 직접 수행한다.

1. decision calendar 순회
2. Strategy callback 호출
3. weight를 target quantity로 변환
4. current quantity와 target quantity의 차이 계산
5. Qlib `Order` 생성
6. `Exchange.deal_order` 직접 호출
7. order/fill/position/account/feedback row 직접 조립
8. qlibx 전용 checkpoint 생성

근거:

- `src/qlibx/_vendor/qlib_backend/backend.py:199-215`
- `src/qlibx/_vendor/qlib_backend/backend.py:357-411`
- `src/qlibx/_vendor/qlib_backend/backend.py:537-575`
- `src/qlibx/_vendor/qlib_backend/backend.py:638-668`

반면 Qlib 0.9.7에는 이미 다음 lifecycle이 있다.

- Trading bar마다 `BaseStrategy.generate_trade_decision(previous_execute_result)` 호출
- `BaseTradeDecision`/`TradeDecisionWO`를 `SimulatorExecutor`가 실행
- `Exchange.deal_order`가 Qlib Account를 변경
- Executor가 bar-end valuation, position history와 metrics를 갱신
- Empty order list를 정상적인 no-op decision으로 취급

근거:

- Qlib 0.9.7 `qlib/backtest/backtest.py:83-93`
  ([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/backtest/backtest.py#L83-L93))
- Qlib 0.9.7 `qlib/strategy/base.py:67-77,132-146`
  ([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/strategy/base.py#L67-L77))
- Qlib 0.9.7 `qlib/backtest/executor.py:273-303,590-609`
  ([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/backtest/executor.py#L273-L303))
- Qlib 0.9.7 `qlib/backtest/decision.py:508-516,547-570`
  ([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/backtest/decision.py#L508-L570))

### 2.2 분석적 판정

따라서 qlibx가 Qlib의 native lifecycle을 충분히 활용하지 못한다는 진단은 맞다. 현재 구조는 Qlib
execution engine을 사용한다기보다 Qlib의 account/exchange primitive를 qlibx loop 안에서 호출한다.

그러나 "DRY이므로 무조건 더 빠르다"는 결론은 성립하지 않는다.

- Native Qlib generic loop가 현재의 단순한 matrix loop보다 runtime overhead가 클 수 있다.
- 개선이 확실한 영역은 execution lifecycle 중복 제거, 유지보수성, Qlib semantics와의 정렬이다.
- 속도 개선 여부는 동일 scenario에 대한 benchmark로 별도 검증해야 한다.

### 2.3 권고

목표 구조는 **Qlib native lifecycle + 얇은 qlibx Strategy adapter + optional matched-endowment
translator**가 적절하다.

Qlib이 calendar, TradeDecision, order execution, fill, Position, Account와 bar-end valuation을 소유하고,
qlibx는 다음만 소유한다.

- PIT data boundary와 Strategy manifest/binding
- immutable account snapshot
- trigger와 Strategy memory
- mandatory finalization과 pre-trade reconciliation
- signed active position을 Qlib-compatible non-negative composite position으로 변환하는 compatibility
  adapter
- qlibx artifact, audit와 checkpoint materialization

## 3. 현재 qlibx가 Qlib lifecycle을 중복하는 지점

### 3.1 qlibx가 직접 bar를 순회한다

현재 backend는 weight matrix의 index를 직접 순회한다.

```python
for offset in range(start_position, stop_position):
    date = pd.Timestamp(weights.index[offset])
    price = market["execution_price"].loc[date]
```

출처: `src/qlibx/_vendor/qlib_backend/backend.py:199-203`

이 loop는 Qlib `collect_data_loop`가 이미 수행하는 trading-bar 순회와 책임이 겹친다.

### 3.2 qlibx가 Strategy output을 직접 target quantity로 변환한다

Long-only path에서 qlibx는 매 bar의 current NAV와 execution price로 weight를 다시 수량화한다.

```python
raw_target_physical = _raw_target_quantity(weights.loc[date], pretrade_nav, price)
target_physical = _round_target_quantity(raw_target_physical, lot_size)
delta = target_adjusted - current_adjusted
```

출처: `src/qlibx/_vendor/qlib_backend/backend.py:382-386`

이 구조는 같은 target weight를 반복하면 price drift와 NAV 변화 때문에 target quantity가 다시 계산되는
문제를 만든다. "이번 bar에는 아무것도 하지 않는다"와 "현재 weight를 다시 맞춘다"가 같은 payload로
표현된다.

관련 조사:

- `docs/thoughts/decision-clock-and-rebalance-trigger.md:83-99`
- `docs/thoughts/constraint-limits-and-the-monitoring-clock.md:230-243`

### 3.3 qlibx가 Qlib order를 직접 만들어 실행한다

현재 backend는 delta에서 Qlib `Order`를 만들고 `ScenarioExchange.deal_order`를 직접 호출한다.

출처:

- `src/qlibx/_vendor/qlib_backend/backend.py:388-411`
- `src/qlibx/_vendor/qlib_backend/backend.py:424-479`

Qlib `SimulatorExecutor`도 같은 역할을 수행한다.

```python
for order in self._get_order_iterator(trade_decision):
    trade_val, trade_cost, trade_price = self.trade_exchange.deal_order(...)
```

출처: Qlib 0.9.7 `qlib/backtest/executor.py:590-609`
([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/backtest/executor.py#L590-L609))

### 3.4 qlibx가 account history를 직접 조립한다

현재 backend는 Qlib Position을 읽은 뒤 별도 `position_rows`, `account_rows`, `feedback_rows`를 만든다.

출처:

- `src/qlibx/_vendor/qlib_backend/backend.py:537-575`
- `src/qlibx/_vendor/qlib_backend/backend.py:638-668`

Qlib Executor는 실행 후 `Account.update_bar_end`를 호출하고, Account는 current position price, account
value, cash, turnover, cost와 position history를 갱신한다.

출처:

- Qlib 0.9.7 `qlib/backtest/executor.py:283-303`
- Qlib 0.9.7 `qlib/backtest/account.py:225-301`
  ([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/backtest/account.py#L225-L301))

qlibx artifact schema가 Qlib raw metrics보다 더 풍부할 수는 있다. 그러나 Qlib state를 다시 계산하기보다
Qlib state를 읽어서 qlibx artifact로 **adapt**하는 편이 책임 분리에 맞다.

## 4. Qlib native Strategy가 실제로 제공하는 것

### 4.1 Strategy가 Qlib Position과 Exchange를 볼 수 있다

Qlib `BaseStrategy`는 `trade_position`과 `trade_exchange` property를 제공한다.

출처: Qlib 0.9.7 `qlib/strategy/base.py:67-77`

따라서 qlibx adapter가 Qlib Position과 declared valuation source에서 immutable `AccountSnapshot`을
만드는 것은 native contract와 충돌하지 않는다.

중요한 경계는 다음과 같다.

- User의 pandas Strategy callable이 Qlib object를 직접 보게 해서는 안 된다.
- qlibx가 소유한 `BaseStrategy` adapter만 Qlib Position/Exchange를 읽는다.
- Adapter는 canonical pandas input과 immutable account snapshot으로 user Strategy를 호출한다.

이 구분을 지켜야 현재 Strategy manifest의 pure pandas boundary를 유지할 수 있다.

근거:

- `src/qlibx/strategy_manifest/invocation.py:90-139`
- `docs/qlibx-architecture.md:571-589`

### 4.2 이전 실행 결과가 다음 Strategy call로 전달된다

Qlib loop의 핵심은 다음 순서다.

```python
decision = trade_strategy.generate_trade_decision(execute_result)
execute_result = yield from trade_executor.collect_data(decision, level=0)
trade_strategy.post_exe_step(execute_result)
```

출처: Qlib 0.9.7 `qlib/backtest/backtest.py:87-93`

이는 qlibx PRD의 "다음 decision은 requested target이 아니라 actual holding을 본다"는 계약과 정합한다.

근거:

- `docs/qlibx-prd.md:1207-1214`
- `tests/test_strategy_qlib_integration.py:66-89`

Qlib의 `execute_result`만으로 qlibx feedback contract 전체가 충족되는 것은 아니다. qlibx adapter는
execute_result와 authoritative Qlib Position/Account snapshot을 결합해야 한다.

### 4.3 Empty order list는 native hold다

Qlib `BaseTradeDecision.empty()`는 order가 없거나 모든 order amount가 0이면 empty로 판정한다.

출처: Qlib 0.9.7 `qlib/backtest/decision.py:508-516`

`TradeDecisionWO([])`는 실행할 order가 없는 유효한 decision이다.

출처: Qlib 0.9.7 `qlib/backtest/decision.py:547-570`

따라서 qlibx의 hold를 "현재 weight를 다시 반환"으로 표현할 필요가 없다.

```text
trigger false
-> target state = current confirmed state
-> intended order delta = 0
-> TradeDecisionWO([])
-> Qlib bar-end valuation은 계속 진행
```

이 구조는 price drift로 인한 불필요한 rebalance 없이 일별 account state와 monitoring row를 만들 수 있다.

### 4.4 Initial stock position을 지원한다

Qlib `Account` constructor는 initial cash뿐 아니라 `position_dict`도 받는다.

출처:

- Qlib 0.9.7 `qlib/backtest/account.py:79-124`
  ([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/backtest/account.py#L79-L124))
- Qlib 0.9.7 `qlib/backtest/__init__.py:113-174`
  ([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/backtest/__init__.py#L113-L174))

따라서 fixed baseline inventory를 Qlib Account의 initial composite position으로 넣는 static endowment
mode는 Qlib public construction contract 안에서 구현 가능하다.

그러나 initial position support만으로 올바른 performance accounting이 자동 보장되지는 않는다.
`Account.init_vars`는 constructor의 `init_cash`를 `self.init_cash`와 Position의 available cash 양쪽에
사용한다.

출처: Qlib 0.9.7 `qlib/backtest/account.py:111-124`

그리고 첫 portfolio metric 계산은 prior account value로 `self.init_cash`를 사용한다.

출처: Qlib 0.9.7 `qlib/backtest/account.py:250-270`
([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/backtest/account.py#L250-L270))

따라서 constructor에 "endowment 매입 후 남은 cash"와 initial positions를 넣기만 하면
`self.init_cash`가 total starting NAV보다 작아져 첫 return denominator가 잘못될 수 있다. Static
endowment adapter는 최소한 다음을 별도로 검증해야 한다.

- Starting composite NAV = initial cash + initial position market value
- Qlib portfolio metric의 initial denominator = starting composite NAV
- Baseline NAV + active NAV = starting composite NAV

현재 qlibx resume path도 Qlib Account를 cash/position으로 복원한 뒤 `account.init_cash`를 직전 NAV로
명시적으로 다시 설정한다.

출처: `src/qlibx/_vendor/qlib_backend/backend.py:1108-1127`

### 4.5 표준 Position은 negative quantity를 허용하지 않는다

Qlib `Position._sell_stock`은 보유량보다 많이 팔아 amount가 음수가 되면 `ValueError`를 발생시킨다.

출처: Qlib 0.9.7 `qlib/backtest/position.py:352-374`
([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/backtest/position.py#L352-L374))

이것이 qlibx가 signed active intent를 non-negative composite position으로 바꾸는 compatibility layer를
필요로 하는 직접적인 이유다.

## 5. Qlib `WeightStrategyBase`를 그대로 사용하면 충분한가

### 5.1 확인된 사실

Qlib `WeightStrategyBase.generate_trade_decision`은 다음을 이미 수행한다.

1. signal 조회
2. current Position 복사
3. score에서 target weight 생성
4. `OrderGenerator`로 target weight를 order list로 변환
5. `TradeDecisionWO` 반환

출처: Qlib 0.9.7 `qlib/contrib/strategy/signal_strategy.py:345-372`
([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/contrib/strategy/signal_strategy.py#L345-L372))

이는 "weight를 order로 바꾸는 책임은 Strategy layer에 있다"는 방향을 뒷받침한다.

### 5.2 그대로 재사용할 때의 계약 충돌

Qlib 기본 order generator는 qlibx의 explicit cash와 clock semantics를 그대로 만족하지 않는다.

#### `OrderGenWInteract`

- Current tradable value와 cash를 합친다.
- `risk_degree`로 reserved cash를 정한다.
- cost를 대략 차감한다.
- `generate_amount_position_from_weight_position`을 호출한다.

출처: Qlib 0.9.7 `qlib/contrib/strategy/order_generator.py:90-139`
([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/contrib/strategy/order_generator.py#L90-L139))

그 helper는 tradable weight 합으로 다시 나눈 뒤 배분하므로 supplied cash를 tradable target에 모두
배분한다.

출처: Qlib 0.9.7 `qlib/backtest/exchange.py:534-587`
([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/backtest/exchange.py#L534-L587))

따라서 `sum(stock_weight) < 1`의 차이를 명시적 cash residual로 보존한다는 qlibx 계약과 같지 않다.

#### `OrderGenWOInteract`

Target amount 계산에 prediction-date close 또는 current Position에 기록된 price를 사용한다.

출처: Qlib 0.9.7 `qlib/contrib/strategy/order_generator.py:184-217`
([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/contrib/strategy/order_generator.py#L184-L217))

이는 valid한 한 timing convention이지만, qlibx의 execution profile이 선언한 valuation price, sizing
price와 execution price를 자동으로 보존하지 않는다.

### 5.3 분석적 판정

`WeightStrategyBase`의 **역할 배치**는 재사용할 가치가 있지만 기본 order generator의 수치 semantics를
그대로 채택해서는 안 된다.

권장 방식은 다음 중 하나다.

1. `BaseStrategy`를 직접 감싼 `QlibxStrategyAdapter`가 reconciled target position과 order를 만들고
   `TradeDecisionWithDetails`를 반환한다.
2. Qlib `OrderGenerator` interface를 따르는 qlibx generator를 만들되 explicit target cash,
   valuation/sizing convention, lot rounding과 reconciliation evidence를 추가한다.

첫 번째가 contract가 더 명확하다. Qlib `Exchange.generate_order_for_target_amount_position` 같은 작은
helper는 재사용할 수 있지만, 해당 함수 자체가 trade-date information을 사용한다고 명시하므로 clock
profile과 함께 검증해야 한다.

출처: Qlib 0.9.7 `qlib/backtest/exchange.py:611-677`
([upstream](https://github.com/microsoft/qlib/blob/v0.9.7/qlib/backtest/exchange.py#L611-L677))

## 6. 현재 matched-capitalization의 정확한 성격

### 6.1 회계 identity

현재 PRD의 signed compatibility contract는 다음과 같다.

```text
A = realized signed active quantity
B = matched baseline/endowment quantity, B >= 0
C = Qlib composite quantity, C >= 0

C = B + A
A = C - B
```

출처: `docs/qlibx-prd.md:1582-1597`

Qlib Account에는 `C`만 존재한다. `B`는 qlibx baseline record이며, realized `A`는 Qlib dealt quantity가
반영된 `C`에서 복원한다. 별도의 authoritative signed fill ledger는 두지 않는다.

### 6.2 현재 구현은 initial-only가 아니라 dynamic endowment다

현재 backend는 negative intent가 발생하면 필요한 baseline quantity를 계산한다.

출처:

- `src/qlibx/_vendor/qlib_backend/backend.py:275-284`
- `src/qlibx/_vendor/qlib_backend/backend.py:1018-1039`

부족한 baseline은 Qlib `Position.update_order`를 직접 호출하여 zero-cost capitalization event로 추가한다.
이 호출은 Qlib `Exchange` fill이 아니다.

출처: `src/qlibx/_vendor/qlib_backend/backend.py:1042-1067`

`active-short-only` policy에서는 actual cover 이후 불필요한 baseline을 release한다.

출처: `src/qlibx/_vendor/qlib_backend/backend.py:494-532`

따라서 현재 구조의 복잡성은 단순히 "Qlib이 short를 지원하지 않는다"에서 끝나지 않는다. Dynamic
universe와 시점별 short capacity를 유지하기 위해 Qlib market lifecycle 밖의 administration event를
같은 loop에 넣은 결과다.

### 6.3 현재 reconciliation

qlibx는 다음을 별도로 검사한다.

- Ticker별 `A = C - B`
- `C >= 0`
- `composite NAV = baseline NAV + active NAV`
- capitalization event가 NAV-neutral인지

출처:

- `src/qlibx/execution.py:442-479`
- `src/qlibx/_vendor/qlib_backend/backend.py:339-345`
- `tests/test_signed_execution_journey.py:113-126`

이 검사는 native Qlib integration으로 전환해도 제거하면 안 된다. Qlib은 composite account만 알기
때문에 baseline/active identity 검사는 qlibx 고유 책임이다.

## 7. Static initial endowment mode

### 7.1 정의

Static mode는 run 시작 전에 ticker별 fixed baseline quantity \(B_i\)를 정한다. Initial active position이
0이라면 Qlib initial composite quantity는 \(C_{i,0}=B_i\)다.

각 decision에서 Strategy가 active target \(A_i^*\)를 만들면:

\[
C_i^* = B_i + A_i^*
\]

를 Qlib-compatible target으로 사용한다. 반드시:

\[
B_i \ge 0,\qquad C_i^* \ge 0
\]

이어야 한다.

Qlib execution 이후 realized active position은:

\[
A_i^{realized}=C_i^{realized}-B_i
\]

로 복원한다.

이 section의 식은 현재 PRD의 accounting identity와 Qlib initial-position support에서 도출한
**분석적 설계**이며 아직 native Qlib loop에서 구현 검증되지 않았다.

### 7.2 장점

- Run 중 Qlib Account에 administration position mutation을 하지 않는다.
- Qlib native `BaseStrategy`, `TradeDecision`, `SimulatorExecutor`, Account valuation을 그대로 사용할 수
  있다.
- Baseline ledger가 fixed이므로 checkpoint identity가 단순해진다.
- Partial fill과 blocked trade는 Qlib composite Position에만 반영되고 active holding은 항상 `C-B`로
  복원된다.
- Hold는 empty order decision으로 표현할 수 있다.
- Dynamic activation/top-up/release journal이 없어져 current manual backend의 상당 부분을 제거할 수 있다.

단, 위 장점은 starting composite NAV와 Qlib metric denominator를 올바르게 초기화한다는 조건부
판정이다. Qlib Account constructor의 기본 initial-cash semantics를 그대로 두면 첫 performance row가
왜곡될 수 있다.

### 7.3 중요한 한계: baseline은 weight capacity가 아니라 quantity capacity다

Short weight cap이 active NAV의 \(r_i\)라면 필요한 active short quantity는:

\[
|A_i^*|=\frac{r_iV_A}{p_i}
\]

다음 변화는 필요한 quantity를 증가시킨다.

- Active NAV \(V_A\) 상승
- 해당 종목 가격 \(p_i\) 하락
- Short cap \(r_i\) 증가
- Lot/factor 또는 corporate action 변화

예를 들어 active NAV가 10억 원, per-name short cap이 5%, initial price가 100,000원이면 baseline
capacity는 500주다. 가격이 50,000원으로 하락한 뒤에도 5% short weight를 만들려면 1,000주가 필요하다.
Initial 500주는 더 이상 충분하지 않다.

따라서 static mode는 다음 중 하나를 명시해야 한다.

- ticker별 fixed maximum short quantity
- stress-tested active NAV ceiling과 price floor
- capacity breach 시 명시적 failure

`C_i^* < 0`을 silent clipping하면 requested signed strategy와 실행 strategy가 달라지므로 기본 동작으로
허용하면 안 된다.

### 7.4 Universe 제한

Run 시작 시 endowment universe에 없던 ticker는 baseline \(B_i=0\)이다. Qlib Position이 negative
quantity를 허용하지 않으므로 새 ticker의 negative active target은 실행할 수 없다.

따라서 static mode는 다음을 선언해야 한다.

- Fixed endowment universe
- Universe 밖 ticker short 금지
- Corporate action/factor에 대한 baseline/composite 동시 조정
- Capacity breach status와 offending ticker

Dynamic universe가 핵심 요구라면 static mode만으로는 충분하지 않다.

### 7.5 경제적 의미

Static matched endowment는 native borrow를 모델링하지 않는다.

- Locate/borrow availability 없음
- Margin과 collateral 없음
- Recall/forced buy-in 없음
- Borrow fee 없음
- Baseline reserve opportunity cost가 별도임

Composite account return을 active strategy return으로 사용해서도 안 된다. Baseline quantity의
mark-to-market PnL을 제거한 active PnL과 active denominator가 필요하다.

근거:

- `docs/qlibx-prd.md:1642-1659`
- `src/qlibx/execution.py:487-507`

따라서 명칭은 계속 **hypothetical signed compatibility** 또는 **static matched endowment**여야 한다.
Native short라는 표현은 사실과 다르다.

## 8. Static과 dynamic mode 비교

| 항목 | Static initial endowment | Dynamic matched capitalization |
| --- | --- | --- |
| Baseline 결정 | Run 시작 전 고정 | Short 필요 시 추가, policy에 따라 release |
| Qlib Account 초기화 | Initial `position_dict` | Initial cash 후 Position 직접 mutation |
| Native Qlib lifecycle 적합성 | 높음 | Administration hook 필요 |
| Dynamic universe | 제한됨 | 지원 가능 |
| NAV/가격 변화에 따른 capacity 증가 | 자동 대응 안 됨 | 필요 시 top-up |
| Journal 복잡성 | 낮음 | activation/top-up/release journal 필요 |
| Reserve 효율 | 낮을 수 있음 | 필요한 시점에만 사용 가능 |
| 연구 목적 | Bounded hypothetical long-short | Adaptive/dynamic signed compatibility |
| Native borrow realism | 없음 | 없음 |

권고는 static mode를 native-first 경로의 1차 구현으로 삼고, dynamic mode는 실제 capacity breach와
dynamic-universe 요구가 확인될 때만 별도 compatibility extension으로 유지하는 것이다.

## 9. 권장 native-first architecture

### 9.1 전체 흐름

```text
Qlib trade calendar
-> QlibxStrategyAdapter.generate_trade_decision(previous_execute_result)
   -> immutable Qlib account snapshot
   -> bounded PIT input resolve
   -> trigger
      -> false: empty TradeDecision
      -> true:
         signal -> weight
         -> mandatory finalization
         -> target active position + target cash
         -> signed mode: C_target = B + A_target
         -> intended-order reconciliation
         -> TradeDecisionWithDetails
-> Qlib SimulatorExecutor
-> ScenarioExchange
-> Qlib Account/Position bar-end update
-> QlibxStrategyAdapter.post_exe_step(actual execute_result)
-> qlibx artifact + checkpoint + signed reconciliation
```

### 9.2 `QlibxStrategyAdapter`

권고 책임:

- Qlib `BaseStrategy`를 상속하거나 동등한 native adapter contract 구현
- Qlib Position/Account와 declared valuation source에서 immutable snapshot 생성
- qlibx Strategy manifest/binding input resolve
- trigger 평가
- User Strategy 호출
- finalization 실행
- target state와 intended transition reconciliation
- `TradeDecisionWithDetails` 생성
- `post_exe_step`에서 Qlib actual result 기록

소유하지 않아야 할 책임:

- Qlib account를 대체하는 별도 physical account
- Market order fill simulation
- Bar-end valuation 재구현
- Qlib portfolio metrics와 독립적으로 움직이는 realized position ledger

### 9.3 Long-only path

```text
confirmed physical account snapshot
-> trigger
-> signal/weight
-> finalizer
-> integer target quantity + target cash
-> target-current delta
-> Qlib TradeDecision
-> Qlib Executor/Exchange/Account
```

Trigger false이면 target weight를 반복하지 않고 empty order decision을 반환한다.

### 9.4 Static signed path

```text
Qlib composite Position C
+ fixed qlibx baseline B
-> realized active A = C - B
-> Strategy feedback
-> signed target A*
-> composite target C* = B + A*
-> C* >= 0 검증
-> Qlib TradeDecision(C* - C)
-> Qlib fill
-> realized active A_realized = C_realized - B
```

### 9.5 Dynamic signed path

Dynamic mode가 필요하면 전체 manual loop를 유지하기보다 native Qlib loop에 작은 administration boundary를
추가한다.

필수 조건:

- Capitalization은 Qlib market fill과 별도 event type이다.
- Event는 quantity/cash를 동시에 바꾸고 NAV-neutral이어야 한다.
- Event와 market order/fill은 한 execution-step checkpoint에서 joint commit된다.
- Cover order가 blocked되면 baseline을 먼저 release하지 않는다.
- Qlib composite Position만 realized physical authority다.

구현 위치는 별도 설계가 필요하다. Strategy가 Account를 임의로 mutate하게 두는 것은 결합도가 높으므로
native Executor 전후의 명시적 hook 또는 qlibx-owned administration adapter가 더 안전하다.

## 10. Trigger와 mandatory finalization의 위치

### 10.1 Trigger

Qlib native loop는 매 trading bar마다 Strategy를 호출하므로 dense evaluation clock을 제공할 수 있다.
qlibx trigger는 그 bar에서 executable decision을 만들지 결정한다.

- `always` trigger: 매 bar 실행
- calendar trigger: month-end 등
- condition trigger: bounded data/account/memory 조건
- false result: empty order decision

Trigger는 scheduler를 대체하지 않는다. 조건이 평가되는 bar 해상도보다 세밀한 intrabar event는 관측할
수 없다.

### 10.2 Finalization

Finalization은 최종 executable parent decision에 정확히 한 번 적용한다.

```text
candidate allocation/target
-> mandatory finalization
-> reconciled target state
-> Qlib TradeDecision
```

Identity finalizer도 명시적으로 선언하고 result에 기록한다. Child signal 또는 historical what-if에 각각
finalization을 적용하면 중복 조정과 constraint scope 오류가 생긴다.

### 10.3 Reconciliation

Source account snapshot:

\[
V=c+\sum_i q_ip_i^{val}
\]

Final target state:

\[
V+F=c^*+\sum_i q_i^*p_i^{val}+K
\]

- \(F\): external cash flow
- \(K\): declared cost reserve

Intended transition:

\[
\Delta q_i=q_i^*-q_i,\qquad \Delta c=c^*-c
\]

비용과 external flow가 없으면:

\[
\Delta c+\sum_i p_i^{val}\Delta q_i=0
\]

따라서 feedback NAV와 같아야 하는 것은 order delta가 아니라 **final target portfolio state**다. Cash
delta는 accounting leg이며 Qlib에 제출하는 ticker order가 아니다.

## 11. `ScenarioExchange`는 유지할 가치가 있다

`ScenarioExchange`는 Qlib `Exchange` subclass이며 다음 qlibx-specific behavior를 제공한다.

- Direct quote frame
- Stock/ETF별 KRX cost policy
- Suspension/price-limit/buyable/sellable reason
- Volume clipping
- Position/cash/lot clipping stage
- Requested/filled amount diagnostic

출처:

- `src/qlibx/_vendor/qlib_backend/exchange.py:64-130`
- `src/qlibx/_vendor/qlib_backend/exchange.py:132-212`
- `src/qlibx/_vendor/qlib_backend/exchange.py:333-384`

이는 Qlib을 우회하는 backend가 아니라 Qlib extension point를 올바르게 사용하는 adapter다. Native
`SimulatorExecutor`에 그대로 연결하는 방향이 맞다.

다만 현재 diagnostic은 `consume_last_diagnostic()`로 마지막 order 하나만 소비한다. Native executor가
order loop를 소유하면 다음 중 하나가 필요하다.

- Exchange 내부 append-only diagnostic journal
- Thin `SimulatorExecutor` subclass가 execute result와 diagnostic을 함께 기록

Qlib order execution을 다시 구현하는 것은 피해야 한다.

## 12. Checkpoint/resume 경계

### 12.1 확인된 사실

현재 qlibx는 Strategy memory와 Qlib backend state를 함께 checkpoint한다.

근거:

- `src/qlibx/execution.py:320-369`
- `src/qlibx/_vendor/qlib_backend/backend.py:752-785`
- `tests/test_qlib_closed_loop.py:44-63`
- `tests/test_strategy_qlib_integration.py:92-112`
- `tests/test_signed_execution_journey.py:133-149`

Qlib 0.9.7의 조사 대상 `qlib/backtest`, `qlib/strategy` source에서는 qlibx가 요구하는 serializable
account/calendar/Strategy joint checkpoint API를 찾지 못했다. 이는 "Qlib 전체에 절대 없다"는 증명이
아니라, 사용 중인 native backtest contract에 바로 재사용할 공개 checkpoint가 확인되지 않았다는
조사 결과다.

### 12.2 권고

Native Qlib lifecycle로 이동해도 checkpoint materialization은 qlibx가 소유해야 한다.

각 completed bar 이후 최소 다음을 동결한다.

- Qlib Account/Position
- 다음 trade-calendar position 또는 equivalent restart boundary
- Strategy memory와 previous result identity
- Confirmed feedback history
- Static baseline 또는 dynamic capitalization state
- Accumulated return, cost와 turnover
- Capitalization event sequence

Native Qlib의 `post_exe_step`은 actual execute result를 받은 뒤 호출되므로 checkpoint observation point로
사용할 수 있다. 다만 crash atomicity와 restore 방법은 별도 구현·검증이 필요하다.

## 13. 기존 backend에서 유지할 것과 제거 후보

### 13.1 유지

- `ScenarioExchange`
- Execution profile과 quote-frame materialization
- PIT Strategy input resolver
- Strategy manifest/binding
- Trigger, memory와 invocation identity
- Signed `A/B/C` reconciliation
- Active/composite/baseline result schema
- Checkpoint serialization
- qlibx artifact와 diagnostics

### 13.2 Native Qlib로 대체할 후보

- `QlibClosedLoopBackend.run_targets`의 generic bar loop
- Qlib Order의 직접 제출 loop
- Generic bar-end Account/Position update
- Qlib과 중복되는 TradeDecision lifecycle
- Empty decision을 weight 반복으로 흉내 내는 경로

### 13.3 즉시 삭제하면 안 되는 이유

현재 backend는 다음 behavior가 test로 검증된 characterization oracle이다.

- Partial fill은 Qlib dealt quantity를 따른다:
  `tests/test_qlib_closed_loop.py:33-41`
- Strategy는 prior confirmed feedback만 본다:
  `tests/test_strategy_qlib_integration.py:66-89`
- Signed active feedback과 partial fill을 반영한다:
  `tests/test_strategy_qlib_integration.py:151-173`
- Resume와 uninterrupted run이 observable table 기준으로 일치한다:
  `tests/test_qlib_closed_loop.py:44-63`

Native path가 이 behavior를 재현하기 전에 기존 backend를 제거하면 검증 기준 자체를 잃는다.

## 14. 권장 이행 순서

### Phase 0 — Characterization freeze

- 현재 12개 focused test를 migration gate로 고정한다.
- Current backend의 orders, fills, positions, account, feedback와 checkpoint schema를 snapshot한다.
- Qlib 0.9.7 dependency를 migration 기간 동안 고정한다.

### Phase 1 — Native long-only

- `QlibxStrategyAdapter(BaseStrategy)`를 추가한다.
- `ScenarioExchange`와 Qlib `SimulatorExecutor`를 연결한다.
- Trigger false를 empty `TradeDecision`으로 표현한다.
- Long-only target/order/fill/account parity를 비교한다.

### Phase 2 — Static matched endowment

- Qlib Account initial `position_dict`로 fixed baseline \(B\)를 설정한다.
- Signed target \(A^*\)를 composite target \(C^*=B+A^*\)로 변환한다.
- Capacity breach는 explicit failure로 기록한다.
- Qlib fill 뒤 `A=C-B`와 NAV identity를 검사한다.

### Phase 3 — Finalization과 intended-transition artifact

- Mandatory identity finalizer를 포함한다.
- Target portfolio NAV와 self-financing transition을 검증한다.
- `TradeDecisionWithDetails`에 trigger, source snapshot, target state, cash leg, orders와 diagnostics를
  기록한다.

### Phase 4 — Checkpoint/resume

- Native Account/Position과 Strategy state의 joint checkpoint를 구현한다.
- Resume와 uninterrupted run의 decision/order/fill/account/result identity를 비교한다.

### Phase 5 — Dynamic endowment 필요성 재평가

- Static capacity breach 빈도
- Dynamic universe short 요구
- Reserve 사용량
- Runtime과 artifact complexity

를 측정한다. 필요성이 확인될 때만 dynamic administration hook을 native loop에 추가한다.

### Phase 6 — Manual loop retirement

- 모든 acceptance scenario가 통과한 뒤 current manual loop를 제거한다.
- 기존 backend를 compatibility alias로 무기한 유지하지 않는다.
- Qlib public contract로 대체되지 않는 qlibx-specific code만 남긴다.

## 15. Acceptance criteria

### 15.1 Native long-only parity

- 동일 scenario에서 trigger된 decision의 requested order quantity가 current backend와 일치하거나 차이가
  문서화된다.
- Qlib dealt quantity, cash, cost, ending Position과 NAV가 reconcile된다.
- Suspension, price limit, volume, position, cash와 lot clipping reason을 보존한다.
- Sell-before-buy financing이 동일하게 동작한다.

### 15.2 Hold

- 가격이 변해도 trigger false bar에는 order가 0건이다.
- Position quantity는 fill/corporate action이 없으면 유지된다.
- Qlib bar-end valuation과 account row는 계속 생성된다.
- Finalizer는 실행할 candidate transition이 없는 hold를 재매매로 바꾸지 않는다.

### 15.3 Static signed mode

- Initial Qlib composite Position은 non-negative다.
- Initial cash, initial position market value, starting composite NAV와 Qlib metric denominator가
  reconcile된다.
- 모든 bar에서 `A = C - B`가 성립한다.
- 모든 intended target에서 `C^* >= 0`을 검사한다.
- Partial short SELL 또는 blocked cover 뒤 active quantity는 requested target이 아니라 Qlib realized
  `C-B`다.
- Composite NAV는 baseline NAV와 active NAV의 합과 일치한다.
- Baseline PnL을 제거한 active PnL을 별도로 제공한다.
- Insufficient endowment는 offending ticker와 required/available quantity를 보고한다.

### 15.4 Clock와 information boundary

- Strategy input은 decision time에 available한 data만 포함한다.
- Sizing, valuation과 execution price role을 혼용하지 않는다.
- Qlib helper가 same-bar information을 사용하는 경우 execution profile이 이를 명시한다.
- Trigger는 evaluation clock보다 세밀한 event를 관측한다고 주장하지 않는다.

### 15.5 Checkpoint

- Resume와 uninterrupted run이 decisions, orders, fills, positions, account, Strategy memory와 signed
  reconciliation에서 일치한다.
- Incomplete bar 또는 capitalization event는 completed checkpoint로 보이지 않는다.
- Static baseline identity 또는 dynamic event sequence가 restart 후 유지된다.

### 15.6 Performance

- 동일 input에서 current manual loop와 native loop의 runtime과 peak memory를 측정한다.
- DRY를 runtime 성능 향상으로 자동 판정하지 않는다.
- Manifest input resolution의 per-bar data reload 비용을 별도로 측정한다.

## 16. PRD에 반영할 수 있는 추상 requirement

이 문서는 내부 architecture를 제안하지만 PRD에는 class 이름이나 module 배치를 그대로 넣지 않는다.
PRD-level requirement는 다음 정도가 적절하다.

1. **Native runtime authority:** Qlib-compatible execution에서는 trading calendar, order execution,
   fill, physical Position, Account와
   valuation의 authoritative lifecycle을 Qlib에 맡긴다. qlibx는 같은 lifecycle을 독립적으로 복제하지
   않는다.

2. **Strategy adaptation:** qlibx는 project Strategy의 bounded input, account feedback, trigger,
   memory와 finalization을 Qlib
   decision lifecycle에 연결하는 adapter contract를 제공한다.

3. **Physical authority:** Requested target, intended order와 hypothetical signed ledger를 realized
   physical holding으로 취급하지
   않는다. Qlib-confirmed Position과 dealt quantity만 realized physical authority다.

4. **Signed compatibility separation:** Qlib이 native short를 제공하지 않는 경우 signed active
   intent를 non-negative composite position으로
   변환하는 compatibility mechanism을 별도 선언한다.

5. **Static endowment boundary:** Static endowment mode는 fixed universe와 explicit quantity
   capacity를 가지며 capacity breach를
   silent clipping하지 않는다.

6. **Accounting reconciliation:** Composite, baseline과 active quantity/NAV identity를 매 decision에서
   검증한다.

7. **No-op decision:** Strategy가 활성화되지 않은 evaluation point는 zero executable order로 표현하며
   target weight 반복으로
   암묵적 rebalance를 만들지 않는다.

8. **Checkpoint integrity:** Strategy state, Qlib account state와 signed compatibility state는 동일
   completed execution boundary에서
   reconcile되고 checkpoint된다.

## 17. 최종 권고

현재 qlibx는 Qlib을 dependency로 강제하면서도 가장 중요한 native abstraction인 Strategy/TradeDecision/
Executor lifecycle을 우회한다. 이 상태는 장기적으로 DRY하지 않고 Qlib semantics 변경을 따라가기 어렵다.

따라서 다음 구조를 목표로 하는 것이 타당하다.

```text
Qlib native lifecycle
+ qlibx Strategy adapter
+ qlibx ScenarioExchange
+ static matched-endowment translator
+ qlibx artifact/checkpoint/reconciliation
```

1차 signed mode는 static initial endowment로 제한한다. 이는 bounded hypothetical long-short research에는
충분히 단순하고 Qlib native lifecycle 활용도를 높인다.

다만 static mode를 dynamic short capacity의 일반 해법으로 과장하면 안 된다. 가격 하락, active NAV
증가, universe 변경과 corporate action은 fixed quantity endowment를 부족하게 만들 수 있다. 이 요구가
실제로 중요하다는 evidence가 쌓일 때만 dynamic matched-capitalization hook을 추가한다.

결론적으로 제거해야 하는 것은 qlibx의 signed accounting이 아니라 **Qlib이 이미 소유한 generic
execution lifecycle의 중복 구현**이다.

## Appendix A. 근거 파일 색인

### qlibx 정본·설계

- `docs/qlibx-prd.md:59-89` — Qlib closed-loop와 feedback authority
- `docs/qlibx-prd.md:1207-1214` — prior confirmed feedback와 resume
- `docs/qlibx-prd.md:1556-1660` — Qlib execution과 matched-capitalization contract
- `docs/qlibx-architecture.md:682-724` — 현재 execution plane
- `docs/thoughts/decision-clock-and-rebalance-trigger.md:83-133` — hold와 trigger gap 조사
- `docs/thoughts/constraint-limits-and-the-monitoring-clock.md:230-282` — dense clock, hold와 finalization
- `docs/implementations/002-package-owned-qlib-execution.md` — 현재 backend 도입 배경
- `docs/implementations/005-adaptive-signed-execution-optimizer-api.md` — adaptive signed path와 checkpoint

### qlibx source

- `src/qlibx/strategy.py:15,113-177,302-361` — output kind, DecisionContext와 DecisionResult
- `src/qlibx/strategy_manifest/invocation.py:90-174` — pure pandas Strategy adapter
- `src/qlibx/execution.py:168-378` — adaptive execution bridge
- `src/qlibx/execution.py:442-510` — signed result reconciliation
- `src/qlibx/_vendor/qlib_backend/backend.py:74-785` — current manual Qlib loop
- `src/qlibx/_vendor/qlib_backend/backend.py:1018-1095` — dynamic capitalization/release
- `src/qlibx/_vendor/qlib_backend/exchange.py:64-212,333-384` — ScenarioExchange와 diagnostics

### qlibx tests

- `tests/test_qlib_closed_loop.py:33-63`
- `tests/test_strategy_qlib_integration.py:66-112,151-203`
- `tests/test_signed_execution_journey.py:49-149`

### Qlib 0.9.7 source

Local inspection root:

```text
.venv/Lib/site-packages/qlib/
```

Primary files:

- `qlib/strategy/base.py:23-146`
- `qlib/backtest/backtest.py:26-110`
- `qlib/backtest/decision.py:302-383,508-595`
- `qlib/backtest/executor.py:250-303,513-628`
- `qlib/backtest/account.py:71-150,225-301`
- `qlib/backtest/position.py:231-475`
- `qlib/backtest/__init__.py:113-214`
- `qlib/contrib/strategy/signal_strategy.py:298-372`
- `qlib/contrib/strategy/order_generator.py:14-217`
- `qlib/backtest/exchange.py:534-710`

Official upstream tag:

- [`microsoft/qlib v0.9.7`](https://github.com/microsoft/qlib/tree/v0.9.7)
