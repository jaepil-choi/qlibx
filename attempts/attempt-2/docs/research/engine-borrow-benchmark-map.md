# qlibx 자체 backtesting engine: reference lib borrow/benchmark map

Status: research note (non-normative)
작성 목적: `docs/qlibx-prd.md`의 목표·철학을 유지하되 qlib을 backend로 쓰지 않고 자체 engine을
만들 때, `references/qlib`, `references/vnpy`, `references/nautilus_trader`에서 무엇을 코드로
차용(borrow)하고 무엇을 설계로만 참고(benchmark)할지 정리한다.

조사 대상 소스 (line reference는 모두 아래 vendored snapshot 기준):

- qlib — `references/qlib/qlib/` (`main@79633dd`, MIT)
- vnpy — `references/vnpy/vnpy/` (`master@1b78494`, MIT). 특히 `alpha/`, `trader/`
- nautilus_trader — `references/nautilus_trader/nautilus_trader/` (`develop@4d14b8c`, LGPL-3.0)

최초 조사는 `pyqlib==0.9.7` wheel을 읽고 수행했다. 이후 `pyqlib` 의존성을 제거하고 qlib upstream
전체 트리를 vendoring하면서 인용 위치를 snapshot 기준으로 재검증했다. 두 소스는 qlibx가 인용하는
10개 모듈 중 9개가 동일하며, `contrib/strategy/order_generator.py`만 7행에 빈 줄이 추가되어 이후
줄이 +1 밀린다. 자세한 내용은 `references/qlib/UPSTREAM.md` 참조.

---

## 0. 먼저: 라이선스 제약 (설계 결정에 직접 영향)

| lib | License | 코드 직접 차용 |
|---|---|---|
| qlib | MIT | 가능 (저작권 고지 유지) |
| vnpy | MIT | 가능 (저작권 고지 유지) |
| nautilus_trader | **LGPL-3.0** | **비권장** |

nautilus_trader는 LGPL-3.0이다. 소스를 qlibx 배포물에 복사·번역해 넣으면 qlibx의 해당 부분이
LGPL 파생물이 되고, 현재 pyproject에 선언된 배포 형태와 충돌할 소지가 크다. 따라서 본 문서는
nautilus를 **전량 benchmark(설계·계약·명명 참고)** 로 취급하고, 코드 차용 대상에서 제외한다.
이건 손해가 아니다 — nautilus에서 가치 있는 건 대부분 Cython/Rust 구현이 아니라 *구조* 이고,
그 구조는 PRD가 이미 요구하는 것과 상당 부분 일치한다.

qlib과 vnpy는 MIT이므로 코드를 직접 가져와도 된다. 실제 "heavily borrow"의 무게중심은 여기다.

---

## 1. 결론 요약 — 3-lib 역할 분담

```text
qlib      → 회계 커널(accounting kernel). Exchange 체결·비용·거래단위·Position/Account 산술.
             주식 daily cross-sectional에 이미 정확히 맞춰진 유일한 소스. 코드 차용 중심.

vnpy      → 형태(shape). 자체 engine이 실제로 어떻게 생겼는지 보여주는 가장 가까운 전례.
             alpha lab / dataset / signal→target→order 흐름. 코드 + 설계 차용.

nautilus  → 계약(contract). 상태 권위, 클럭 분리, 사전 리스크 검증, 리컨실리에이션,
             portable catalog. PRD의 어려운 요구사항들이 어떻게 구조화되는지의 교본. 설계만 차용.
```

PRD 관점에서 한 줄로: **qlib에서 산술을 가져오고, vnpy에서 골격을 가져오고, nautilus에서
경계를 가져온다.**

---

## 2. PRD 요구사항 → 소스 매핑 표

