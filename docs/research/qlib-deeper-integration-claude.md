# qlib을 더 깊이 쓸 수 있는가 — 재사용 경계 재조사

- 상태: 조사 기록 (research). 결정된 설계가 아니다.
- 대상 브랜치/커밋: `exp/one-shot` @ `f22fa12`
- 대상 qlib: `pyqlib 0.9.7` (`.venv/Lib/site-packages/qlib`, `qlib.__version__ = "0.9.7"`)
- 계기: "DRY 해야 efficient·effective한데 qlibx가 qlib을 충분히 활용하지 못하는 것 같다. qlibx로
  strategy를 뺀 이유는 long-short을 실험하고 싶은데 qlib이 short을 허용하지 않기 때문이었다. qlib
  native strategy가 있다면 그것을 최대한 쓰고, initial endowment를 통한 hypothetical long-short만
  따로 처리하면 되지 않는가."
- 자매 문서: [`../thoughts/decision-clock-and-rebalance-trigger.md`](../thoughts/decision-clock-and-rebalance-trigger.md),
  [`../thoughts/constraint-limits-and-the-monitoring-clock.md`](../thoughts/constraint-limits-and-the-monitoring-clock.md).
  이 문서는 그 두 문서가 "구조적으로 불가"로 판정한 항목 중 일부를 **뒤집는다** (§11).

## 0. 인용 규칙과 검증 방법

- qlibx 인용은 저장소 상대 경로 + 행 번호다.
- qlib 인용은 `.venv/Lib/site-packages/qlib/...` 상대 경로 + 행 번호다. 이 경로는 환경 로컬이며
  버전이 바뀌면 행 번호가 달라진다. 위 버전 고정과 함께 읽어야 한다.
- 모든 인용은 이 문서를 쓰면서 실제 파일을 열어 확인했다. 확인하지 못한 항목은 §12에 분리해 두었다.

## 1. 한 줄 결론

**qlib이 실제로 막는 것은 `Position`의 음수 수량 금지 한 곳인데, qlibx는 그 하나 때문에 strategy ·
trade decision · executor · order generation 네 층을 새로 만들었다.** exchange · account · position은
이미 제대로 재사용하고 있으므로, 문제는 "qlib을 안 쓴다"가 아니라 **잘라낸 지점이 필요보다 위에
있다**는 것이다. 그리고 endowment(matched capitalization)는 qlib을 한 줄도 고치지 않고 그 바깥에서
성립하므로, 사용자의 방향 제안은 원리적으로 맞다.

## 2. 현재 재사용 지도

| qlib 구성요소 | 상태 | 근거 |
| --- | --- | --- |
| `Exchange.deal_order` 체결 경로 | **재사용** | [`exchange.py:114`](../../src/qlibx/_vendor/qlib_backend/exchange.py:114) `super().deal_order(...)` |
| `Exchange._calc_trade_info_by_order` | **재사용** (비용만 교체) | [`exchange.py:139`](../../src/qlibx/_vendor/qlib_backend/exchange.py:139) |
| `Exchange._clip_amount_by_volume` | **재사용** | [`exchange.py:178`](../../src/qlibx/_vendor/qlib_backend/exchange.py:178) |
| `Account` / `Position` / `Order` | **재사용** | [`backend.py:534-537`](../../src/qlibx/_vendor/qlib_backend/backend.py:534) |
| `qlib.init` | **재사용** | [`backend.py:83-88`](../../src/qlibx/_vendor/qlib_backend/backend.py:83) |
| `BaseStrategy` / `BaseTradeDecision` | **미사용** | 자체 `target_policy` 콜백 ([`execution.py:226`](../../src/qlibx/execution.py:226)) |
| `SimulatorExecutor` / `NestedExecutor` | **미사용** | 자체 for 루프 ([`backend.py:199`](../../src/qlibx/_vendor/qlib_backend/backend.py:199)) |
| weight→order 생성 helper | **미사용** | 자체 `_raw_target_quantity`/`_round_target_quantity` ([`backend.py:1154-1176`](../../src/qlibx/_vendor/qlib_backend/backend.py:1154)) |
| `TradeCalendarManager` / `TradeRange` | **미사용** | 결정 달력 = `execution_price.index` |

`backend.py`는 1411행이다. 위 "미사용" 네 줄이 그 대부분을 차지한다.

