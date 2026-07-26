# Qlib Migration PRD

## 1. 목적과 경계

이 문서는 `qlib-integration-codex/` 안에서 수행하는 Qlib migration의 요구사항만 정의한다.
Production `src/kwam_enhanced_index`의 현재 동작과 계약은 root `docs/vibe/` 문서가 소유하며,
Qlib migration을 위해 그 문서나 production source를 변경하지 않는다.

Migration의 목적은 KWAM이 만든 signed alpha, 여러 alpha의 ensemble과 enhanced-index portfolio
intent를 Qlib의 order, fill, `Account`, `Position`과 mark-to-market lifecycle에 연결하는 것이다.
Qlib source와 `.venv` package는 수정하지 않고 `qlib-extended` adapter로 확장한다.

최종 목표는 개별 alpha strategy를 Qlib에 port하는 데서 끝나지 않는다. Config로 logical
dataset과 strategy를 선택해 alpha를 만들고, immutable artifact로 저장하고, ensemble과
enhanced-index optimizer를 거쳐 Qlib에서 체결·회계한 뒤, 저장된 결과만으로 report와 후속
연구를 재생성할 수 있는 causal research/execution application을 제공해야 한다.

```text
logical dataset config
-> causal alpha research
-> immutable alpha run
-> ensemble / enhanced-index optimizer
-> Qlib order / fill / Account / Position
-> immutable backtest run
-> cached report / ensemble / audit
```

Existing production closed-loop engine은 migration 검증을 위한 differential reference다. 이 PRD의
완료가 곧바로 production engine 삭제를 뜻하지 않는다.

Corporate action normalization은 이 framework의 책임이 아니다. 액면분할·병합, 배당, 권리락,
adjusted price와 delisting을 포함한 market data/universe 정규화는 별도의 upstream ETL pipeline이
담당한다. Qlib integration framework는 ETL이 제공한 point-in-time execution price, mark price,
universe와 tradability를 일반 market input contract로 소비하고 schema와 causality만 검증한다.
Raw corporate action event나 adjustment factor를 해석하거나 backtest 안에서 price/quantity를
재조정하지 않는다.

## 2. 제품 원칙

### 2.1 Realized state

- Qlib dealt amount로 realized holding을 갱신한다. Order request나 별도 ledger로 대체하지 않는다.
- Cash, physical position, transaction cost와 composite NAV는 Qlib `Account`/`Position`에서
  읽는다.
- Partial fill, suspension, price limit, volume, cash와 lot 제약을 우회하지 않는다.
- Qlib state와 stored observation이 tolerance 밖에서 어긋나면 silent reconciliation하지 않고
  fail-fast한다.

### 2.2 Causality

- Decision bar보다 먼저 알려진 observation과 completed execution feedback만 사용한다.
- Dataset별 lookback, availability와 observation time을 독립적으로 관리한다.
- Research evaluation, what-if와 model training은 실제 Qlib account를 변경하지 않는다.
- 미래 universe membership, future target과 전체 기간 통계를 과거 decision, inventory
  activation이나 capacity sizing에 사용하지 않는다.

### 2.3 Responsibility separation

- Alpha artifact는 원 종목 ticker level의 signal 또는 signed active intent를 표현한다.
- Ensemble은 저장된 alpha를 조합하며 member strategy를 다시 실행하지 않는다.
- Enhanced-index optimizer는 intent를 physical target과 cash target으로 변환한다.
- Execution은 physical target을 Qlib order/fill/account lifecycle에 연결한다.
- Backtest config만 바뀌면 compatible alpha run을 재사용하고 backtest run만 새로 만든다.

### 2.4 Reproducibility

- Effective dataset, strategy, graph, optimizer, backtest와 capitalization policy를 fingerprint한다.
- 동일한 effective input은 deterministic run ID와 verified cache를 재사용한다.
- 같은 run ID에 다른 content나 provenance를 덮어쓰지 않는다.
- Stored artifact가 손상되거나 manifest hash와 다르면 complete run으로 읽지 않는다.

## 3. 핵심 결정

Qlib long-short 실행은 **matched capitalization**으로 구현한다.

```text
signed active intent
-> causal baseline inventory activation
-> non-negative composite target
-> Qlib Exchange / Account / Position
-> signed observation and audit
```

Ticker `i`, bar `t`의 상태는 다음 관계를 항상 만족해야 한다.

