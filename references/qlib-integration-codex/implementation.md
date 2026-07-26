# Qlib Migration Implementation Notes

## 1. 현재 구현 상태

현재 `qlib-integration-codex/`에는 다음이 구현되어 있다.

- pyqlib 0.9.7 `Order -> Exchange -> Account/Position` execution/accounting backend
- direction-aware tradability, volume/cash/position/lot stage diagnostics
- KRX stock/ETF cost와 tax policy
- Qlib position/cash/NAV를 보존하는 checkpoint/resume
- optimizer, research DAG, dataset/run/artifact lineage
- deterministic alpha/backtest run ID, DuckDB catalog와 immutable Parquet artifact
- stored-run reporting과 stored-alpha ensemble
- 독립 Qlib `BaseStrategy` peer-momentum twin
- matched-capitalization signed-weight execution과 active reporting
- 실제 peer momentum long-short public workflow runner

Goal 0~15와 native peer-momentum twin은 long-only regression baseline이다. 기존 production
runtime의 실행 방식을 바꾸지는 않았으며, migration runtime인 `qlib-extended`에 signed execution을
추가했다.

## 2. 2026-07-23 Accepted Decision

Qlib long-only `Position`을 유지하면서 signed alpha를 실행하는 target architecture로 matched
capitalization을 채택했다.

폐기한 접근:

- synthetic inverse/mirror ticker
- long/short 별도 Qlib account
- 상장 전 positive inventory seed
- `Exchange.deal_order(position=None)`와 독립 signed authoritative ledger
- Qlib source fork 또는 `.venv` 직접 수정

채택한 상태 계약:

```text
composite = baseline + active_signed
active_signed = composite - baseline
```

Qlib `Account`/`Position`은 composite execution state를 소유한다. Baseline sidecar는 matched
capitalization state만 소유한다. Signed observer는 read-only projection이다.

Goal 16 범위의 runtime 구현과 실제 2025 peer momentum long-short smoke가 완료됐다. Matched
state checkpoint/resume와 core lifecycle acceptance도 구현됐다. Corporate-action normalization은
upstream ETL 책임이며 integration runtime은 non-unit adjustment factor를 거부한다. Delisting의
explicit closeout/unavailable-price policy는 별도 market-data lifecycle 범위다.

## 3. 구현 순서

### Stage 1 — Domain contracts

- `SignedActiveIntent`
- `MatchedCapitalizationState`
- `CapitalizationEvent`
- `CompositeExecutionIntent`
- `SignedExecutionObservation`
- point-in-time mask와 failure reason schema

이 단계에서는 Qlib object를 domain type에 노출하지 않는다.

### Stage 2 — Capitalization adapter

- Current active NAV와 per-name short cap으로 required baseline capacity 계산
- First-observed/first-tradable activation
- Existing ticker capacity top-up
- Quantity와 matching cash debit의 atomic update
- NAV-neutrality, funding reserve와 non-negative composite validation

Baseline activation은 market order가 아니며 active order보다 먼저 적용한다.

### Stage 3 — Qlib lifecycle integration

- Qlib strategy/executor bar lifecycle 안에 capitalization hook 연결
- Underlying active BUY/SELL order 생성
- Partial fill과 direction-specific blocking 보존
- Upstream-normalized market input과 universe exit/re-entry 처리
- Checkpoint/resume에 baseline sidecar와 activation sequence 추가

### Stage 4 — Signed observer and persistence

- Qlib dealt amount에서 active signed fill 생성
- `A = C - B` held projection
- Composite/baseline/active cash, quantity와 NAV reconciliation
- Baseline event와 signed audit Parquet artifact 추가
- Backtest fingerprint에 policy/config/backend code 포함

### Stage 5 — Reporting

- Qlib standard portfolio return을 canonical active return에서 제외
- Stored composite/baseline artifact로 active money PnL 계산
- Active notional denominator를 report metadata에 명시
- Member/ensemble/enhanced-index signed attribution 제공

### Stage 6 — Strategy integration

- Stored signed alpha single-member execution
- Multiple alpha ticker-level crossing/netting
- Long-short ensemble execution
- Enhanced-index intent와 composite physical book 연결

## 4. Contract Test Matrix

### Causality

- Future ticker column은 존재하지만 observed 이전 target/inventory/position은 0
- Future membership과 future target 변경이 과거 activation/buffer에 영향 없음
- Decision은 이전 completed bar feedback만 사용

### Capitalization

- First-tradable activation 직후 NAV delta 0
- Same-bar active short는 underlying SELL
- Top-up은 부족분만 반영
- Funding reserve 부족 fail-fast

### Execution