| PRD 요구 | 1순위 출처 | 2순위 | 성격 |
|---|---|---|---|
| §11.2 Exchange 체결/비용/lot/tradability | qlib `backtest/exchange.py` | vnpy `alpha/strategy/backtesting.py` | borrow |
| §11.4 long-only Position 제약, 음수 수량 거부 | qlib `backtest/position.py` | — | borrow |
| §3.2 Account/NAV/turnover/cost 누적 | qlib `backtest/account.py` | vnpy `PortfolioDailyResult` | borrow |
| §11.3 target→order 변환 + 전 주문 진단 | qlib `contrib/strategy/order_generator.py` (반면교사) + `backtest/report.py::Indicator` | vnpy `AlphaStrategy.execute_trading` | borrow + 재설계 |
| §9.5 closed-loop feedback (execute_result) | qlib `strategy/base.py`, `backtest/executor.py` | nautilus `Portfolio.update_order/position` | borrow |
| §9.6 4개 클럭 분리 (observation/decision/execution/monitoring) | **nautilus** `common/component.pyx` Clock/TestClock/TimeEvent | — | benchmark |
| §10.9 pre-execution constraint validation | **nautilus** `risk/engine.pyx` | — | benchmark |
| §14.4 OMS reconciliation / commit boundary | **nautilus** `execution/reports.py`, `execution/engine.pyx` | — | benchmark |
| §12.5 file-backed portable catalog | **nautilus** `persistence/catalog/parquet.py` | vnpy `alpha/lab.py` | benchmark + borrow |
| §12.2 artifact envelope / 저장 lifecycle | vnpy `alpha/lab.py` | nautilus catalog | borrow(단순형) |
| §8.4 signal built-in operations | vnpy `alpha/dataset/{ts,cs,math}_function.py`, `processor.py` | qlib `data/ops.py` | borrow |
| §13.2 built-in analysis / 통계 | **nautilus** `analysis/` (plugin 구조) | vnpy `calculate_statistics` | benchmark + borrow |
| §4.3 actual state가 authority | **nautilus** `cache/cache.pyx` 단일 상태 저장소 | — | benchmark |
| §10.5 optimizer backend 경계 | qlib `contrib/strategy/optimizer/` | — | borrow(주의) |

---

## 3. qlib — borrow 중심

### 3.1 반드시 가져올 것 (거의 그대로)

**(a) `backtest/exchange.py::_calc_trade_info_by_order` (L859-950)**

이게 qlib에서 가장 값어치 있는 100줄이다. 주식 daily 체결의 현실적 clipping 순서가
그대로 코드화돼 있다:

```
deal_amount = order.amount
→ _clip_amount_by_volume        (거래량 참여율 제한, L786)
→ impact cost = impact * (trade_val/total_val)^2   (제곱 충격비용)
→ SELL: min(current_amount, deal_amount) → round_amount_by_trade_unit
        → 현금이 수수료를 못 내면 deal_amount = 0
→ BUY : 현금 부족 시 _get_buy_amount_by_cash_limit (L834) → lot 반올림
→ trade_cost = max(trade_val * cost_ratio, min_cost)
→ trade_val <= 1e-5 이면 cost = 0
```

특히 **"마지막 주식을 파는 경우에만 lot 반올림을 생략"** 하는 처리(L904, `np.isclose(deal_amount,
current_amount)`)는 실제로 짜보면 반드시 걸리는 함정이다. 여기서 반올림하면 잔여 주식이 영원히
청산되지 않는다.

관련해 함께 가져올 것:
- `check_stock_limit` (L338) — 상하한가 판정. `limit_threshold`가 tuple/float/str 세 형태를 받는 처리
- `check_stock_suspended` (L378) — 거래정지
- `is_stock_tradable` (L404) — 위 둘의 결합
- `round_amount_by_trade_unit` (L761), `get_amount_of_trade_unit` (L728) — factor 기반 lot 산술
- `_get_vol_limit` (L295) — volume threshold 선언 파싱

**PRD 정합성 주의:** qlib은 이 clipping 결과를 `logger.debug`로만 흘리고 버린다
(L830, L917, L928, L936). PRD §11.3·§4.6은 **instrument별 conversion/rounding/clipping/skip 사유를
모두 보존** 하라고 요구한다. 따라서 차용 시 각 clip 지점에서 구조화된 diagnostic record를
반환값에 실어야 한다. 산술은 그대로, 진단은 새로.

**(b) `backtest/position.py::Position`**

`_buy_stock`/`_sell_stock`/`_del_stock`(L342-385), `settle_start`/`settle_commit`(L487-500),
`get_stock_weight_dict(only_stock=)`(L456). 미보유 SELL과 보유 초과 SELL을 거부하는 지점이
PRD §11.4가 말하는 바로 그 제약이며, `InfPosition`(L503)은 "제약 없는 position"이 필요한
child research/what-if 용도의 깔끔한 전례다.

