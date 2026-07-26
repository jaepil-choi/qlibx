# Qlib production migration: application workflow goals

## 1. 이 문서가 정하는 것

이 문서는 `scripts/run_backtest.py`의 구현 구조를 이식하지 않고, 그 script를 사용해서 얻고
싶었던 **외부 결과**를 새 `qlib-integration-codex` codebase의 acceptance contract로 바꾼다.

현재 `kwam_qlib_backend` Goal 0~10은 Qlib execution, accounting, optimizer, artifact와 research
capability를 폭넓게 검증한다. 그러나 test-only `BackendHarness`가 중심이어서 실제 research
사용자가 호출할 production application API가 없었다. Goal 11~15는 이 공백을 구현했다.

아래 테스트는 실제 `qlib_extended` public package를 직접 호출하며, 구현 완료 여부를 외부
result로 검증한다.

## 2. 비판적 평가

### 보존할 결과

- config의 logical dataset 선언만으로 strategy input을 읽는다.
- 한 번에 여러 strategy를 선택해 alpha와 Qlib backtest를 실행한다.
- `max_workers > 1`이면 서로 독립적인 strategy run이 실제로 겹쳐서 실행된다.
- alpha 계산과 backtest 실행은 각각 immutable run ID를 받고, parent lineage와 provenance가
  run store에 남는다.
- reporting은 backtest run ID로 저장 결과를 읽으며 strategy를 다시 실행하지 않는다.
- ensemble은 member alpha run ID의 저장 alpha를 읽으며 member strategy를 다시 실행하지 않는다.
- report는 browseable HTML을 기본으로 만들고 figure는 요청할 때만 만든다.
- CLI는 `run`, `report`, `ensemble` use case만 얇게 노출한다.

### 이식하지 않을 구조

- `scripts/run_backtest.py`의 import/re-export 목록과 compatibility surface
- data loading, universe, strategy construction, backtest, cache, reporting을 한 함수에서 조립하는
  방식
- `BackendHarness`를 production facade로 승격하는 방식
- report마다 임의의 cache directory layout을 알고 직접 parquet를 찾는 방식
- ensemble이 member strategy instance나 source config를 다시 만드는 방식

기존 script가 dirty한 이유는 단순히 길어서가 아니다. 한 entry point가 여러 use case의
composition root인 동시에 compatibility module, diagnostics host, cache writer 역할까지 한다.
그 구조를 복사하면 파일을 나누더라도 같은 결합이 다시 생긴다.

## 3. 구현한 public interface

사용자에게 필요한 첫 production surface는 네 use-case 함수와 공통 configuration exception이다.

```python
from qlib_extended import (
    ConfigurationError,
    build_ensemble,
    create_report,
    open_run_catalog,
    run_strategy_batch,
)
```

예상 사용 흐름은 다음과 같다.

```python
batch = run_strategy_batch(
    "configs/research.yaml",
    strategy_ids=("peer_momentum", "value"),
    max_workers=2,
)

catalog = open_run_catalog("outputs/runs.duckdb")
alpha = catalog.load_alpha(batch.runs[0].alpha_run_id)

report = create_report(
    "outputs/runs.duckdb",
    backtest_run_ids=tuple(run.backtest_run_id for run in batch.runs),
    output_dir="outputs/reports/comparison",
)

ensemble = build_ensemble(
    "outputs/runs.duckdb",
    strategy_id="ensemble.equal_weight",
    members={run.alpha_run_id: 0.5 for run in batch.runs},
)
```

함수 이름은 use case를 말할 뿐 구현 class topology를 드러내지 않는다. Qlib executor, DuckDB,
Parquet, process pool은 adapter 세부사항이며 반환 object에는 `alpha_run_id`,
`backtest_run_id`, `status`, 생성된 file과 조회 결과처럼 관찰 가능한 값만 둔다.

Alpha와 backtest identity는 합치지 않는다. 같은 alpha를 다른 cost, portfolio constraint,
execution policy로 반복 평가하는 것은 정상적인 research use case다. `backtest_run_id`가
`alpha_run_id`를 parent로 참조하면 alpha를 다시 계산하지 않고도 이 비교가 가능하다.

