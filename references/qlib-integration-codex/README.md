# Qlib Integration Codex

이 디렉토리는 Qlib closed-loop migration의 유일한 실험 작업 공간이다. Production `src/`
package에는 Qlib runtime이나 peer-return bridge를 추가하지 않는다.

Peer momentum migration은 두 경계를 분리한다.

- `qlib_extended/`: `qlib-extended` production application facade, deterministic run store,
  cached reporting/ensemble
- `peer_momentum_runtime/`: 독립 peer-return 계산과 `BaseStrategy` twin, physical ETF 실행
- `kwam_qlib_backend/`: Goal 0~10 capability/optimizer/artifact regression harness
- `weight-strategy-twin/`: 이전 `WeightStrategyBase` 비교 실험 보관 경계

`peer_momentum_runtime/peer_return.py`는 production peer momentum 코드를 import하지 않는다.
동일한 경제적 정의를 별도 구현해 twin 결과로 검증하는 것이 목적이다.

`kwam_qlib_backend/`는 KWAM decision과 pyqlib 0.9.7 execution/accounting을 연결한다.
`tests/`는 test-only `BackendHarness` adapter를 통해 observable capability만 검사한다.
Adapter는 production API, four-view pipeline, child book, Qlib Account topology를 고정하지
않는다.

실제 실행 flow는 다음과 같다.

```text
lookahead-safe subscription / strategy state / actual feedback
-> online physical target
-> integer quantity와 lot-size sizing
-> Qlib Order
-> ScenarioExchange.deal_order
-> Qlib Account / Position
-> backend-neutral fill, cash, NAV, position feedback
-> 다음 decision
```

`ScenarioExchange`는 pandas quote를 Qlib에 공급하고 `KrxExecutionPolicy`로
stock/ETF 비용·세금과 instrument별 lot을 명시한다. Qlib의 tradability, volume, position,
  cash, lot clipping hook을 계측해 각 stage quantity와 `reason_code`/`blocked_by`를
  fill artifact에 남긴다. Suspension과 upper/lower price limit은 일반 buyable/sellable block과
  구분한다. 현재 구현의 production short는 policy에서 비활성이다. Target architecture는 아래
  matched-capitalization boundary를 따른다. Cost 차감, position update,
mark-to-market은 Qlib implementation을 통과한다. Corporate-action normalization은 upstream
ETL 책임이다. Integration은 정규화된 physical unit의 `execution_price`와 optional
`valuation_price`만 소비하며 raw event나 adjustment factor로 quantity를 변환하지 않는다.
Legacy config의 `position_unit_factor`는 compatibility를 위해 optional로 읽지만 all-ones만
허용하고 변동 값은 upstream contract 위반으로 fail-fast한다. `valuation_price`를 생략하면
execution price로 평가한다. Production closed loop처럼 당일 기준가에 체결하고 당일 종가로
평가할 때는 두 matrix를 명시적으로 분리한다.

`ParquetArtifactStore` schema v2는 immutable `run_id`를 실행 identity로 사용하고
strategy/date/provenance와 content hash를 분리한다. 같은 strategy/date의 서로 다른 run은
공존하며, 같은 `run_id`는 provenance와 content가 모두 같을 때만 idempotent하다.
Temporary directory에서 완성한 run을 atomic publish한다. Reporting과 ensemble input은
complete manifest와 file hash를
검증한 Parquet만 읽으며 strategy나 backend를 재실행하지 않는다. Signed attribution도 stored
position/account/price와 member alpha lineage만 읽는다. Checkpoint는 Qlib position의 quantity,
price, cash, NAV, sequence counter뿐 아니라 baseline cash/quantity, 직전 baseline/active NAV와
capitalization event sequence를 저장하고 남은 bar만 새 Qlib Account로 이어 실행한다.

Research path는 execution path와 분리하되 artifact lineage로 연결한다.

```text
immutable dataset snapshots
-> reusable signal/mask/active_intent node DAG
-> physical_target execution root
-> CVXPY intent-tracking optimizer
-> Qlib execution/accounting

pandas feature/label/universe
-> Qlib StaticDataLoader
-> DataHandlerLP train-only processor fit
-> DatasetH purged/embargoed segments
-> Qlib Model.fit/predict
-> portable prediction signal artifact
```

`ResearchGraph`는 `signal`, `mask`, `active_intent`, `physical_target` node의 type contract,
cycle 금지, 재귀적 definition hash와 strategy별 단일 physical execution root를 검증한다.
`ResearchGraphExecutor`는 root ancestor를 topological order로 실행하고 동일 node definition과
transitive snapshot set의 output을 hash-verified Parquet에서 재사용한다.
`ParquetResearchCatalog`는 logical dataset, immutable snapshot, node/edge, 전이적 strategy
dependency와 `run_dataset_inputs`를 별도 identity로 보존한다. ML input snapshot fingerprint는
실제 pandas content hash와 대조한다.