## 3. qlib이 실제로 막는 것 — 정확히 어디인가

### 3.1 `Position._sell_stock` — 음수 보유 금지

```python
# .venv/Lib/site-packages/qlib/backtest/position.py:352-374
def _sell_stock(self, stock_id, trade_val, cost, trade_price):
    trade_amount = trade_val / trade_price
    if stock_id not in self.position:
        raise KeyError("{} not in current position".format(stock_id))
    ...
            if self.position[stock_id]["amount"] < -1e-5:
                raise ValueError("only have {} {}, require {}".format(...))
```

두 가지가 동시에 걸린다. **미보유 종목은 매도 자체가 `KeyError`**이고(→ 신규 short 진입 불가),
**보유 초과 매도는 `ValueError`**다(→ 기존 보유를 넘는 short 불가). "qlib은 short을 허용하지 않는다"는
전제는 정확하며, 그 근거는 이 한 함수다.

### 3.2 `Order`는 방향 열거형이고 수량은 비음수다

```python
# .venv/Lib/site-packages/qlib/backtest/decision.py:30-33, 54
class OrderDir(IntEnum):
    SELL = 0
    BUY = 1
...
    amount: float  # `amount` is a non-negative and adjusted value
```

signed 수량을 담을 자리가 없다. 이것도 사실이다.

### 3.3 그러나 그 위층은 막지 않는다

`SimulatorExecutor`는 주문 리스트를 받아 exchange에 넘길 뿐이고, 부호나 방향에 대한 추가 제약이
없다([`executor.py:590-628`](../../.venv/Lib/site-packages/qlib/backtest/executor.py:590)). `BaseStrategy`도
마찬가지다. **즉 short 금지는 회계 최하층(`Position`)의 성질이지 strategy/executor 층의 성질이
아니다.** qlibx가 strategy/executor를 다시 만든 것은 이 제약과 직접 관련이 없다.

## 4. qlibx가 다시 만든 것 vs qlib에 이미 있는 것

이 절이 이 문서의 본론이다. 최근 논의에서 "새로 설계해야 한다"고 본 계약 상당수가 qlib에 native로
존재한다.

### 4.1 "전략의 출력은 order다" — qlib native strategy contract 그 자체

```python
# .venv/Lib/site-packages/qlib/strategy/base.py:132-146
@abstractmethod
def generate_trade_decision(self, execute_result: list = None):
    """Generate trade decision in each trading bar
    execute_result : List[object], optional
        the executed result for trade decision, by default None
    """
```

반환 타입은 `BaseTradeDecision`이고, 주문을 담는 구현체가 `TradeDecisionWO(order_list, strategy)`다
([`decision.py:547-570`](../../.venv/Lib/site-packages/qlib/backtest/decision.py:547)).

qlibx는 대신 weight `pd.Series`를 반환하는 콜백을 쓴다.

```python
# src/qlibx/execution.py:226
def target_policy(date: pd.Timestamp, state: Mapping[str, Any]) -> pd.Series:
```

**"전략이 weight→order 변환까지 책임진다"는 제안은 qlib으로 되돌아가는 것과 같다.**

### 4.2 hold(no-op) 계약 — 이미 있다

```python
# .venv/Lib/site-packages/qlib/backtest/decision.py:539-544
class EmptyTradeDecision(BaseTradeDecision[object]):
    def get_decision(self) -> List[object]:
        return []
    def empty(self) -> bool:
        return True
```

`BaseTradeDecision.empty()`는 **수량 0인 주문도 빈 것으로 취급**한다
([`decision.py:508-516`](../../.venv/Lib/site-packages/qlib/backtest/decision.py:508)). qlib 자신의
`WeightStrategyBase`도 신호가 없으면 `TradeDecisionWO([], self)`를 반환한다
([`signal_strategy.py:354-355`](../../.venv/Lib/site-packages/qlib/contrib/strategy/signal_strategy.py:354)).

반면 qlibx 루프는 매 bar 반드시 target weight를 받아 delta를 계산한다.

```python
# src/qlibx/_vendor/qlib_backend/backend.py:383-386
raw_target_physical = _raw_target_quantity(weights.loc[date], pretrade_nav, price)
target_physical = _round_target_quantity(raw_target_physical, lot_size)
target_adjusted = target_physical.astype("float64").div(factor)
delta = target_adjusted - current_adjusted
```