`fill_stock_value`(L280) — 초기 endowment를 과거 가격으로 채우는 로직은 PRD §11.7 static
initial-endowment profile에 직접 대응한다.

**(c) `backtest/account.py`**

- `AccumulatedInfo`(L35) — return/cost/turnover 누적기. 30줄짜리지만 계약이 명확하다.
- `update_bar_end`(L338) — bar 종료 시 mark-to-market + portfolio metric 기록. PRD §9.7
  "no-trade bar에도 account mark가 진행되어야 한다"의 구현 지점.
- `is_port_metr_enabled`(L132) — portfolio metric을 명시적으로 켜고 끄는 구조. PRD §9.7이
  "required profile은 portfolio metrics를 명시적으로 활성화" 하라고 한 것과 일치.

**(d) `backtest/report.py::Indicator` (L249-650)**

주문 단위 진단 집계기. `_update_order_trade_info`, `_update_order_fulfill_rate`,
`_agg_order_price_advantage`, `_cal_trade_fulfill_rate` 등. PRD §13.2가 요구하는
"cost, fill and desired-versus-realized reconciliation"의 상당 부분이 여기 이미 있다.
`PortfolioMetrics`(L22)의 record 스키마도 그대로 참고 가능.

**(e) `backtest/decision.py::Order` (L36-152)**

`amount` / `deal_amount` 분리, `factor`, `key_by_day`, `parse_dir`가 numpy array까지 받는 처리.
`TradeRange`/`TradeRangeByTime`(L206-300)은 execution clock 범위 표현의 좋은 원형이다.

### 3.2 설계만 참고할 것

**`strategy/base.py::BaseStrategy.generate_trade_decision(execute_result)`**

PRD §2.4·§9.5의 closed-loop 계약 그 자체. qlib을 backend로 안 쓰더라도 **이 시그니처는
유지할 가치가 있다** — PRD가 `BaseStrategy`, `TradeDecision`을 "Qlib upstream compatibility가
직접 요구하는 명칭"으로 예외 처리해뒀고, 나중에 qlib 상호운용이 필요해질 때 비용이 0에 가깝다.

다만 `level_infra`/`common_infra`의 문자열 키 dict 기반 서비스 로케이터(`self.common_infra.get(
"trade_account")`)는 따라가지 말 것. 타입이 사라지고 PIT 경계를 강제할 수 없다. nautilus의
명시적 생성자 주입(§5.4)으로 대체.

**`backtest/executor.py::NestedExecutor` (L310-500)**

multi-level execution clock의 유일한 실전 참고 자료. 다만 PRD §9.6이 직접 못박은 대로,
NestedExecutor는 arbitrary observation scheduler나 PIT cutoff를 자동으로 주지 않는다.
계층 구조 아이디어만 취하고 클럭 자체는 nautilus 방식으로.

**`backtest/high_performance_ds.py`**

`BaseQuote`/`NumpyQuote` — pandas MultiIndex 조회를 numpy 배열 + 인덱스 맵으로 우회하는
성능 계층. PRD §9.6 "dense evaluation profile은 매 point마다 unrelated full history를 다시
load하지 않고 declared lookback과 bounded-load expectation 안에서 실행" 에 대응.
아이디어는 유효하나, qlibx는 이미 duckdb/pyarrow를 의존성에 두고 있으므로 그쪽으로 다시 짜는 게 낫다.

### 3.3 명시적으로 피할 것 (PRD가 이미 금지한 것들)

`contrib/strategy/order_generator.py::OrderGenWInteract` (L51-142)와
`signal_strategy.py::WeightStrategyBase.generate_trade_decision` (L345)은
**PRD §11.3의 금지 목록을 거의 항목별로 실증하는 코드**다. 반면교사로 읽을 가치가 있다:

| 코드 위치 | 동작 | 위반하는 PRD 조항 |
|---|---|---|
| `order_generator.py` L115-121 | 현금 부족 시 tradable 주식 전량 매도로 조용히 폴백 | §4.6 silent fallback 금지 |
| L124 `current_tradable_value /= 1 + max(open,close)` | 비용을 근사치로 뭉갬 | §4.6 |
| `generate_amount_position_from_weight_position` (exchange.py L534) | tradable subset만 남기고 weight 재정규화 | §9.3 flexible budget 위반, §11.3 명시 금지 |
| 전 경로 | 스킵된 종목의 사유가 반환값에 없음 | §11.3 all-order diagnostics |
| `WeightStrategyBase` L345 | trigger 개념 없음 → 매 step 재제출 | §5.6 price-drift rebalance 금지 |