```text
A[i,t] = active signed quantity
B[i,t] = baseline inventory quantity, B >= 0
C[i,t] = Qlib composite quantity, C >= 0

C[i,t] = B[i,t] + A[i,t]
A[i,t] = C[i,t] - B[i,t]
```

Qlib composite `Account`/`Position`은 order, fill, cash, quantity와 NAV의 source of truth다.
Baseline sidecar는 matched capitalization state만 소유한다. Signed view는 둘의 차이로 계산하는
read-only audit projection이며 독립 execution ledger가 아니다.

## 4. Functional Requirements

### 4.1 Feedback, data subscription과 strategy state

- Execution 결과와 portfolio return은 해당 bar가 완료된 뒤 다음 decision부터만 보인다.
- Consecutive-loss stop 같은 rule은 확인된 feedback 수가 threshold에 도달한 다음 bar부터 target을
  변경한다.
- Partial fill 이후 다음 decision과 optimizer current holding은 requested target이 아니라 실제 Qlib
  holding, cash와 NAV를 사용한다.
- Strategy memory는 한 run 안에서는 유지되고 별도 run을 시작할 때 초기화된다.
- 각 logical dataset은 독립적인 lookback과 availability rule을 가진다.
- Decision에 전달되는 모든 row의 `max_observation_date`는 `decision_date`보다 앞서야 한다.
- Quarterly, daily 등 frequency가 다른 dataset을 하나의 공통 lookback으로 암묵적으로 자르지 않는다.
- 필요한 logical dataset이 없으면 strategy를 호출하기 전에 `ConfigurationError`로 실패한다.

### 4.2 Dynamic universe와 lifecycle

- Universe entry, exit, liquidation block, delayed liquidation과 re-entry를 order/fill/state artifact에서
  관측할 수 있어야 한다.
- Re-entry 때 strategy memory와 baseline inventory를 reset, retain 또는 release하는 정책을
  명시해야 하며 default를 추측하지 않는다.
- 전체 backtest 기간의 ticker 집합은 matrix column axis로 사용할 수 있다.
- 미래 ticker의 axis 존재는 economic inventory, eligibility나 tradability를 뜻하지 않는다.
- 각 bar는 point-in-time `observed`, `tradable`, `strategy_universe`, `shortable`,
  `inventory_ready` 상태를 구분할 수 있어야 한다.
- `observed=False`인 ticker는 signal, rank, normalization, optimizer, target, baseline inventory와
  composite position에서 모두 제외한다.

### 4.3 Physical quantity, cash와 KRX execution

- Weight target은 booksize, execution price와 lot size를 사용해 physical integer quantity로
  변환한다.
- Lot rounding으로 투자하지 못한 금액은 cash로 남고 NAV reconciliation에 포함된다.
- Stock과 ETF는 서로 다른 commission/tax policy를 적용할 수 있어야 한다.
- Suspension, upper/lower price limit, volume participation, current position, available cash와 lot
  rounding을 방향별로 적용한다.
- Order/fill artifact에는 raw target, rounded target, requested/dealt amount와 각 clipping stage
  이후 quantity를 저장한다.
- Block 또는 partial fill은 `reason_code`, `blocked_by`, asset class, execution policy와
  effective cost rate를 보존한다.
- 알 수 없는 physical instrument를 target이 반환하면 무시하지 않고 실패한다.

### 4.4 Enhanced-index optimizer

- Optimizer 입력은 desired active exposure, benchmark weight, current physical holding, cash,
  look-through matrix, tradability, bounds, transaction cost, risk와 named constraint를 명시한다.
- Physical target은 look-through matrix를 정확히 한 번 적용해 constituent exposure로 변환한다.
- Cash와 physical target weight의 합, hard bounds와 named hard constraint를 solve 이후 독립적으로
  검증한다.
- Non-tradable physical position은 실제 current holding에 freeze한다.
- Turnover와 transaction cost는 requested target이 아니라 현재 realized physical holding을
  기준으로 계산한다.
- Soft constraint는 이름, slack과 penalty를 diagnostic에 남긴다.
- Infeasible problem을 자동 완화하지 않으며 `infeasible`과 `solver_error`를 구분한다.
- Input axis mismatch는 alignment를 추측하지 않고 실패한다.

### 4.5 Research graph와 ML research

- Alpha, mask, transform, ensemble, active intent와 physical target을 typed DAG node로 표현할 수
  있어야 한다.
- Graph는 cycle, parent input type mismatch와 physical execution root가 아닌 strategy root를
  거부한다.
- Node definition hash는 operator config와 모든 transitive parent definition을 포함하며 mapping
  order에는 독립적이어야 한다.