- Short increase, cover와 long/flat/short cross-zero
- Partial fill은 dealt amount로 realized signed quantity 갱신
- Suspension, upper/lower limit, volume과 lot clipping
- Buy/sell asymmetric cost

### State lifecycle

- Universe exit/re-entry와 retained baseline
- Upstream-normalized execution/mark price와 physical unit contract
- Checkpoint/resume 전후 identical state/artifact
- Delisting policy fail-fast 또는 explicit closeout

### Reconciliation

- `B >= 0`, `C >= 0`, `A = C - B`
- `composite_nav = baseline_nav + active_nav`
- Existing production signed holdings ledger와 deterministic differential parity
- Stored artifacts만으로 signed audit/report 재생성

### Goal 16 RED contract

`tests/test_goal_16_matched_capitalization.py`는 구현 class나 hook이 아니라
`qlib_extended` public facade와 catalog artifact만 사용한다. 다음 관측 결과가 이 migration의
첫 acceptance boundary다.

- Full ticker axis에서 아직 observed되지 않은 ticker의 signed target, baseline과 composite 수량은 0
- First-observed bar에서 signed short target은 underlying SELL로 체결되고 `C >= 0` 유지
- Volume partial fill 뒤 realized signed quantity는 target이 아니라 dealt amount와 일치
- `signed_positions`에서 intended/target/held signed quantity와 baseline/composite quantity를 직접 관측
- `active_account_daily`의 money PnL과 denominator로 active return 계산
- 큰 composite capitalization reserve와 작은 active booksize를 분리해도 active PnL과
  denominator가 변하지 않음
- `account_daily = baseline_account_daily + active_account_daily` NAV reconciliation
- Stored alpha ensemble은 ticker-level signed intent를 먼저 netting하고 0 net intent에는 주문과
  capitalization이 없음
- Capitalization policy 변경은 alpha를 재실행하지 않고 backtest identity와 baseline 결과만 변경

2026-07-23 최초 RED 실행은 다음 command를 사용했다.

```powershell
$env:KWAM_RUN_QLIB_CONTRACTS='1'
uv run --group qlib python -m pytest `
  qlib-integration-codex\tests\test_goal_16_matched_capitalization.py -q
```

최초 결과는 `5 failed`이며 모두 public config가 아직 `target_semantics`,
`matched_capitalization`, `execution`을 허용하지 않는 동일한 최초 경계에서 실패했다. Production
구현은 config에서 시작해 각 경제적 result assertion을 순서대로 green으로 만들었다.

최초 Goal 16 결과는 `5 passed`였다. 2026-07-23 lifecycle closure 뒤 Goal 16은
`15 passed`, 전체 qlib-integration suite는 같은 opt-in 환경에서 `93 passed`다.

추가된 automated acceptance는 다음을 직접 검증한다.

- Short increase, cover, flat/long/short cross-zero의 Qlib dealt-amount realized transition
- Baseline reserve와 active trading cash의 분리, causal activation/top-up/release event
- Blocked universe exit, delayed liquidation과 retained/`active_short_only` re-entry
- Baseline cash/quantity, prior baseline/active NAV와 event sequence의 JSON checkpoint round-trip
- Resume run과 uninterrupted run의 모든 observable table 및 result hash 동일성
- Production `execute_holdings_ledger_step` 대비 quantity, cash, absolute turnover와 PnL exact parity
- Stored member alpha/weight, signed position/account/price만 사용한 ensemble attribution과 active report
- Overnight/intraday/cost attribution과 `active_account_daily.money_pnl` reconciliation
- Stored member ensemble intent → benchmark+active Goal 9 optimizer → Qlib physical execution
- Optimizer constituent/physical artifact와 realized lot-rounded position/cash의 attribution
- 첫 Qlib fill 뒤 realized 54%/45% holding과 1% cash가 다음 optimizer current state로 전달되는 feedback

`position_unit_factor`의 split quantity transformation test는 삭제했다. Public config에서는 해당
dataset이 optional이고, compatibility 입력이 있으면 all-ones만 허용한다. 실제 실행 계약은
upstream ETL이 정규화한 `execution_price`, optional `valuation_price`, universe와 physical
quantity다.

이 경계 변경 후 현재 factor-free runner로 2025 production differential smoke를 다시 실행했다.

```powershell
uv run --group qlib python qlib-integration-codex\compare_signed_peer_momentum.py `
  --start-date 2025-01-02 `
  --end-date 2025-12-31