`_round_target_quantity`가 floor이므로([`backend.py:1162-1164`](../../src/qlibx/_vendor/qlib_backend/backend.py:1162)),
같은 weight를 반환해도 `pretrade_nav`와 `price`가 변하면 target 수량이 바뀌고 주문이 나간다.
**price drift 리밸런싱은 qlib의 결함이 아니라 weight 콜백을 택한 대가다.**

### 4.3 closed-loop feedback — 이미 있다

`generate_trade_decision(execute_result)`의 인자가 직전 스텝 체결 결과이고, 계좌는
`BaseStrategy.trade_position` / `common_infra.get("trade_account")`로 접근한다
([`base.py:70-77`](../../.venv/Lib/site-packages/qlib/strategy/base.py:70)). qlibx가
`DecisionContext.account`와 `feedback_history`로 손수 만들어 넘기는 것
([`execution.py:244-264`](../../src/qlibx/execution.py:244))과 1:1로 대응한다.

### 4.4 weight→order 변환 building block — 이미 있다

- `Exchange.generate_amount_position_from_weight_position` ([`exchange.py:534`](../../.venv/Lib/site-packages/qlib/backtest/exchange.py:534))
- `Exchange.generate_order_for_target_amount_position` ([`exchange.py:611`](../../.venv/Lib/site-packages/qlib/backtest/exchange.py:611))
- `Exchange.get_real_deal_amount` / `round_amount_by_trade_unit` ([`exchange.py:589`](../../.venv/Lib/site-packages/qlib/backtest/exchange.py:589), [`:761`](../../.venv/Lib/site-packages/qlib/backtest/exchange.py:761))
- `OrderGenWInteract` / `OrderGenWOInteract` ([`order_generator.py:50`](../../.venv/Lib/site-packages/qlib/contrib/strategy/order_generator.py:50), [`:142`](../../.venv/Lib/site-packages/qlib/contrib/strategy/order_generator.py:142))

`OrderGenWInteract`는 현금·거래가능·비용 유보(`risk_degree`)까지 처리한다. 다만 그대로 쓰면 안 되는
이유가 §8에 있다.

### 4.5 "매도 먼저" 주문 순서 — 이미 있다

qlibx는 손으로 정렬한다.

```python
# src/qlibx/_vendor/qlib_backend/backend.py:388-391
# 같은 bar의 매도 대금을 Qlib buy cash limit가 사용할 수 있도록 매도를 먼저 처리합니다.
order_specs = [...value < -1e-12] + [...value > 1e-12]
```

qlib은 order generator가 `sell_order_list + buy_order_list`를 반환하고
([`exchange.py:677`](../../.venv/Lib/site-packages/qlib/backtest/exchange.py:677)),
`SimulatorExecutor.TT_SERIAL`이 리스트 순서를 보존한다
([`executor.py:576-578`](../../.venv/Lib/site-packages/qlib/backtest/executor.py:576)). 같은 동작이 두 곳에 있다.

### 4.6 decision clock 분리 — qlib에는 있다

`NestedExecutor`는 레벨마다 `time_per_step`을 따로 갖는다.

```python
# .venv/Lib/site-packages/qlib/backtest/executor.py:317-322
def __init__(self, time_per_step: str, inner_executor, inner_strategy, ...)
```

여기에 `TradeCalendarManager`, `TradeRange` / `TradeRangeByTime`
([`decision.py:206`](../../.venv/Lib/site-packages/qlib/backtest/decision.py:206), [`:264`](../../.venv/Lib/site-packages/qlib/backtest/decision.py:264))가 붙는다.

반면 qlibx는 target index가 execution_price index와 **정확히 일치**할 것을 요구한다.

```python
# src/qlibx/_vendor/qlib_backend/backend.py:927-928
if not matrix.index.equals(execution_price.index):
    raise ValueError("target_weights index must match execution_price")
```

자매 문서가 "관측 clock과 결정 clock을 분리할 방법이 없다"고 판정한 것은 **qlibx 루프에 대해서만
참이다.**

## 5. 유일한 실질 장벽 — trading calendar, 그리고 그것이 싼 이유

### 5.1 장벽

`BaseExecutor.reset`이 calendar를 만들고([`executor.py:173`](../../.venv/Lib/site-packages/qlib/backtest/executor.py:173)),
`TradeCalendarManager.reset`이 qlib 전역 calendar provider를 부른다.