- Strategy run은 모든 transitive logical dataset을 immutable snapshot ID에 bind한다.
- Node cache key는 해당 node의 transitive dataset snapshot과 definition에 의해서만 결정한다.
- Verified node cache는 nested ensemble을 포함한 동일 node를 다시 실행하지 않으며 손상된 cache
  artifact는 거부한다.
- ML pipeline은 실제 Qlib `DatasetH`, `DataHandlerLP`와 `Model` surface를 사용한다.
- Processor는 effective train segment에만 fit하고 label horizon purge와 validation/test embargo를
  적용한다.
- Prediction은 `(datetime, instrument)` axis를 유지하고 deterministic, portable signal artifact로
  저장한다.
- Model manifest는 model ID, seed, effective segment, metric, dataset snapshot과 code version
  lineage를 보존한다.
- ML fit/predict와 historical candidate evaluation은 실제 Qlib account에 order, cash 또는 position
  side effect를 만들지 않는다.

### 4.6 Run catalog와 artifact store

- Alpha와 backtest는 서로 다른 run ID와 run kind를 가지며 backtest run은 사용한 alpha run을
  parent로 참조한다.
- Artifact store는 최소한 strategy registry, strategy runs, signals, portfolio targets, orders,
  fills, positions, account daily, research evaluations와 artifact manifest를 keyed Parquet table로
  저장한다.
- Signed execution은 signed positions, capitalization event, baseline account와 active account
  artifact를 추가로 저장한다.
- Table은 정의된 primary key가 중복되지 않아야 하고 quantity column은 physical contract에 맞는
  dtype을 유지해야 한다.
- Result hash는 order/fill이 같더라도 signal 또는 intended target이 다르면 달라야 한다.
- 동일 content의 재기록은 idempotent해야 하지만 동일 run ID의 content나 provenance 변경은
  거부한다.
- `exact_run`, `portable_signal`, `portable_target` 같은 reuse scope를 저장하고 reader가 이를
  임의로 승격하지 못하게 한다.
- Report와 ensemble input은 stored artifact만으로 로드하며 strategy invocation count를 증가시키지
  않는다.

### 4.6.1 Systematic alpha research pool

- Research data와 alpha definition은 각각 `configs/data/`, `configs/alphas/` YAML을 source of
  truth로 사용한다.
- Research loader는 production `src/`를 import하지 않지만 source/logical dataset 분리,
  DuckDB Parquet query, table/matrix contract와 explicit alignment methodology를 동일하게
  구현한다.
- Research alpha pool은 `runs`, `metrics`, `members` 세 core table만 가진 rebuildable result
  index다.
- Parallel worker는 shared DuckDB에 직접 쓰지 않고 immutable manifest를 publish하며 coordinator가
  transaction으로 등록한다.
- 신규 trusted alpha의 fixed interval은 63거래일을 넘지 않는다.
- Exact filing vintage가 없는 financial alpha는 `financial_shadow`, 기존 252일 또는
  full-sample-informed alpha는 `legacy`로 분리한다.
- Calendar cohort는 같은 family와 exact `order_calendar_key` member만 crossing한다.
- Physical 비용은 trusted family target delta를 ticker별로 netting한 후 한 번만 적용한다.
- 동결 이후 도착 데이터만 true forward OOS로 표시한다.

### 4.7 Configured application workflow

- Config path와 strategy ID 목록만으로 logical dataset loading, alpha generation과 Qlib backtest를
  실행할 수 있어야 한다.
- 선택한 각 strategy는 status, alpha run ID와 backtest run ID를 반환한다.
- `max_workers > 1`이면 독립 strategy 실행이 실제로 overlap되어야 한다.
- 같은 effective config와 input snapshot을 다시 실행하면 strategy를 재호출하지 않고 같은 alpha와
  backtest run ID를 반환한다.
- Backtest-only config 변경은 기존 alpha run을 재사용하고 새로운 backtest run ID만 생성한다.
- Run catalog를 process 종료 후 다시 열어도 run record, parent lineage, fingerprint와 stored
  table을 조회할 수 있어야 한다.
- Public Python API는 최소한 `run_strategy_batch`, `create_report`, `build_ensemble`,
  `open_run_catalog` use case를 제공한다.
- `python -m qlib_extended --help`는 성공하고 `run`, `report`, `ensemble` command를
  노출한다.
- Public facade와 CLI는 backend implementation, storage layout과 Qlib internal constructor를
  호출자에게 노출하거나 orchestration logic을 중복 소유하지 않는다.