```

242거래일의 Qlib active PnL은 `120,867,255 KRW`, production 대비 차이는 `6.1502 bp`,
일별 PnL correlation은 `0.9999734`, sign agreement는 `100%`였다. Qlib attribution
reconciliation error는 `0.0`이며 기존 selection semantics `2.3492 bp`와 integer execution
`3.8010 bp` 분해가 그대로 재현됐다.

### 실제 peer momentum long-short smoke

```powershell
uv run --group qlib python `
  qlib-integration-codex\run_signed_peer_momentum.py `
  --start-date 2025-01-02 `
  --end-date 2025-12-31
```

2025-01-02~2025-12-30의 242거래일을 실행했다. 전일 peer return, 5일 linear decay,
absolute top 5%, long/short side exposure와 per-name cap을 사용했다. Production closed loop와
같이 당일 기준가에 체결하고 당일 종가로 평가하며, commission/tax/slippage/borrow fee는 모두
0으로 두었다. Composite initial cash는 `3,000,000,000 KRW`, active booksize와 return
denominator는 `1,000,000,000 KRW`다. 결과는 다음과 같다.

- active money PnL: `120,867,255 KRW`
- active return denominator 대비 total return: `12.0867255%`
- long money PnL: `127,558,400 KRW`
- short money PnL: `-6,691,145 KRW`
- long + short - active PnL reconciliation error: `0.0`
- execution cost: `0.0`
- average long/short exposure: `20.036990% / 10.598494%`
- Qlib underlying order/fill: `3,776 / 3,776`
- `composite_nav - baseline_nav - active_nav` max absolute error: `0.0`
- minimum composite quantity: `0.0`

최초 smoke의 `-9.420717%`는 production timing과 다른 close 체결·next-close 평가로 signal을
한 거래일 더 지연했고, buy/sell cost와 sell tax `108,120,915.9965 KRW`도 포함했다. 따라서
peer momentum 자체의 sign을 판단하는 비교로 사용하지 않는다. Cost 0과 production timing으로
재실행한 위 결과가 현재 migration evidence다.

처음 `retained` 정책으로 실행했을 때 회전하는 short name의 baseline이 누적되어 funding reserve가
fail-fast했다. 미래 ticker를 seed하거나 capacity를 clip하지 않고 해결하기 위해 실제 run은
`inventory_retention=active_short_only`를 명시했다. 이 policy는 현재 bar fill 뒤 active signed
quantity와 NAV를 바꾸지 않는 excess baseline만 release한다. Default는 `retained`다.
추가로 composite cash와 active booksize를 분리해 universe/short-name 교체 시 필요한 순간
capitalization reserve를 active exposure 축소 없이 제공한다. Reserve는 사전에 정한 현금이며
future ticker나 future target을 읽어 seed한 inventory가 아니다.

### Production closed-loop differential twin

다음 command로 production `src`의 `SignalDecayPeerMomentumSignalStrategy` 및
`ClosedLoopBacktestEngine`과 matched-capitalization Qlib run을 동일 조건에서 비교했다.

```powershell
uv run --group qlib python `
  qlib-integration-codex\compare_signed_peer_momentum.py `
  --start-date 2025-01-02 `
  --end-date 2025-12-31