```python
# .venv/Lib/site-packages/qlib/backtest/utils.py:69-72
_calendar = Cal.calendar(freq=freq, future=True)
assert isinstance(_calendar, np.ndarray)
self._calendar = _calendar
_, _, _start_index, _end_index = Cal.locate_index(start_time, end_time, freq=freq, future=True)
```

`TradeDecisionWO.__init__`도 `strategy.trade_calendar.get_step_time()`을 부른다
([`decision.py:561`](../../.venv/Lib/site-packages/qlib/backtest/decision.py:561)). 즉 executor·decision
모두 calendar를 통해 qlib 데이터 provider에 묶인다. qlibx의 data plane은 사용자 Parquet이므로
**이것이 자체 루프를 짠 실질적 이유로 보인다.**

참고로 `Exchange` 쪽 provider 결합은 이미 두 지점뿐이고 둘 다 회피되어 있다.

- `D.instruments(codes)`는 `codes`가 `str`일 때만 호출된다([`exchange.py:166-167`](../../.venv/Lib/site-packages/qlib/backtest/exchange.py:166)). qlibx는 리스트를 넘긴다([`backend.py:151`](../../src/qlibx/_vendor/qlib_backend/backend.py:151)).
- `get_quote_from_qlib()`의 `D.features` 호출([`exchange.py:205`](../../.venv/Lib/site-packages/qlib/backtest/exchange.py:205))은 qlibx가 통째로 override한다([`exchange.py:84-90`](../../src/qlibx/_vendor/qlib_backend/exchange.py:84)).

### 5.2 그런데 provider는 교체 가능하다

```python
# .venv/Lib/site-packages/qlib/data/data.py:1297-1301
_calendar_provider = init_instance_by_config(C.calendar_provider, module)
if getattr(C, "calendar_cache", None) is not None:
    _calendar_provider = init_instance_by_config(C.calendar_cache, module, provide=_calendar_provider)
register_wrapper(Cal, _calendar_provider, "qlib.data")
```

`C.calendar_provider`의 기본값은 `"LocalCalendarProvider"`이고
([`config.py:136`](../../.venv/Lib/site-packages/qlib/config.py:136)), `qlib.init(calendar_provider=...)`로
바꿀 수 있다. 그리고 `CalendarProvider`에서 **하위 클래스가 구현할 것은 `load_calendar(freq, future)`
하나**다. `calendar()`, `locate_index()`, `_get_calendar()`는 base가 그 위에서 구현한다
([`data.py:65-205`](../../.venv/Lib/site-packages/qlib/data/data.py:65)).

즉 **등록된 execution index를 `np.ndarray`로 돌려주는 어댑터 하나**가 `BaseStrategy` ·
`SimulatorExecutor` · `NestedExecutor` · `TradeRange` 전체를 연다. qlibx는 이미 `qlib.init`을 부르고
있으므로 추가 진입 비용도 없다.

`SimulatorExecutor._collect_data`는 calendar 외에 데이터 provider를 쓰지 않는다 — 주문 iterate,
`exchange.deal_order`, `trade_account` 갱신이 전부다
([`executor.py:590-628`](../../.venv/Lib/site-packages/qlib/backtest/executor.py:590)).

**이 문서에서 가장 값어치 있는 발견이다.**

## 6. endowment layer가 qlib 바깥에서 성립하는 이유

matched capitalization이 성립하는 조건은 세 가지이고, 전부 qlib을 고치지 않아도 만족된다.

1. `B`(baseline)는 평범한 롱 보유다.
2. `C = B + A >= 0`이므로 §3.1의 음수 금지에 걸리지 않는다.
3. 모든 주문이 평범한 `BUY`/`SELL`이므로 §3.2의 방향 열거형에 걸리지 않는다.

t0 시딩은 `Position` 생성자가 직접 지원한다.

```python
# .venv/Lib/site-packages/qlib/backtest/position.py:245-262
def __init__(self, cash: float = 0, position_dict: Dict[str, Union[Dict[str, float], float]] = {}):
    """
    position_dict : Dict[stock_id, Union[int, {"amount": int, "price"(optional): float}]]
        initial stocks with parameters amount and price,
        if there is no price key in the dict of stocks, it will be filled by _fill_stock_value.
    """
```