## 4. Goal과 acceptance result

### Goal 11 — Configured strategy batch

**목표:** config path와 strategy ID만으로 logical dataset을 읽고 여러 alpha + Qlib backtest
run을 만든다.

**왜 필요한가:** 호출자가 DataFrame을 미리 만들거나 loader/strategy constructor를 조립해야
하면 config-driven system이 아니다. 반대로 config schema가 내부 Qlib class를 그대로 노출하면
configuration이 dependency injection container로 비대해진다.

**통과 결과:**

- 같은 input data에서 fixture strategy의 예상 alpha matrix가 정확히 저장된다.
- 선택한 strategy마다 서로 다른 non-empty `alpha_run_id`, `backtest_run_id`와 `complete`
  status가 반환된다.
- `backtest_run_id`가 `alpha_run_id`를 parent로 참조하고 Qlib 실행 결과인 `account_daily`를
  다시 조회할 수 있다.
- 존재하지 않는 logical dataset은 strategy 호출 전에 `ConfigurationError`로 실패한다.

대응 테스트: `tests/test_goal_11_configured_strategy_batch.py`

### Goal 12 — Real parallel execution and durable run catalog

**목표:** 독립 strategy를 설정한 worker 수 안에서 동시에 실행하고, 서로 다른 effective
definition을 immutable run으로 보존한다.

**왜 필요한가:** 단순히 `workers` 인자를 받는 것은 병렬 실행의 증거가 아니다. 또한 memory에만
남는 result object는 report와 ensemble 재사용 요구를 만족하지 못한다.

**통과 결과:**

- 두 fixture strategy가 서로의 start marker를 기다리는 barrier test를 통과한다. thread인지
  process인지는 고정하지 않지만 실제 overlap은 요구한다.
- 같은 effective config로 strategy를 두 번 실행하면 같은 deterministic alpha/backtest run ID를
  반환하고 catalog row와 strategy invocation을 중복 생성하지 않는다.
- run record에는 dataset과 strategy fingerprint가 남는다.

대응 테스트: `tests/test_goal_12_parallel_and_catalog.py`

### Goal 13 — Cached reporting

**목표:** reporting을 strategy execution과 완전히 분리하고 저장된 Qlib account result를
요약한다.

**왜 필요한가:** report 생성이 strategy code나 원 data loader를 다시 호출하면 속도 문제뿐 아니라
나중에 code/config가 바뀌어 같은 run ID의 report가 달라지는 reproducibility 문제가 생긴다.

**통과 결과:**

- strategy 실행을 강제로 금지한 상태에서도 backtest run ID만으로 report가 만들어진다.
- 기본 호출은 run 결과를 포함한 `.html`만 생성하며 summary file이나 PNG를 만들지 않는다.
- `include_png=True`인 호출만 실제 `.png`를 추가 생성한다.
- strategy invocation count가 증가하지 않는다.

대응 테스트: `tests/test_goal_13_cached_reporting.py`

### Goal 14 — Cached ensemble lineage

**목표:** 저장된 member alpha를 조합해 새로운 ensemble alpha run을 publish한다.

**왜 필요한가:** ensemble research의 반복 단위는 member 재실행이 아니라 저장 alpha의 선택,
alignment, weight 변경이어야 한다. 그래야 여러 조합을 빠르게 비교할 수 있다.

**통과 결과:**

- member strategy 실행을 금지한 상태에서도 weighted alpha가 수치적으로 정확하다.
- ensemble은 별도 alpha run ID를 받고 다시 `load_alpha()` 할 수 있다. 이 ensemble alpha를
  parent로 참조하는 별도 backtest run도 만들고 Qlib `account_daily`를 저장한다.
- ensemble record가 정확한 parent run ID를 보존한다.

대응 테스트: `tests/test_goal_14_cached_ensemble.py`

### Goal 15 — Thin public CLI

**목표:** Python API와 동일한 세 use case를 module CLI에서 제공한다.

**왜 필요한가:** 실제 research workflow에는 script/terminal entry point가 필요하지만 CLI가 다시
orchestrator 전체를 소유하면 기존 `run_backtest.py` 구조가 반복된다.