```

비교 조건은 cost 0, 전일 signal, 5일 linear decay, absolute top 5%, long/short
0.25/0.25, per-name 0.05 cap, 당일 기준가 체결·당일 종가 평가, active booksize 10억
원이다. Production factory의 원래 default budget은 1.0/1.0이므로, 엔진 parity만 보기 위해
비교 run에서 동일 scaler를 production strategy weight policy에 명시적으로 주입했다.

- Production total PnL: `121,482,278.7744 KRW`
  - long: `127,899,840.3513 KRW`
  - short: `-6,417,561.5769 KRW`
- Qlib total PnL: `120,867,255 KRW`
  - long: `127,558,400 KRW`
  - short: `-6,691,145 KRW`
- Production - Qlib: `615,023.7744 KRW`, active booksize 대비 `6.1502 bp`
- 일별 total PnL correlation: `0.9999734`
- 일별 PnL sign agreement: `100%`
- 최대 누적 PnL 괴리: `617,014.8734 KRW`

Qlib intended weight를 production fractional-share ledger로 실행하는 중간 counterfactual을
추가해 전체 차이를 분해했다.

- Signal selection/universe mask 순서 차이: `234,920.9325 KRW` (`2.3492 bp`)
- Qlib integer-share/lot execution 차이: `380,102.8419 KRW` (`3.8010 bp`)
- 합계: `615,023.7744 KRW` (`6.1502 bp`)

Applied/intended weight는 242일 중 3일만 달랐다. Production은 lagged signal universe에서
selection/scaling한 뒤 당일 execution universe 밖 target을 제거하고, Qlib signed alpha는
observation/trade universe intersection을 selection 전에 적용한다. 2025-11-26과 2025-12-11에는
실제 universe exit가 있었고, 2025-11-25에는 cutoff membership이 달라졌다. 최대 weight 차이는
`2.5040%p`다. 나머지 차이는 production fractional quantity와 Qlib integer quantity의
rounding이다. 두 account의 PnL reconciliation error는 각각 `3.3e-7 KRW` 이하와 `0.0`이다.

따라서 이 기간/조건에서는 어느 한 backtest가 경제적으로 틀렸다는 증거가 없다. Total과 leg
PnL, 일별 방향, 경로가 모두 일치하며 `6.15 bp` 차이는 관측 가능한 execution/selection contract
차이로 설명된다. Exact parity contract를 원하면 current-universe mask를 rank 전에 적용할지
execution에서만 적용할지 하나로 통일하고, fractional-vs-integer quantity tolerance를 별도로
정의해야 한다.

## 5. Frozen report twin migration evidence

`report_twin/`과 `run_report_twin.py`를 추가해 `report-draft-3.md` 및
`research/report/build_report_assets.py`가 사용하는 전체 계산 계약을 독립 재현했다. 구현 범위는 18개 member,
6개 기존 market allocation, 최종 market equal-weight+5일 decay, 3개 family, 5개 rationale
allocation, bottom 10% negative screen, 연 3% alpha volatility risk sizing, 0.1 production scale,
execution-universe ETF residual과 stock/ETF 비용이다.

2026-07-23 실제 frozen input 2,095거래일(2018-01-02~2026-07-20) 실행 결과:

- 6개 market allocation/combined intent 최대 오차: `2.6645352591003757e-15`
- 3개 family weight 최대 오차: `1.3877787807814457e-17`
- 5개 rationale candidate weight 최대 오차: `0.0`
- 5개 physical daily gross/net active return, cost, turnover 최대 오차:
  `1.4623718902484484e-15`
- 최종 frozen annualized net active return: `-0.09523645486265453%`
- 실제 Qlib annualized net active return: `-0.09516519966912242%`
- Qlib과 analytical twin의 최대 일별 net active 차이: `6.474236323515681e-06`
- 1,000억 원 Qlib account 최종 NAV: `314,069,974,088.7108 KRW`
- Qlib total money PnL: `214,069,974,088.71082 KRW`
- Qlib execution cost: `1,393,371,756.4208617 KRW`

Analytical twin은 report와 같은 fractional vectorized contract이므로 frozen output과 machine
precision에서 일치한다. Qlib 결과는 같은 target을 integer share, cash-funded cost와 Account
mark-to-market lifecycle에 통과시킨 결과다. 전체 증거는
`outputs/report_twin/migration-proof.json`, PnL은
`outputs/report_twin/figures/report-twin-pnl.png`에 생성된다.

검증 command:

```powershell
uv run --group qlib python qlib-integration-codex\run_report_twin.py

$env:KWAM_RUN_QLIB_CONTRACTS='1'
uv run --group qlib python -m pytest `
  qlib-integration-codex\tests\test_goal_17_report_twin.py -q
```

Goal 17 acceptance는 `2 passed`다. 첫 test는 전체 frozen ensemble과 daily PnL exact parity를,
둘째 test는 stock/ETF `target_weight`가 실제 Qlib backend와 instrument contract를 통과하는지
검증한다.

## 6. 열린 구현 선택

다음은 architecture를 바꾸지 않는 범위에서 config/implementation으로 결정한다.

- Baseline reserve sizing과 replenishment policy
- Default safety multiplier
- Same-bar readiness와 next-bar conservative variant
- Universe exit 뒤 baseline retained/retired policy
- Delisting closeout price와 unavailable-price policy
- Borrow availability/fee data가 생겼을 때 `shortable` capacity에 결합하는 방식

어떤 선택도 미래 ticker membership이나 future target을 읽어 capacity를 seed해서는 안 된다.

## 8. 검증 및 기록 규칙

- Qlib opt-in suite는 실제 installed pyqlib object를 통과해야 한다.
- 작은 deterministic fixture부터 검증하고 full smoke는 contract가 green인 뒤 수행한다.
- 구현이 완료되면 이 문서에 실제 command, test count와 남은 제약을 기록한다.
- 구현 완료 전에는 README나 public API에서 matched-capitalization support를 완료 기능으로 표시하지
  않는다.

Canonical requirement는 `prd.md`, layer/data flow는 `architecture.md`, 상세 state decision은
`weight-strategy-twin/qlib-shorting.md`를 따른다.
