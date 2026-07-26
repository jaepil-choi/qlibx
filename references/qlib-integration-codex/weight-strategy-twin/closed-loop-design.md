# Qlib WeightStrategyBase twin direction

## 목적

`qlib-integration`은 Qlib을 precomputed target replay engine이 아니라 KWAM strategy의
execution/accounting backtester로 사용하기 위한 실험 경계다.

- Qlib 소유: order generation, fill, cost, quantity, cash, NAV, mark-to-market
- KWAM research layer 소유: signal, stateful decision, feedback 해석, portfolio construction,
  ETF financing, constraint와 research diagnostics
- 필수 invariant: decision date `t`의 strategy는 Qlib에서 완료된 `t-1` execution/account
  feedback을 본 뒤 lookahead-safe data window로 다음 target을 online 계산한다.

ETF enhanced index도 Qlib 안에 고정된 strategy template으로 만들지 않는다. Strategy가
desired active weight를 낸 뒤 KWAM-owned portfolio constructor가 direct stock, K200 ETF,
cash target으로 바꾸고 Qlib은 그 physical instrument를 실행한다. 다음 decision에는 physical
book과 ETF lookthrough exposure를 함께 feedback으로 돌려주는 방향이다.

## 현재 구현 overview

현재 twin은 production `src/`를 수정하지 않고 data loader를 read-only로 재사용한다.
이 flow는 long-only regression baseline이다. 승인된 long-short target은
[`qlib-shorting.md`](qlib-shorting.md)의 matched capitalization이며 synthetic mirror나 별도 signed
authoritative ledger를 사용하지 않는다.

```text
K200 universe / return / industry / benchmark / adjusted close
-> leave-one-out EW peer return
-> QlibPeerMomentumStrategy(WeightStrategyBase)
-> benchmark + scaled signed alpha
-> current long-only target
-> DataFrameExchange / SimulatorExecutor / Qlib Account
```

`QlibPeerMomentumStrategy`가 매 bar signal을 읽고 target을 생성하므로 target schedule을
사전에 만들지 않는다. `ConsecutiveLossStopPeerMomentumStrategy`는 첫 번째 closed-loop
feedback spike다. Qlib이 bar execution과 mark-to-market을 끝낸 뒤 `post_exe_step`에서 실제
portfolio net return을 읽고, 3일 연속 손실이면 다음 decision부터 signal과 무관하게 전량
청산한다.

현재 feedback spike가 연결한 것은 portfolio return/cost/cash/account value/turnover다.
향후 generic closed-loop adapter에서는 filled quantity, held quantity, applied/held weight,
execution diagnostics와 component/ETF lookthrough feedback까지 확장한다.

## `qlib-integration-claude`와의 차이

Claude 구현은 production strategy를 Qlib 밖에서 끝까지 실행해 desired target matrix를 먼저
만든 뒤, `PrecomputedTargetWeightStrategy`가 동일 target을 Qlib에서 재생한다. 같은 target의
own-engine/Qlib execution parity를 측정하기에는 유용하지만 Qlib execution 결과가 target
schedule에 영향을 줄 수 없다. `state.user_memory`의 decay history는 이어지지만
`state.feedback`은 execution 결과로 갱신되지 않는다.

이 integration은 반대로 strategy decision을 Qlib lifecycle 안에 둔다. Qlib의 실제 fill,
cost, holdings, cash와 NAV를 feedback으로 변환한 뒤 다음 decision을 계산하는 것이 목적이다.
따라서 precomputed target replay는 architecture가 아니라 필요할 때만 쓰는 execution 진단
도구로 취급한다.

Claude 구현에서 가져올 항목은 `OrderGenWInteract`, quote ticker/field 검증, fresh calendar
provider와 sentinel, canonical cost/config, unsupported slippage fail-fast, target/fill
diagnostics다. Target date를 vectorized engine에 맞춰 강제로 이동하거나 precomputed target을
주 strategy API로 삼는 부분은 가져오지 않는다.

## Codex capability backend

`qlib-integration-codex/kwam_qlib_backend/`는 이 문서의 장기 방향을 capability contract로
구현한다. Strategy/data/research 판단은 backend-neutral pandas view로 유지하고 physical
action만 Qlib `Order -> Exchange.deal_order -> Account/Position`에 보낸다. 이전 bar의
Qlib cash/NAV/return/fill은 다음 decision callback에만 보이며 precomputed target replay로
loss-stop을 우회하지 않는다.

구현된 범위는 dataset별 native-row subscription, run-local memory, changing universe와
blocked liquidation, integer/lot sizing, asset-class cost/tax, explicit ETL
`position_unit_factor`,
cached ensemble, side-effect 없는 historical what-if와 scheduled retraining, content-verified
Parquet artifact DB, Qlib position/cash를 보존하는 checkpoint resume다. ETF constituent는
physical order로 확장하지 않고 look-through research와 physical ETF execution을 분리한다.

## 다음 단계

1. `MatchedCapitalizationAdapter`, baseline sidecar와 signed read-only observer contract를 구현한다.
2. Acceptance workload(2,000 bars × 300 instruments)의 wall time, memory, Parquet throughput
   baseline을 기록한다.
3. Production peer momentum와 enhanced-index constructor를 adapter가 아닌 reusable strategy
   composition entrypoint에 연결한다.
4. KRX-specific lot, settlement, price-limit policy를 명시적 config로 추가한다.
5. Partial fill 뒤 남은 주문의 multi-bar carry policy와 live migration boundary를 검증한다.