**통과 결과:** `python -m qlib_extended --help`가 성공하고 `run`, `report`, `ensemble` command를
노출한다. CLI 구현은 인자 parsing 후 위 public use case를 호출하는 composition adapter여야 한다.

대응 테스트: `tests/test_goal_15_public_cli.py`

## 5. 저장 경계 제안

첫 구현은 **DuckDB catalog + immutable Parquet artifact**로 확정한다.

- DuckDB: run, status, fingerprint, artifact location, parent lineage를 빠르게 filter/join한다.
- Parquet: date × ticker alpha와 account/position처럼 큰 columnar result를 압축 저장한다.
- `run_id`: alpha 계산 또는 backtest 실행의 content-addressed semantic identity다. 같은 effective
  definition은 같은 ID를 재사용하지만 다른 definition에 ID를 재할당하지 않는다.
- lineage: backtest run은 하나의 alpha run을, ensemble alpha run은 member alpha run들을
  parent로 참조한다.
- content hash: artifact integrity와 동일 content 판별에 사용하며 run identity와 분리한다.

모든 matrix를 DuckDB row table로 강제하면 큰 alpha panel의 write amplification이 커진다. 반대로
Parquet directory만 두면 run filter, lineage query, status transaction을 각 reader가 다시
구현하게 된다. 두 역할을 분리하는 편이 단순하다.

테스트는 DuckDB table 이름이나 directory layout을 고정하지 않는다. `open_run_catalog()`로 새
connection을 열어 result가 다시 조회되는지만 검사한다. 따라서 이후 storage adapter 교체가
필요해도 application API는 유지할 수 있다.

## 6. Clean architecture 구현 guardrail

테스트 통과만으로 clean architecture가 보장되지는 않는다. 구현 review에는 다음 기준을 함께
적용한다.

```text
CLI / Python facade
        ↓
application use cases
        ↓
domain ports: strategy, dataset reader, run repository, reporter
        ↑
adapters: config, Qlib, DuckDB/Parquet, matplotlib/html
```

- application use case는 Qlib, DuckDB, pandas file I/O를 직접 import하지 않는다.
- strategy worker는 alpha 계산과 result 반환만 담당하며 catalog publish를 직접 하지 않는다.
- parent process가 run status와 atomic publish를 책임진다.
- report와 ensemble은 `run repository` port만 사용한다.
- CLI에는 dataframe 계산, Qlib loop, SQL, figure code를 두지 않는다.
- compatibility re-export는 새 package에 만들지 않는다.
- 새로운 abstraction은 두 번째 실제 adapter/use case가 생길 때만 추가한다.

구현은 `runner.py`(batch orchestration), `planning.py`(identity), `ensemble.py`, `store.py`,
`execution.py`, `reporting.py`, `cli.py`로 변경 이유를 분리했다. Architecture test는 public
surface, core의 external import 금지, CLI dependency, source/test 격리와 file size budget을
검사한다.

## 7. Review에서 결정할 항목

Review 결정은 다음과 같이 확정했다.

1. distribution 이름은 `qlib-extended`, Python import 이름은 `qlib_extended`다. Python module
   identifier에는 hyphen을 사용할 수 없기 때문이다.
2. 첫 저장 adapter는 DuckDB catalog + immutable Parquet artifact다.
3. report는 HTML을 기본으로 생성한다. 별도 summary artifact는 만들지 않고 PNG는
   `include_png=True`일 때만 생성한다.
4. effective config, input content, strategy code가 같으면 deterministic alpha/backtest run ID를
   만들고 기존 complete run을 재사용한다. 이 중 하나가 바뀌면 stale reuse를 막기 위해 새 ID가
   생긴다.
5. alpha와 backtest identity를 분리한다.
6. Long-short target architecture는 matched capitalization이다. Qlib composite
   `Account`/`Position`과 baseline sidecar를 source state로 두고 signed view는 read-only
   projection으로 저장한다. Synthetic mirror ticker와 독립 signed authoritative ledger는 쓰지
   않는다. 이 항목은 implementation pending이며 기존 Goal 0~15 완료와 구분한다.
