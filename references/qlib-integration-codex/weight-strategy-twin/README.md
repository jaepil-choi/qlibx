# Qlib peer momentum twin

이 디렉터리는 `qlib-integration-codex/` 아래의 비교용 WeightStrategyBase twin이다.
production `src/`를 바꾸지 않고 독립 EW peer momentum signal을 Qlib
0.9.7의 strategy/executor/accounting loop로 실행하는 실험 경계다.

현재 코드는 long-only regression baseline이다. Long-short target architecture는 synthetic mirror가
아니라 [`qlib-shorting.md`](qlib-shorting.md)의 matched capitalization 결정이며 아직 구현 전이다.

구현 flow:

```text
ConfigDrivenDataLoader (read-only import)
-> K200 universe / returns / industry / benchmark / adjusted close
-> leave-one-out EW peer return
-> QlibPeerMomentumStrategy(WeightStrategyBase)
-> benchmark + active_multiplier * signed peer alpha
-> current long-only normalized target
-> DataFrameExchange
-> SimulatorExecutor / Account / Position
```

장기 방향과 `qlib-integration-claude/`와의 책임 차이는
[`closed-loop-design.md`](closed-loop-design.md)에 기록한다. 핵심 원칙은 target matrix를
미리 만들어 재생하지 않고, 매 bar에서 Qlib execution/account feedback을 받은 뒤 다음
strategy decision을 online으로 계산하는 것이다.

`DataFrameExchange`는 Qlib feature provider 조회만 pandas quote로 대체한다. Order 생성,
tradability, cash 제약, buy/sell cost, fill, position mark-to-market, portfolio metrics는 Qlib
구현을 그대로 사용한다. Qlib trade calendar를 위해 runner가 output 아래에 최소 provider
calendar를 만든다.

pyqlib 0.9.7이 의존하는 MLflow 1.27은 최신 protobuf 7.x와 import 호환되지 않으며
`pkg_resources`도 요구한다. 그래서 root `pyproject.toml`/`uv.lock`에
`protobuf==3.20.3`, `setuptools<81`을 고정해 표준 `qlib.init()` 경로를 사용한다.
별도 환경에서 integration dependency만 맞출 때는 다음을 실행한다.

```powershell
uv pip install -r qlib-integration-codex\weight-strategy-twin\requirements.txt
```

실행:

```powershell
$env:PYTHONPATH='src;qlib-integration-codex\weight-strategy-twin'
uv run --group qlib python qlib-integration-codex\weight-strategy-twin\run_peer_momentum_backtest.py \
  --start-date 2020-01-01 \
  --active-multiplier 0.10
```

Qlib closed-loop feedback 검증용 3일 연속 손실 stop variant:

```powershell
$env:PYTHONPATH='src;qlib-integration-codex\weight-strategy-twin'
uv run --group qlib python qlib-integration-codex\weight-strategy-twin\run_peer_momentum_backtest.py \
  --variant three_day_loss_stop \
  --start-date 2025-01-02 \
  --end-date 2025-03-31 \
  --output-dir qlib-integration-codex\weight-strategy-twin\outputs\three_day_loss_stop
```

이 variant는 Qlib Account의 실제 일별 `net_return = return - cost`가 3거래일 연속
음수이면 stop을 latch한다. 다음 bar부터 signal 조회를 우회하고 빈 target을 주문으로
변환해 전량 매도한 뒤 cash를 유지한다. 일별 feedback은 `portfolio_feedback.csv`, trigger와
청산일은 `summary.json`에 저장한다.

검증:

```powershell
$env:PYTHONPATH='src;qlib-integration-codex\weight-strategy-twin'
uv run --group qlib python -m pytest qlib-integration-codex\weight-strategy-twin\tests
```

`tests/test_closed_loop_stop.py`는 마지막 청산일 signal을 의도적으로 누락한 상태에서
`-10%, -10%, -10%`의 Qlib Account feedback 뒤 다음 bar에 실제 stock position이 0이고
전액 cash가 되는지를 end-to-end로 검증한다.

기본 비용은 현재 `configs/backtest.yaml`과 동일하게 buy 3bp, sell 23bp(수수료 3bp +
세금 20bp)다. `risk_degree=0.999`, `trade_unit=None`, `min_cost=0`으로 두어 비용용 cash를
소량 남기고 KRX lot 규칙을 아직 추정하지 않는다.

중요한 시점 차이: Qlib `WeightStrategyBase`는 전 bar signal로 현재 bar close 주문을
만든다. 따라서 현재 production closed-loop의 weight-return 산술과 일별 수익률이 바로
같아지는 parity 실험은 아니다. 이번 spike는 동일 signal을 Qlib의 실제 order/account
loop에서 끝까지 실행하는 twin이며, 정확한 execution-timing parity는 다음 단계다.