**price를 함께 주는 것이 중요하다.** 생략하면 `fill_stock_value`가 qlib 데이터에서 종가를 읽으려
한다([`position.py:280`](../../.venv/Lib/site-packages/qlib/backtest/position.py:280)) — qlibx 환경에서는
동작하지 않는다.

따라서 signed layer는 qlib 루프 바깥의 세 조각으로 분해된다.

```text
(a) t0 position seeding          -> Position(cash, {ticker: {"amount": B, "price": p}})
(b) 전략 경계에서 A <-> C 번역    -> 전략은 signed를 보고, 주문은 composite로 나감
(c) 리포팅에서 A = C - B 재구성  -> active NAV denominator 유지 (PRD §11.5)
```

세 조각 중 어느 것도 executor·exchange·position을 대체할 이유가 없다. **사용자 제안의 방향은
맞다.**

### 6.1 다만 중간 증자는 native 루프에 자리가 없다

현재 설계는 short가 필요해지는 시점에 baseline을 lazy activation하고 NAV 중립을 검증한다.

```python
# src/qlibx/_vendor/qlib_backend/backend.py:275-283, 339-345
additions = _required_baseline_additions(intended_weight=..., baseline_quantity=..., ...)
...
if not np.isclose(capitalized_nav, pretrade_nav, ...):
    raise RuntimeError("matched capitalization changed composite NAV")
```

qlib native 루프에는 "거래소를 거치지 않고 주식과 현금을 동시에 주입"하는 훅이 없다. 선택지는 둘이고
이것이 §10-1의 미결 사항이다.

- **(i) t0 선증자.** 최대 short capacity를 처음에 다 넣는다. native 루프에 손댈 필요가 없다.
  대신 reserve가 과도하게 묶이고 PRD §11.4의 activation / top-up / release lifecycle이 축소된다.
- **(ii) 전략 안에서 `common_infra.get("trade_account").current_position`을 직접 변형.** 가능은
  하지만 qlib이 의도한 지점이 아니고, `Account.update_bar_end`
  ([`account.py:338`](../../.venv/Lib/site-packages/qlib/backtest/account.py:338)) 기반의
  portfolio_metrics 회계와 충돌할 위험이 있다.

## 7. 이 방향이 부수적으로 푸는 것

- **manifest 경로 / adaptive 경로 이원화** (자매 문서 §3, §8). 전략 경계가
  `generate_trade_decision` 하나로 통일되면 "memory·feedback을 가진 전략과 아닌 전략" 구분이
  사라진다. 현재는 `output_kind != "weight"`를 두 곳에서 각각 막고 있다
  ([`execution.py:194`](../../src/qlibx/execution.py:194),
  [`invocation.py:151`](../../src/qlibx/strategy_manifest/invocation.py:151)).
- **hold 계약 신설 부담.** §4.2대로 이미 존재하므로 qlibx가 정의할 새 계약이 아니라 노출할 기존
  계약이다.
- **`freq="day"` 하드코딩** ([`backend.py:148`](../../src/qlibx/_vendor/qlib_backend/backend.py:148)).
  executor의 `time_per_step`으로 대체된다.
- **fill rate 진단.** qlib `Indicator`가 `ffr`(full fill rate)을 계산한다
  ([`report.py:264`](../../.venv/Lib/site-packages/qlib/backtest/report.py:264), [`:615-623`](../../.venv/Lib/site-packages/qlib/backtest/report.py:615)).
  qlibx의 `ExecutionDiagnostic`과 부분적으로 겹친다.

## 8. 그대로 채택하면 안 되는 것

"최대한 활용"이 "기본값을 그대로 쓴다"는 아니다. 아래는 qlibx 원칙과 **정면 충돌**한다.

### 8.1 거래가능 종목으로의 조용한 재정규화

```python
# .venv/Lib/site-packages/qlib/backtest/exchange.py:576-586
amount_dict[stock_id] = (
    cash * weight_position[stock_id] / tradable_weight
    // self.get_deal_price(...)
)
```

거래불가 종목을 빼고 **남은 tradable weight로 나눠 현금을 전부 배분**한다. PRD §8.4(flexible budget의
unused amount 보존)와 §2.6("required data가 없을 때 조용히 생략하지 않는다")을 동시에 위반한다.

### 8.2 전역 RNG 리셋