### 4.8 Cached reporting과 ensemble

- Report는 backtest run ID만으로 저장된 account/artifact를 읽어 생성한다.
- Report 생성 중 strategy code와 원 data loader를 다시 호출하지 않는다.
- 기본 report는 self-contained HTML을 생성하고 `include_png=True`일 때만 PNG를 추가 생성한다.
- Ensemble은 member alpha run ID와 weight를 입력으로 받아 ticker axis를 정렬하고 새로운 reusable
  alpha run을 publish한다.
- Ensemble alpha는 member run ID를 parent lineage로, ensemble backtest는 ensemble alpha를
  parent로 보존한다.
- 동일 member와 weight로 다시 요청하면 verified ensemble/backtest cache를 재사용한다.

### 4.9 Signed intent와 composition

- Strategy와 optimizer는 원 종목 기준 signed active intent를 생성해야 한다.
- 여러 alpha member는 원 종목 ticker level에서 결합하고 crossing/netting한 뒤 execution layer에
  전달해야 한다.
- Ensemble과 enhanced-index 변환 전후의 signed intent lineage를 보존해야 한다.
- Synthetic execution instrument가 signal, rank, normalization, optimizer universe에 들어가서는
  안 된다.

### 4.10 Signed universe와 causality

- 전체 backtest 기간의 ticker 집합은 matrix column axis로 사용할 수 있다.
- 미래 ticker의 axis 존재는 경제적 inventory나 eligibility를 의미하지 않는다.
- 각 bar는 point-in-time `observed`, `tradable`, `strategy_universe`, `shortable`,
  `inventory_ready` mask를 가져야 한다.
- `observed=False`인 ticker는 signal, rank, normalization, optimizer, target, baseline inventory와
  composite position에서 모두 제외해야 한다.
- 미래 K200 편입, 미래 alpha target이나 전체 기간 최대 short exposure를 activation 또는 buffer
  sizing에 사용해서는 안 된다.

### 4.11 Matched capitalization

- Ticker가 point-in-time activation 조건을 처음 만족하면 execution-time price `P`로 baseline과
  composite에 같은 inventory `delta_B`와 cash debit `-delta_B*P`를 atomic하게 반영해야 한다.
- Activation은 composite NAV와 active projection을 바꾸지 않아야 한다.
- Baseline activation은 시장 주문이 아니므로 market volume과 transaction cost를 소비하지 않는다.
- Activation/top-up 이후 active order만 원래 경제적 BUY/SELL 방향으로 Qlib execution을 통과해야
  한다.
- 신규 ticker의 first-tradable bar short는 baseline activation 후 underlying `SELL`로 표현한다.
- Baseline funding reserve가 부족하면 우회하지 않고 fail-fast해야 한다.

### 4.12 Execution과 realized state

- Qlib의 tradability, suspension, 방향별 price limit, volume clipping, lot rounding과 cost 계산을
  유지해야 한다.
- Partial fill 이후 realized signed quantity는 requested target이 아니라 Qlib dealt amount로
  갱신해야 한다.
- Baseline activation/top-up과 active order의 순서를 artifact에서 재현할 수 있어야 한다.
- ETL이 제공한 universe exit/re-entry와 market input을 적용한 뒤에도 `A = C - B`를 유지해야
  한다.

### 4.13 Observation, artifacts와 reporting

- Intended signed target, baseline before/after, capitalization event, submitted order, Qlib requested/
  dealt amount, composite closing position과 reconstructed signed position을 저장해야 한다.
- 모든 artifact는 observation time과 point-in-time mask provenance를 보존해야 한다.
- Qlib raw account/report artifact는 reconciliation을 위해 저장한다.
- Qlib standard return은 거대한 composite NAV를 denominator로 사용하므로 active 성과의 canonical
  report로 사용하지 않는다.
- Active report는 stored composite/baseline artifact에서 active money PnL과 명시적인 active
  notional denominator로 다시 계산해야 한다.

### 4.14 Frozen report twin과 migration proof

- `docs/report/enhanced-index-2/report-assets/manifest.json`과 manifest가 가리키는 frozen
  artifact를 report migration의 source of truth로 사용한다.
- Twin은 production report builder나 production ensemble 함수를 import하지 않고 18개 member,
  6개 market allocation과 최종 동일가중+5일 decay, 3개 family, 5개 causal rationale allocation,
  negative screen, embedded risk multiplier를 독립 구현한다.