Acceptance adapter의 기본 module은
`kwam_qlib_backend.acceptance_adapter`이며 `build_harness()`를 제공해야 한다. 다른 구현을
연결할 때는 `KWAM_QLIB_ACCEPTANCE_ADAPTER`로 module을 지정한다. 이 adapter interface는
production public API가 아니다.

상세 구조 진단과 goal별 성공 기준은 다음 문서가 기준이다.

- `prd.md`: Qlib migration 전용 요구사항과 acceptance criteria
- `architecture.md`: current/target layer, state와 data flow
- `implementation.md`: 현재 구현 상태와 matched-capitalization 구현 순서
- `weight-strategy-twin/migration-readiness-and-contract-test-plan.md`
- `critical-review.md`: 현재 구현의 책임 경계와 Goal 0~10/graph 완료 계약
- `application-workflow-goals.md`: production facade와 구현 완료된 Goal 11~15 계약

## Contract test 실행

일반 repository test run을 방해하지 않도록 기본적으로 skip된다.

```powershell
uv run --group qlib python -m pytest qlib-integration-codex\tests -q
```

전체 capability contract를 실제로 실행하려면 명시적으로 활성화한다.

```powershell
$env:KWAM_RUN_QLIB_CONTRACTS='1'
uv run --group qlib python -m pytest qlib-integration-codex\tests -q
```

Goal 하나만 실행할 수도 있다.

```powershell
$env:KWAM_RUN_QLIB_CONTRACTS='1'
uv run --group qlib python -m pytest qlib-integration-codex\tests\test_goal_01_feedback_loop.py -q
```

현재 Goal 0~16, structured execution/KRX policy, research DAG와 dataset/run lineage가
구현되어 있다. 2026-07-23 검증 기준 opt-in suite는 native twin과 `qlib-extended`
application workflow test를 포함한다. 이는 기존 capability migration contract의 완료를 뜻하며,
기존 production closed-loop code의 즉시 삭제를 뜻하지 않는다. 기본 실행의 skip은 일반 repository test가 Qlib
integration 비용을 암묵적으로 부담하지 않게 하는 정책이다.

## Matched-capitalization long-short

승인된 다음 target architecture는 signed intent와 Qlib composite execution 사이에
matched-capitalization adapter를 둔다.

```text
signed active intent
-> causal baseline inventory activation with matching cash debit
-> non-negative Qlib composite position
-> Qlib fill/account feedback
-> signed read-only observation = composite - baseline
```

Qlib `Account`/`Position`은 composite execution의 source of truth로 유지한다. Baseline sidecar는
capitalization state만 소유하며 별도 signed ledger를 authoritative state로 두지 않는다. Future
ticker는 full matrix axis에 있을 수 있지만 point-in-time observed/tradable mask가 열리기 전에는
inventory와 position을 갖지 않는다. 상세 결정과 폐기한 대안은
[`weight-strategy-twin/qlib-shorting.md`](weight-strategy-twin/qlib-shorting.md)에 있다.

Goal 16 public contract와 실제 Qlib composite execution이 구현되어 있다. 다음 command는 로컬
preprocessed KOSPI200 data로 causal peer momentum signed alpha를 실행하고 active PnL figure와
stored-run report를 생성한다.

```powershell
uv run --group qlib python qlib-integration-codex\run_signed_peer_momentum.py `
  --start-date 2025-01-02 `
  --end-date 2025-12-31
```

Output은 `qlib-integration-codex/outputs/signed_peer_momentum/`에 생성된다. Runner는 회전하는 short
name의 funding reserve를 미래 정보 없이 회수하기 위해 명시적
`inventory_retention=active_short_only`를 사용한다. 일반 public config의 default는 `retained`다.
이 smoke의 composite initial cash는 30억 원, active booksize와 active return denominator는
10억 원이다. 남은 20억 원은 causal baseline funding reserve이며 alpha exposure가 아니다.
Signal은 전일까지의 정보만 사용하고, 당일 기준가 체결·당일 종가 평가를 적용한다. Commission,
tax, slippage와 borrow fee는 모두 0이며, 결과 figure는 cumulative long PnL, short PnL과 total
PnL을 별도로 표시한다.

동일한 cost-zero/base-to-close 조건에서 production `src`의
`SignalDecayPeerMomentumSignalStrategy`와 `ClosedLoopBacktestEngine`을 Qlib signed run과
일별로 비교하려면 다음 command를 사용한다.

```powershell
uv run --group qlib python qlib-integration-codex\compare_signed_peer_momentum.py `
  --start-date 2025-01-02 `
  --end-date 2025-12-31
```