즉 **qlib의 weight→order 경로는 통째로 재설계 대상**이고, qlib에서 가져올 것은 그 아래층
(Exchange 산술)뿐이다. 이 분리가 이번 설계에서 가장 중요한 판단이다.

`EnhancedIndexingStrategy`(L375)와 `contrib/strategy/optimizer/`는 PRD §10.5가 "수학적으로
동일하다고 가정하지 말라"고 이미 경고해뒀다. characterization test 없이 채택 금지.

---

## 4. vnpy — 자체 engine의 골격

vnpy에서 진짜 값어치 있는 건 CTA 쪽이 아니라 **`vnpy/alpha/`** 다. 이건 vnpy가
qlib을 벤치마크해서 만든 자체 alpha research 스택으로, **"qlib을 안 쓰고 qlib 같은 걸 만든다"는
지금 과제와 정확히 같은 문제를 이미 푼 사례**다. 우선순위 최상.

### 4.1 `alpha/strategy/backtesting.py` (944줄) — 가장 가까운 전례

daily 다종목 포트폴리오 백테스터 전체가 여기 한 파일에 있다. 구조:

```
set_parameters → load_data → run_backtesting(dts 순회 → new_bars)
  → cross_limit_order (체결 시뮬)
  → PortfolioDailyResult.calculate_pnl(pre_closes, start_poses, sizes, rates)
  → calculate_result → calculate_statistics
```

가져올 것:
- **`PortfolioDailyResult.calculate_pnl`의 trading_pnl / holding_pnl 분해.**
  qlib의 `AccumulatedInfo`에는 이 분해가 없다. PRD §13.2 attribution과 §10.10
  flexible-budget attribution에 직접 쓰인다. `pre_closes`/`start_poses`를 일별로 넘겨가며
  체이닝하는 방식(L186-199)이 그대로 참고 대상.
- `calculate_statistics` (L228-380) — polars 기반. `balance = net_pnl.cum_sum() + capital`,
  highlevel/drawdown/ddpercent, max_drawdown_duration을 `arg_min`/`arg_max`로 구하는 방식.
  **파산(balance <= 0) 시 통계 계산을 거부** 하는 처리(L280-282)는 PRD §4.6의
  "명시적 실패가 silent fallback보다 우선"과 같은 정신이다.
- polars 채택 자체. qlibx는 pandas/pyarrow/duckdb를 이미 의존성에 두고 있으니 polars를
  더 넣을 필요는 없지만, 컬럼 기반 일별 결과 테이블 스키마는 그대로 쓸 만하다.

### 4.2 `alpha/strategy/template.py::AlphaStrategy` (205줄) — target-position 패턴

**`pos_data` / `target_data` 이원 관리 + `execute_trading(bars, price_add)`** (L133-185).
PRD §4.3 "requested target은 intention이며 realized holding이 아니다"를 가장 간결하게 구현한
코드다. `update_trade`(L58)에서 체결이 들어올 때만 `pos_data`가 움직이고, `target_data`는
전략이 자유롭게 쓴다.

`execute_trading`의 diff 분해(long/short × open/close 4방향)는 주식 long-only에서는
과하지만, **PRD §11.5-11.6 matched-capitalization 프로파일에서 composite `C = B + A`를
실제 주문으로 분해할 때 이 4방향 분해가 그대로 필요해진다.** 지금은 필요 없어 보여도
나중에 다시 볼 파일이다.

가져오되 바꿀 것: `execute_trading`은 현재 bar가 있는 종목만 주문한다(L138). 없는 종목은
사유 없이 조용히 빠진다 — PRD §4.6 위반. skip reason을 반환하도록 고쳐야 한다.

### 4.3 `alpha/lab.py::AlphaLab` (480줄) — artifact 저장소의 최소 원형

```
save/load/remove/list_all × {bar_data, component_data, contract_setting, dataset, model, signal}
```