```python
# .venv/Lib/site-packages/qlib/backtest/exchange.py:637-639
sorted_ids = sorted(set(list(current_position.keys()) + list(target_position.keys())))
random.seed(0)
random.shuffle(sorted_ids)
```

`random` 모듈의 **전역 상태**를 리셋한다. PRD §7.1의 determinism/seed 계약을 쓰는 전략이 이 함수
호출 이후 난수를 쓰면 시드가 조용히 덮인다.

### 8.3 거래불가 종목의 조용한 스킵

같은 함수에서 거래불가 종목은 `continue`로 넘어간다
([`exchange.py:642-643`](../../.venv/Lib/site-packages/qlib/backtest/exchange.py:642)). 어떤 종목이 왜
빠졌는지 결과에 남지 않는다.

### 8.4 `OrderGenWInteract`는 signed에 못 쓴다

`generate_amount_position_from_weight_position`이 `wp < 0 or wp > 1`을 거부한다
([`exchange.py:560-563`](../../.venv/Lib/site-packages/qlib/backtest/exchange.py:560)).

### 8.5 `WeightStrategyBase`는 signal 구동이다

```python
# .venv/Lib/site-packages/qlib/contrib/strategy/signal_strategy.py:353
pred_score = self.signal.get_signal(start_time=pred_start_time, end_time=pred_end_time)
```

qlibx StrategyAgent는 임의의 canonical pandas input + memory가 필요하다. **상속 대상은 `BaseStrategy`
이지 `WeightStrategyBase`가 아니다.**

### 8.6 부수 효과 — eval price 논쟁의 native 어휘

직전 논의에서 미결로 남긴 "전략이 결정 시점 가격을 봐도 되는가"를 qlib은 이미 두 갈래로 이름
붙여 두었다.

- `Exchange.generate_order_for_target_amount_position`의 docstring 첫 줄:
  `"Note: some future information is used in this function"` ([`exchange.py:619`](../../.venv/Lib/site-packages/qlib/backtest/exchange.py:619))
- `OrderGenWInteract`: 체결일 가격 사용 ([`order_generator.py:66-69`](../../.venv/Lib/site-packages/qlib/contrib/strategy/order_generator.py:66))
- `OrderGenWOInteract`: 예측일 종가 사용, docstring이 "cannot get that value when do not interact with
  exchange"라고 이유를 밝힌다 ([`order_generator.py:158-163`](../../.venv/Lib/site-packages/qlib/contrib/strategy/order_generator.py:158))

qlibx가 새로 명명할 필요가 없다. 두 프로파일을 그대로 쓰면 된다.

## 9. 비용과 리스크

1. **qlib 전역 상태 의존 상승.** provider는 `register_wrapper`로 **프로세스 전역**에 등록된다
   ([`data.py:1300`](../../.venv/Lib/site-packages/qlib/data/data.py:1300)). 현재는 calendar를 안 쓰므로
   무해하지만, run마다 다른 달력을 등록해야 하는 순간 **PRD §9.7(한 branch에서 여러 agent 동시
   실행)이 전역 상태 충돌 문제로 승격된다.** 프로세스 격리 또는 run별 provider 스위칭 전략이 필요하다.
   이 방향의 가장 큰 숨은 비용이다.
2. **내부 API 결합도 상승.** `executor` / `strategy` / `decision`은 `exchange`보다 변동이 잦은 영역이다.
   현재 vendor 격리는 exchange 표면만 얇게 물려 있다.
3. **회계 이중화.** `Account.update_bar_end` 기반 portfolio_metrics는 composite 기준이므로, Path B의
   active NAV 회계(PRD §11.5)는 어차피 별도 reconciliation으로 유지해야 한다. executor 채택이 이
   부담을 줄여주지는 않는다.
4. **진단 정밀도.** qlibx의 `ExecutionDiagnostic`은 tradability → volume → position → cash → lot의
   단계별 귀속을 계측한다([`exchange.py:333-384`](../../src/qlibx/_vendor/qlib_backend/exchange.py:333)).
   qlib `Indicator`의 `ffr`은 이보다 거칠다. **계측은 유지해야 한다** — 유지 가능하다. 계측은 exchange
   층에 있고 executor 교체와 무관하다.

## 10. 이관 경로 (제안, 미확정)