Production factory default budget은 1.0/1.0이므로 이 differential run은 엔진 비교를 위해
Qlib smoke와 같은 long/short 0.25/0.25, per-name 0.05 cap을 production weight policy에
명시적으로 주입한다. 결과는
`qlib-integration-codex/outputs/signed_peer_momentum_twin/`에 저장한다.

## qlib-extended application workflow

Distribution 이름은 `qlib-extended`, Python import 이름은 `qlib_extended`다. Public facade는
`run_strategy_batch`, `open_run_catalog`, `create_report`, `build_ensemble`,
`build_signed_attribution`, `build_enhanced_index_attribution` use case를 노출한다.
Same effective config는 normalized config,
input Parquet content, strategy code가 모두
같다는 뜻이며 이 경우 deterministic alpha/backtest run ID와 complete artifact를 재사용한다.
Alpha ID와 backtest ID는 분리되어 execution config만 바뀌면 alpha를 다시 실행하지 않는다.

```powershell
uv run --group qlib python qlib-integration-codex\showcase\run_workflow.py
```

Showcase는 2개 strategy process 병렬 실행, persistent cache hit, stored-alpha ensemble, 실제
Qlib account, DuckDB catalog, 30개 Parquet artifact, HTML-only 기본 report와 optional PNG를
검증한다. 결과는 `outputs/workflow_showcase/evidence.json`에 남는다.

`backtest.target_semantics=enhanced_index`는 stored signed alpha와 benchmark weight를 Goal 9
optimizer에 전달한다. Config의 look-through, physical bounds, transaction cost, cash bounds와
solver를 사용하며, 매 bar의 current holding/cash는 requested target이 아니라 직전 Qlib realized
state다. Solver tolerance 안의 budget 오차는 raw target과 normalization delta를 artifact에 남긴
뒤 재검증한다. `build_enhanced_index_attribution`은 stored member weights, signed intent,
optimizer constituent/physical target, Qlib positions만 읽어 member → constituent → physical
lineage를 재생성한다.

## Frozen report 전체 twin 실행

`report_twin/`은 `docs/report/enhanced-index-2/report-assets/manifest.json`이 가리키는 frozen
artifact를 사용해 report의 18개 alpha와 모든 ensemble을 production 계산 함수 import 없이
독립 재현한다. 검증 범위는 7개 market variant, 3개 family, 5개 causal rationale candidate,
negative screen, embedded risk sizing, 0.1 scale의 ETF residual enhanced-index PnL이다.

```powershell
uv run --group qlib python qlib-integration-codex\run_report_twin.py
```

기본 output은 `qlib-integration-codex/outputs/report_twin/`이다.

- `migration-proof.json`: 단계별 최대 parity 오차, lineage run ID와 실제 Qlib NAV/PnL
- `runs.duckdb`, `artifacts/`: 18 member → 3 family → 5 candidate → final Qlib backtest lineage
- `tables/`: member, market method, family, rationale PnL과 summary CSV
- `figures/report-twin-pnl.png`: 누적 PnL 4-panel

2026-07-23 frozen 2,095일 실행은 overall `PASS`, 전체 최대 오차 `2.66e-15`, 5개 최종
candidate weight 오차 `0.0`이었다. 최종 inverse-volatility ensemble의 비용 후 연환산 active
return은 frozen `-0.095236%`, 실제 Qlib `-0.095165%`다. 1,000억 원 Qlib account의 최종
NAV/PnL은 각각 `3,140.70억 원` / `2,140.70억 원`이다. NAV/PnL에는 K200 benchmark total
return이 포함되므로 active 성과는 별도의 annualized net active return으로 판단한다.

## Native peer momentum twin 실행

```powershell
$env:PYTHONPATH='src;qlib-integration-codex'
uv run --group qlib python qlib-integration-codex\run_native_peer_momentum.py `
  --start-date 2025-01-02 `
  --end-date 2025-12-30
```

Twin config와 output은 각각 `qlib-integration-codex/configs/peer_momentum.yaml`,
`qlib-integration-codex/outputs/native_peer_momentum/` 아래에 둔다.

Stock의 신규 매수는 당일 production universe와 suspension 조건을 그대로 적용한다.
다만 production holdings ledger가 universe 제외 보유종목을 마지막 유효가격에서 0 target으로
청산하는 것과 parity를 맞추기 위해, 유효가격이 남은 suspension row에서는 buy를 막고
기존 position의 sell만 허용한다. 이 sell-only exit는 일반 10% volume participation cap의
예외이며, Qlib `OrderGenWInteract`의 방향 미지정 tradability 조회도 한쪽 방향이 열려 있으면
order 생성을 허용한다. 양방향 제한이나 가격 누락은 계속 non-tradable이다.