PRD §12의 catalog가 요구하는 것에 비하면 한참 단순하다 (fingerprint, lineage, envelope,
atomic publication, conflict 처리가 전부 없다). 하지만 **"lab_path 하나 아래 file-backed로
전부 넣는다"** 는 형태와 `list_all_*` API 표면은 PRD §12.5의
"MongoDB나 always-on service를 기본 요구하지 않는다"와 정확히 맞는다.

→ vnpy에서 *형태*를 가져오고, *내용물*(envelope/lineage/publication semantics)은 nautilus의
catalog와 PRD §12.2에서 채운다.

`load_component_data`/`load_component_symbols`/`load_component_filters` (L245-348)는
지수 구성종목의 시점별 유효구간 처리로, PRD §7.7 universe와 §10.6 ETF look-through의
출발점으로 쓸 수 있다.

### 4.4 `alpha/dataset/` — signal 연산 built-in

PRD §8.4가 요구하는 built-in signal operations의 후보가 거의 그대로 있다:

- `ts_function.py` (329줄) — `ts_delay/min/max/argmax/rank/sum/mean/std/slope/quantile/rsquare/
  resi/corr/cov/decay_linear/product/delta` (22개)
- `cs_function.py` — `cs_rank/mean/std/sum/scale`
- `processor.py` (201줄) — `process_cs_norm`, `process_robust_zscore_norm`,
  `process_cs_rank_norm`, `process_ts_norm`, `process_replace_inf`, `process_cs_fill_na`
- `datasets/alpha_158.py`, `alpha_101.py` — 검증용 factor 세트

PRD §8.4 목록과 대조하면 **cross-sectional rank/zscore, winsorization, missing/inf 정책,
lag/rolling/decay가 전부 커버**된다. 빠진 것은 industry/sector demeaning, beta
residualization, hump/barrier turnover control 3가지뿐이다.

`dataset/template.py::AlphaDataset` (305줄)의 `add_feature`/`set_label`/`add_processor(task,...)`
/`fetch_raw|infer|learn(segment)` 구조는 qlib의 `DataHandlerLP` 를 단순화한 것으로,
**learn/infer 데이터 분리** (PRD §8.1 fit/inference 분리, leakage 방지)를 훨씬 읽기 쉽게
표현한다. qlib DataHandlerLP보다 이쪽을 따르는 걸 권한다.

### 4.5 `trader/object.py`, `trader/constant.py`

`@dataclass` 기반 `BarData/OrderData/TradeData/PositionData/AccountData/ContractData`와
`Direction/Offset/Status/OrderType/Product/Interval` enum. qlib의 `Order` dataclass보다
필드가 풍부하고(특히 `Status`: SUBMITTING/NOTTRADED/PARTTRADED/ALLTRADED/CANCELLED/REJECTED),
PRD §4.3이 요구하는 "Partial, rejected, blocked, zero-fill과 expired execution은 canonical
result" 를 표현하기에 적합하다. qlib `Order`에는 상태 개념 자체가 없다.

`trader/converter.py`(OffsetConverter), `trader/optimize.py`(파라미터 탐색)도 나중에 볼 것.

---

## 5. nautilus_trader — 계약과 경계 (설계만)

LGPL이므로 코드는 안 가져온다. 하지만 **PRD에서 가장 구현이 막막한 조항들이 여기 전부
구조화돼 있다.** 읽는 목적은 "어떤 객체가 어떤 권위를 갖는가"의 답을 얻는 것이다.

### 5.1 `common/component.pyx` — Clock 추상화 (PRD §9.6의 답)

```
Clock (L130)  ├─ TestClock (L623)   : set_time / advance_time(to_time_ns) → list[TimeEvent]
              └─ LiveClock (L839)
  공통: set_time_alert / set_timer / cancel_timer / next_time_ns
TimeEvent (L1013), TimeEventHandler (L1144)
```

PRD §9.6은 observation / decision / execution / monitoring 4개 클럭을 요구하고, §13.3은
"이 클럭들을 하나의 Strategy loop로 강제하지 말라"고 한다. nautilus의 답은 **timer를 등록하면
TimeEvent가 큐로 나오고, 백테스트에서는 `TestClock.advance_time`이 그 시각까지의 이벤트를
정렬해 뱉는다** 는 것이다. 클럭 개수가 몇 개든 하나의 시간축 위에서 결정론적으로 병합된다.