- Member → family → rationale candidate → ETF residual physical portfolio lineage를 immutable run
  catalog에 보존한다.
- Frozen weight, allocation, gross/net active return, turnover와 trade cost의 최대 절대 오차는
  `1e-10` 이하여야 한다.
- 최종 physical stock/ETF target은 `target_semantics=target_weight`로 실제 Qlib order/fill/account
  lifecycle을 통과해야 한다. Asset class와 lot size는 execution contract에 명시한다.
- Report 문서의 기간, alpha multiplier와 최종 비용 후 active return이 manifest와 일치하지 않으면
  migration proof는 실패한다.

## 5. Required Invariants

각 bar에서 다음을 fail-fast로 검사한다.

```text
B >= 0
C >= 0
A == C - B
composite_nav == baseline_nav + active_nav

if observed_mask is false:
    intended_target == 0
    A == 0
    B == 0
    C == 0
```

Qlib state와 audit projection이 tolerance 밖에서 어긋나면 report를 계속 생성하거나 silent
reconciliation하지 않는다.

추가로 다음 invariant를 검사한다.

- `nav == cash + marked_position_value` within scale-aware tolerance
- Physical position과 order/fill quantity는 configured lot/unit contract를 만족
- Stored result hash와 artifact content hash 일치
- Run input은 필요한 모든 logical dataset snapshot을 빠짐없이 포함
- Resume 전 checkpoint cash, position와 NAV가 서로 reconcile됨

## 6. 채택하지 않는 방식

- Synthetic inverse/mirror ticker를 BUY해 short를 근사하는 방식
- 상장 전 ticker에 양수 Qlib inventory 또는 0-price position을 미리 넣는 방식
- Long leg와 short leg를 서로 다른 Qlib account로 실행하고 사후 PnL만 합치는 방식
- `Exchange.deal_order(position=None)`와 별도 signed ledger를 authoritative state로 쓰는 방식
- Qlib source fork 또는 `.venv` source 직접 수정
- Qlib standard report를 active strategy performance로 직접 사용하는 방식
- Report나 ensemble을 만들기 위해 member strategy와 원 data loading을 다시 실행하는 방식
- Infeasible optimizer constraint, missing schema나 corrupt artifact를 silent fallback으로 우회하는 방식
- Raw corporate action event나 adjustment factor를 backtest framework가 해석하거나 adjusted
  price와 universe lifecycle을 자체 생성하는 방식

## 7. Goal별 Acceptance Criteria

| Goal | Acceptance boundary |
|---|---|
| 0 | Capability adapter가 production API shape을 고정하지 않고 test observation port를 만족한다. |
| 1 | Feedback은 다음 decision에만 반영되고 partial fill/account state는 Qlib 결과와 일치한다. |
| 2 | Dataset별 lookback과 causality가 유지되고 strategy memory lifecycle이 run 단위로 격리된다. |
| 3 | Universe entry/exit, blocked liquidation, delayed exit와 re-entry policy가 관측 가능하다. |
| 4 | Integer/lot quantity, rounding cash와 stock/ETF cost contract를 만족한다. |
| 5 | Keyed immutable Parquet run DB, manifest/hash/provenance/reuse scope와 corruption detection을 제공한다. |
| 6 | Cached long-short member alpha로 member 재실행 없이 enhanced-index Qlib run을 만든다. |
| 7 | Adaptive what-if/model evaluation이 causal하고 actual account에 side effect를 만들지 않는다. |
| 8 | Checkpoint resume와 uninterrupted run의 observable result와 hash가 동일하다. |
| 9 | Look-through optimizer가 hard/soft constraint, frozen holding, turnover와 solver status를 정확히 처리한다. |
| 10 | Qlib ML pipeline이 train-only fit, purge/embargo, portable prediction과 dataset/model lineage를 만족한다. |
| 11 | Config와 strategy ID만으로 logical data, alpha run과 backtest run을 생성한다. |
| 12 | Independent strategy를 실제 병렬 실행하고 deterministic run/cache catalog를 유지한다. |
| 13 | Stored backtest run만으로 strategy 재실행 없이 report를 생성한다. |
| 14 | Stored member alpha로 reusable ensemble alpha/backtest와 parent lineage를 만든다. |
| 15 | Thin public CLI가 `run`, `report`, `ensemble` use case를 제공한다. |
| 16 | Matched capitalization으로 causal signed execution, dealt-amount realization, active reporting과 stored-alpha netting을 만족한다. |
| 17 | Frozen report의 18 member, 7 market variant, 3 family, 5 rationale candidate와 final Qlib physical execution을 독립 twin으로 재현한다. |
| 18 | `qlib-integration-codex` 내부의 stored report-data run만으로 12 figure/9 table을 병렬 생성하고 path boundary, hash cache와 lineage를 검증한다. |