1. **CalendarProvider 어댑터 + `BaseStrategy` 브리지 + `SimulatorExecutor` 채택.**
   `ScenarioExchange`는 유지한다 — 그것은 옳은 종류의 재사용이다. Path A(long-only)만 먼저 이관하고
   기존 결과와의 동일성 회귀 테스트로 판정한다.
2. **Path B를 endowment layer로 재구성.** §6.1의 결정에 따라 t0 선증자 또는 계좌 변형.
   `A <-> C` 번역은 전략 경계 어댑터로 둔다.
3. **`NestedExecutor`로 clock 분리.** 여기까지 오면 자매 문서의 A/B 선택지가 다시 열린다. B(trigger를
   1급 개념으로)가 갑자기 싸진다.

### PRD 영향

대부분 architecture 결정이며 PRD 문구는 유지 가능하다. 다만 두 곳은 손대는 편이 정확하다.

- **§2.2 "Qlib에 맡기는 것"** — decision loop, trade decision, trading calendar를 목록에 추가.
- **§11.2** — "Qlib을 fork하지 않고"를 "qlib native strategy/executor 계약 위에 endowment layer만
  얹는다"로 강화.

그리고 최근 논의에서 제안된 requirement 골격 중 hold 계약과 order 출력은 "qlibx가 정의하는 새 계약"이
아니라 **"qlib 계약을 그대로 노출한다"**로 약화시킬 수 있다. DRY 관점에서 그쪽이 옳다.

## 11. 이 문서가 뒤집는 기존 판정

| 기존 판정 | 출처 | 이 문서의 수정 |
| --- | --- | --- |
| "관측 clock과 결정 clock을 분리할 방법이 없다" | decision-clock 문서 §4.2 | **qlibx 루프에 대해서만 참.** qlib `NestedExecutor`는 지원한다 (§4.6) |
| "no-op 계약이 없다" | decision-clock 문서 §4.3(1) | **qlibx 계약에 없을 뿐.** qlib `TradeDecisionWO([])`가 native (§4.2) |
| "qlibx는 행동한 시점의 포트폴리오만 기술할 수 있다" | constraint-limits 문서 §6.4 | 현상 진단은 유효. 다만 원인이 "all-data-frequency closed loop 모델"이 아니라 **weight 콜백 선택**이다 |

세 문서의 결론이 달라지는 것은 아니지만, **원인 귀속이 달라진다.** 자매 문서들은 이를 제품 모델의
근본 결함으로 서술했는데, 실제로는 재사용 경계를 잘못 그은 결과이며 그만큼 되돌리기 쉽다.

## 12. 검증하지 못한 것

정직하게 분리해 둔다. 아래는 이 조사에서 **확인하지 않았다.**

1. 커스텀 `CalendarProvider`를 실제로 등록해 `SimulatorExecutor`를 끝까지 돌려보지 않았다. §5.2는
   코드 독해에 근거한 판단이며 실행 검증이 아니다.
2. `Account.update_bar_end` / `PortfolioMetrics`가 qlibx의 기존 account 표와 동일한 수치를 내는지
   대조하지 않았다.
3. `NestedExecutor`가 qlibx의 point-in-time 경계(`DatasetWindow.bounded`)와 어떻게 맞물리는지 —
   inner level에서 전략이 다시 호출될 때 데이터 cutoff를 누가 정하는지 확인하지 않았다.
4. `settle_type`(T+N 결제) 동작이 KRX 가정과 맞는지 확인하지 않았다
   ([`position.py:487-493`](../../.venv/Lib/site-packages/qlib/backtest/position.py:487)).
5. qlib `Indicator`의 `ffr`이 qlibx `ExecutionDiagnostic`의 어느 단계에 대응하는지 정밀 대조하지
   않았다.

§10-1을 시작하기 전에 최소한 1번은 spike로 확인해야 한다.

## 13. 결정이 필요한 것

1. **중간 endowment 증자를 포기하고 t0 선증자로 갈 것인가** (§6.1). 이 답에 따라 native 이관의
   이득 폭이 크게 갈린다.
2. **전역 calendar provider와 병렬 run** (§9-1). 프로세스 격리인가, run별 스위칭인가.
3. **qlib order generator를 built-in으로 노출할 것인가** — 노출한다면 §8.1-8.3의 동작을 명시한 채로,
   아니면 qlibx 자체 변형만 제공할 것인가.

1번이 가장 급하다.