→ qlibx 권고: 단일 `advance_to(t)` 이벤트 큐 위에 4개 클럭을 timer로 얹는다. qlib의
`TradeCalendarManager` step 방식으로는 decision과 monitoring의 독립적 cadence를 표현할 수 없다.

### 5.2 `risk/engine.pyx` — pre-execution validation (PRD §10.9의 답)

```
execute(command) → _handle_submit_order → _check_order
    ├─ _check_order_price     (L608)
    ├─ _check_order_quantity  (L633)
    └─ _check_orders_risk     (L642) / _check_orders_risk_for_account (L666)
→ 통과: _send_to_execution (L1185)
→ 실패: _deny_command / _deny_new_order / _deny_order(reason) (L1073-1132)
set_trading_state(TradingState)  (L228)  — ACTIVE / REDUCING / HALTED
```

핵심 구조: **RiskEngine은 Strategy와 ExecutionEngine 사이에 물리적으로 끼어 있고,
통과시키거나(pass-through) 사유와 함께 거부한다(deny). 조용히 수정하지 않는다.**

PRD §10.9가 요구하는 "warning은 진행 가능 / error는 제출 중단 또는 explicit override"는
`TradingState`와 `_deny_*(reason)` 조합으로 표현된다. PRD §10.8(best-effort adjustment)과
§10.9(independent validation)의 책임 분리도 nautilus에서는 ExecAlgorithm(조정) vs
RiskEngine(검증)으로 이미 갈라져 있다.

→ qlibx 권고: `deny(reason)` 대신 구조화된 finding record를 반환하되, **"통과 아니면 사유 있는
거부, 조용한 수정 없음"** 이라는 불변식은 그대로 채택.

### 5.3 `execution/reports.py` + `execution/engine.pyx` — reconciliation (PRD §14.4의 답)

```
ExecutionReport (L75)
 ├─ OrderStatusReport   (L95)  : is_open, is_order_updated(order) ← 내부 상태와 외부 상태 비교
 ├─ FillReport          (L619)
 └─ PositionStatusReport(L859) : create_flat()
ExecutionMassStatus (L1038) : order/fill/position report 묶음

ExecutionEngine.reconcile_execution_state(timeout)  (L605)
                .reconcile_execution_report(report) -> bool  (L627)
                .reconcile_execution_mass_status(mass)  (L644)
```

PRD §14.2-14.4의 prepared decision → outbox → OMS → confirmed result → reconcile → commit
흐름에 1:1로 대응한다. 특히:

- 세 종류 report(order status / fill / position status)를 **분리** 한 것 — PRD §14.3의
  "Requested and filled quantity / Fill price, cost and time / Account snapshot reference"
- `is_order_updated(order)`(L287) — 외부 보고와 내부 상태의 delta 판정. PRD §14.4
  "Delta는 prior requested target이 아니라 actual holding에서 계산한다"
- `create_flat()`(L919) — "포지션 없음"을 명시적 보고로 표현. 무응답과 0을 구분한다.
  PRD §4.6이 요구하는 구분.
- 모든 report에 `to_dict`/`from_dict`가 있음 — PRD §12.2 portable artifact

### 5.4 `cache/cache.pyx` + `system/kernel.py` — 상태 권위 (PRD §4.3의 답)

`Cache`가 orders/positions/accounts/instruments의 **단일 저장소**이고, Portfolio·RiskEngine·
Strategy가 전부 여기서 읽는다. 자체 사본을 들고 있지 않는다. `check_integrity`(L480),
`check_residuals`(L798), `snapshot_position_state`(L2512)가 상태 일관성을 강제한다.

`NautilusKernel`(kernel.py L101)은 clock / msgbus / cache / portfolio / data_engine /
risk_engine / exec_engine / trader를 **생성자에서 명시적으로 조립** 하고 property로만 노출한다.
qlib의 `CommonInfrastructure.get("trade_account")` 문자열 키 방식과 대조된다.

→ qlibx 권고: qlib의 infra dict를 그대로 베끼지 말고 kernel 스타일 명시적 조립으로 갈 것.
PRD §7.9(provider/process isolation)와 §12.8(parallel-agent) 둘 다 전역 가변 상태를 싫어하는데,
문자열 키 서비스 로케이터는 정확히 그 반대 방향이다.