Goal 번호 외에 structured execution/KRX diagnostics, optimizer axis validation, research DAG lineage,
native peer-momentum twin 독립성 및 clean architecture boundary test도 전체 acceptance suite에
포함한다.

### 7.1 Matched-capitalization acceptance

- Full future ticker axis를 사용해도 first-observed 이전 ticker state가 모두 0이다.
- First-tradable activation의 composite NAV와 active projection 변화가 0이다.
- Activation 후 short entry가 underlying `SELL` 방향으로 실행된다.
- Short increase, cover와 long/flat/short cross-zero가 정확하다.
- Partial fill, suspension, limit과 volume clipping 이후 signed realized quantity가 Qlib fill과 맞는다.
- Baseline capacity/funding 부족은 명시적 reason으로 실패한다.
- ETL이 제공한 execution/mark price와 universe exit/re-entry input에서 모든 invariant가
  유지된다.
- Existing production signed holdings ledger와 quantity, cash, turnover와 PnL differential parity를
  작은 deterministic fixture에서 통과한다.
- Stored artifact만으로 signed audit와 active report를 재생성할 수 있다.

## 8. 현재 상태와 완료 evidence

현재 workspace 기준 Goal 0~16, structured execution/KRX policy, research DAG, dataset/run lineage,
`qlib-extended` application workflow와 matched-capitalization signed execution이 구현되어 있다.
Goal 0~15와 native peer-momentum twin은 long-only regression baseline이며, signed execution은
migration runtime인 `qlib-extended`에 추가됐다.

2026-07-23 opt-in contract suite 검증 command와 결과는 다음과 같다.

```powershell
$env:KWAM_RUN_QLIB_CONTRACTS='1'
uv run --group qlib python -m pytest qlib-integration-codex\tests -q
```

```text
93 passed
```

기존 `position_unit_factor` corporate-action quantity transformation test는 upstream-normalized
execution/mark price와 physical unit contract로 교체됐다. Public config의 legacy factor는
optional이며 all-ones만 허용한다. 변동 factor는 upstream ETL 책임을 침범하므로 fail-fast한다.

Goal 16 automated acceptance는 future ticker dormancy, first-observed same-bar underlying `SELL`,
volume partial fill, short increase/cover/cross-zero, reserve 부족과 top-up/release, blocked exit와
delayed liquidation, retained/released re-entry, matched checkpoint/resume parity를 직접 검증한다.
또한 production signed holdings ledger와 quantity/cash/absolute turnover/PnL을 deterministic
fixture에서 대조하고, stored member/ensemble lineage만으로 signed attribution과 active report를
재생성한다.

Enhanced-index acceptance는 stored signed member alpha를 weighted ensemble로 netting한 뒤
benchmark+active intent를 Goal 9 optimizer에 전달하고 Qlib physical target으로 실행한다.
첫 bar의 requested 55%/45% target이 integer rounding으로 realized 54%/45%와 1% cash가 된 뒤,
다음 optimizer input이 이 realized state를 사용하는지 직접 검증한다.
`build_enhanced_index_attribution`은 stored parent weight, signed member intent, benchmark,
look-through, optimizer constituent/physical artifact와 Qlib position만 읽어
member → constituent → physical lineage를 재생성한다. Strategy invocation count는 attribution과
report 전후 동일하며, look-through가 physical target에 정확히 한 번 적용됐는지 reader가 다시
검증한다. Corporate action 처리 완료 여부는 이 framework가 아니라 upstream ETL pipeline의
별도 acceptance contract로 판단한다.

Upstream-normalized contract 전환 뒤 factor dataset 없이 2025 production differential smoke도
재실행했다. 242거래일의 Qlib active PnL은 `120,867,255 KRW`, production 대비 차이는
`6.1502 bp`, 일별 PnL correlation은 `0.9999734`, sign agreement는 `100%`, Qlib
reconciliation error는 `0.0`이었다.

세부 상태 전이와 테스트 계약은
[`weight-strategy-twin/qlib-shorting.md`](weight-strategy-twin/qlib-shorting.md), 구현 및 검증
기록은 [`implementation.md`](implementation.md), Goal 11~15 public workflow 계약은
[`application-workflow-goals.md`](application-workflow-goals.md)를 따른다.