### 5.5 `persistence/catalog/parquet.py` — file-backed catalog (PRD §12.5의 답)

`ParquetDataCatalog`: `write_data`, `query`, `consolidate_catalog`, `delete_data_range`,
`_min_max_from_parquet_metadata`(L570), `_deduplicate_table`(L820),
`_validate_table_metadata`(L781), `from_uri`(L202).

PRD §12.5-12.6이 요구하는 것 중 여기 이미 있는 것: file-backed 단일 조회면, parquet metadata
기반 시간범위 인덱싱(전체 읽지 않고 min/max), 중복 제거, 스키마 검증.
없는 것: content fingerprint, dependency edge, terminal status, atomic visibility commit.

→ qlibx 권고: 물리 저장 계층은 이 구조를 참고(디렉터리 레이아웃 + parquet metadata 인덱싱),
그 위에 PRD §12.2 envelope와 §12.6 publication semantics를 얹는다. duckdb가 이미 의존성에
있으므로 catalog 인덱스는 duckdb로 두는 게 자연스럽다.

### 5.6 `analysis/` — 통계 plugin 구조 (PRD §13.1의 답)

```
PortfolioStatistic (statistic.py L25)
  ├─ fully_qualified_name()
  ├─ name (CamelCase → "Camel Case" 자동 변환)
  ├─ calculate_from_returns(returns)
  ├─ calculate_from_realized_pnls(...) / _orders(...) / _positions(...)
PortfolioAnalyzer (analyzer.py L38)
  register_statistic / deregister_statistic / calculate_statistics(account, positions)
  get_performance_stats_{pnls,returns,general,returns_vs_benchmark}
```

**통계 하나 = 클래스 하나 = 등록 가능한 plugin.** PRD §13.1(analysis와 rendering 분리),
§13.4(public extension points: Analyzer and reporter)에 그대로 대응한다. 반환값이
"JSON serializable primitive"여야 한다는 제약(statistic.py L29 주석)도 PRD §12.2 portable
artifact와 일치.

vnpy의 `calculate_statistics`는 350줄짜리 단일 함수라 확장이 안 되고, qlib의 `risk_analysis`도
마찬가지다. **이 부분만은 nautilus 구조가 압도적으로 낫다.**

`backtest/results.py::BacktestResult`(L20)의 필드 목록(run_config_id, instance_id, run_id,
run_started/finished, elapsed_time, iterations, total_events/orders/positions, summary,
stats_pnls, stats_returns)은 PRD §12.2 envelope의 좋은 출발점이다.

### 5.7 `backtest/models/{fee,fill}.pyx` — 모델 교체 가능성

`FeeModel` 추상 + `MakerTaker/Fixed/PerContract` 구현, `FillModel` 추상 + 9종 구현.
qlib은 비용/체결이 `Exchange` 생성자 파라미터로 하드코딩돼 있어 교체가 안 된다.

→ qlibx 권고: Exchange 산술은 qlib에서 가져오되, **비용 모델과 체결 모델은 이 방식으로
인터페이스를 뽑아낸다.** PRD §11.2가 프로파일별로 "Cost and tax schedule / Volume
participation and clipping"을 명시하라고 요구하므로 교체 가능해야 한다.
주식 daily에는 nautilus의 orderbook 기반 FillModel 9종은 과하다 — 추상화만 취할 것.

---

## 6. 종합 아키텍처 제안

```text
┌─ qlibx control plane (신규) ──────────────────────────────────────┐
│  dataset registration / PIT / capability binding / frozen config  │
│  ← 신규 작성. PRD §7. 세 lib 모두에 대응물 없음.                    │
└───────────────────────────────────────────────────────────────────┘
                              │
┌─ research layer ──────────────────────────────────────────────────┐
│  AlphaDataset / processor / ts_cs functions   ← vnpy alpha (borrow)│
│  SignalProducer / AlphaPolicy / Ensemble      ← 신규 (PRD §8-10)   │
└───────────────────────────────────────────────────────────────────┘
                              │
┌─ execution kernel (신규 조립) ────────────────────────────────────┐
│  Kernel: clock/cache/portfolio/exchange 명시적 조립  ← nautilus 구조│
│  Clock × 4 (obs/decision/exec/monitor)               ← nautilus     │
│  Strategy.generate_trade_decision(execute_result)    ← qlib 시그니처│
│  target→order conversion + 전 주문 진단              ← 신규 (qlib 반면교사)│
│  ConstraintAdjuster (best-effort)                    ← 신규         │
│  Validator (pass or deny-with-reason)                ← nautilus RiskEngine│
│  Exchange 체결 산술                                   ← qlib (borrow)│
│  Position / Account / AccumulatedInfo                ← qlib (borrow)│
│  trading_pnl / holding_pnl 분해                      ← vnpy (borrow)│
└───────────────────────────────────────────────────────────────────┘
                              │
┌─ evidence plane ──────────────────────────────────────────────────┐
│  Artifact envelope + lineage        ← 신규 (PRD §12.2)             │
│  file-backed catalog (parquet+duckdb) ← nautilus 구조 + vnpy lab 표면│
│  PortfolioStatistic plugin           ← nautilus analysis (구조)     │
│  Reconciliation reports              ← nautilus execution/reports   │
└───────────────────────────────────────────────────────────────────┘
```

---

## 7. 권장 구축 순서

각 단계는 앞 단계의 결과물만 의존한다.

1. **Domain objects** — Order/Fill/Position/Account/Bar dataclass.
   vnpy `trader/object.py` 필드 + qlib `Order`의 `amount`/`deal_amount`/`factor` 결합.
   `Status` enum으로 partial/rejected/blocked/expired를 표현 (PRD §4.3).

2. **Exchange 체결 커널** — qlib `_calc_trade_info_by_order` 이식 + 모든 clip 지점에
   구조화 diagnostic 부착. 여기가 전체에서 가장 검증이 중요한 부분이므로
   qlib과의 characterization parity test를 먼저 세울 것 (PRD §16.2).

3. **Position/Account + 일별 결과** — qlib Position/AccumulatedInfo + vnpy
   trading/holding pnl 분해.

4. **Clock/Kernel 조립** — nautilus TestClock 방식 단일 이벤트 큐. 4개 클럭 등록.
   여기서 PRD §9.7 hold/dense state와 §9.8 trigger가 자연스럽게 표현되는지 확인.

5. **Strategy → target → order 경로** — vnpy `pos_data`/`target_data` 패턴 +
   전 주문 conversion 진단. qlib order_generator는 참고만.

6. **Validator** — nautilus RiskEngine 구조. pass or deny-with-finding.

7. **Artifact + catalog** — vnpy AlphaLab 표면 + nautilus parquet catalog 물리구조 +
   PRD §12.2 envelope.

8. **Analysis plugin** — nautilus PortfolioStatistic 구조.

9. **Signal/dataset 계층** — vnpy alpha/dataset 이식.

10. **Reconciliation / production boundary** — nautilus execution reports 구조.

2번이 끝나면 qlib 대비 parity를 측정할 수 있고, 5번이 끝나면 end-to-end long-only 백테스트가
돈다. 6번 이후는 PRD 고유 요구사항이라 참고할 코드가 거의 없다 — 그래서 뒤로 미룬다.

---

## 8. 남은 위험과 미해결 질문

- **qlib parity oracle을 유지할 것인가.** PRD §16.2 native migration gate는 characterization
  parity를 요구한다. qlib을 backend에서 뺐어도, Exchange 산술 검증용 oracle로는
  `pyqlib==0.9.7`을 dev dependency에 남겨두는 게 안전하다. 결정 필요.
- **polars 도입 여부.** vnpy alpha 코드는 전부 polars 기반이다. 이식 시 pandas로 다시 쓸지,
  polars를 의존성에 추가할지. 현재 pyproject는 pandas/pyarrow/duckdb만 있다.
- **matched-capitalization (PRD §11.5-11.7)** — 세 lib 어디에도 대응물이 없다. 자체 engine을
  쓰면 qlib의 long-only Position 제약이 사라지므로, PRD가 이 프로파일을 계속 필요로 하는지
  자체가 재검토 대상이다. qlib 제약을 우회하려고 만든 구조였기 때문이다.
- **nautilus LGPL 경계** — 설계 참고와 파생물의 선. 클래스명·메서드 시그니처 수준의
  유사성은 문제없으나, 알고리즘을 줄 단위로 옮기는 건 피할 것.
