# 037 Expose public samples and constraint monitoring

## Intent

Three bundled samples existed, but the CLI could select only the default. Independent actual-state
constraint monitoring also existed internally, but an installed project had no public route from a
committed daily checkpoint to the mutable `Account` required by `MonitoringFlow`. Several concrete
daily configuration types were missing from the top-level package surface, so the advertised public
spec could not be assembled from `qlibx` imports alone.

## Observable outcome

`qlibx project sample <root> --sample-id <id>` exposes all three version-matched bundled sample IDs
as argparse choices while retaining `basic-real-dw-journey-v1` as the default.

`ConstraintMonitoringSpec` freezes a simulation checkpoint artifact, evaluation instant, policy and
invocation identity. `QlibxProject.monitor_constraints()` restores the committed Account checkpoint
and publishes the existing independent no-trade monitoring result. Repeating the same spec returns
the same result and artifact identity. A held position marked before the selected instant returns
`ACCOUNT_VALUATION_STALE`; a structurally invalid Account checkpoint returns
`MONITORING_ACCOUNT_CHECKPOINT_INVALID` instead of leaking `ValueError`.

Installed users can import `ConstraintMonitoringSpec`, `CostRule`, `EtfInstrument`,
`KrxExchangeConfig`, `Side`, and `StockInstrument` from top-level `qlibx` and construct a
`DailySimulationSpec` without subpackage imports.

## Responsibilities and flow

- `ConstraintMonitoringSpec` owns the frozen evaluation instant and policy fingerprint. The same
  instant drives Account mark freshness and the benchmark PIT cutoff.
- `QlibxProject.monitor_constraints` loads `SIMULATION_CHECKPOINT_CONTRACT`, restores
  `SimulationCheckpoint.account_checkpoint` through `Account.from_checkpoint`, and delegates to
  `MonitoringFlow` with `BacktestClock(spec.evaluation_time)`.
- `QlibxProject._checkpoint_failure` translates Account checkpoint integrity failures to a bounded
  non-committed operation error.
- `SampleMaterializer` stores one directory per sample ID, exposes deterministic `sample_ids()`, and
  no longer shadows a class-level `sample_id` or duplicates source/destination tuples.
- The CLI obtains choices from `QlibxProject.available_sample_ids()` and passes the selected ID to
  the facade.
- README, PRD `GAP-MONITOR-001`, and Architecture §17 describe the same installed-project boundary.

## Alternatives and trade-offs

Reading wall time in the facade was rejected because it would make artifact identity depend on when
the method was called and could select a different PIT benchmark row. `evaluation_time` therefore
lives on the public frozen spec and is not added to the internal monitoring request.

Reconstructing Account state from the lightweight state projection was rejected because it omits
the journal and idempotency authority. The only supported route is
`SimulationCheckpoint → AccountCheckpoint → Account.from_checkpoint`.

Constraint monitoring is not injected into every daily run. A fourth bundled sample and a new
monitoring step in `constraint-workflow-v1` were also rejected as scope expansion without separate
closure evidence.

## Validation

```
.venv/Scripts/python.exe -m pytest tests/test_contracts.py tests/test_sample.py tests/test_public_constraints.py -q -p no:cacheprovider --basetemp=.agent/runs/pytest-c6-final-019fd96d
-> 22 passed in 28.06s

.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp=.agent/runs/pytest-c6-full-019fd96d
-> 171 passed in 330.34s

.venv/Scripts/python.exe -m ruff check .
-> All checks passed!

git diff --check
-> clean

$env:UV_CACHE_DIR='D:\chljeffreyz\DevProjects\qlibx\.uv-cache'; uv build
-> Successfully built dist/qlibx-0.1.0.tar.gz and dist/qlibx-0.1.0-py3-none-any.whl
```

The default uv cache under the non-ASCII managed-Windows profile failed with `WinError 5`; the build
used the repository-local task-scoped cache. The first sandboxed build with that cache could not
reach PyPI, so only the dependency-fetching retry used approved network access.

Artifact inspection found the intended package modules, three bundled samples and bundled qlibx
skill, with no tests, experiments, showcases, caches, local configuration or credentials. Metadata
reported `Name: qlibx`, `Version: 0.1.0`, `Requires-Python: >=3.11, <3.13`, the declared runtime
dependencies, and console entry point `qlibx = qlibx:main`.

| artifact | bytes | SHA-256 |
|---|---:|---|
| `qlibx-0.1.0-py3-none-any.whl` | 125998 | `24B70FB5F2F934C90900E8FCCA0D7C7367F24DEF253CF731FDF1E8D4B16D7783` |
| `qlibx-0.1.0.tar.gz` | 87847 | `078C62CD149D6F04455DFA376ADEE7E602247F3B28A02AEBECCF4543188FFE9D` |

Fresh wheel compatibility evidence:

```yaml
- python: "3.11.15"
  declared_by_project: true
  upstream_metadata: supported
  resolution: passed
  install: passed
  import: passed
  smoke: passed
  tests: not_run
  build: not_run
  artifact_install: passed
  commands:
    - uv pip install --python .agent/runs/c6-wheel-py311/Scripts/python.exe dist/qlibx-0.1.0-py3-none-any.whl
    - fresh site-packages top-level DailySimulationSpec and ConstraintMonitoringSpec smoke
  artifacts:
    - dist/qlibx-0.1.0-py3-none-any.whl
  failure_class: null
  risk: full source suite was not rerun under 3.11 during C6
- python: "3.12.13"
  declared_by_project: true
  upstream_metadata: supported
  resolution: passed
  install: passed
  import: passed
  smoke: passed
  tests: passed
  build: passed
  artifact_install: passed
  commands:
    - uv pip install --python .agent/runs/c6-wheel-py312/Scripts/python.exe dist/qlibx-0.1.0-py3-none-any.whl
    - installed qlibx project sample --sample-id daily-closed-loop-v1 --apply
    - installed daily_closed_loop/run.py
  artifacts:
    - dist/qlibx-0.1.0-py3-none-any.whl
    - dist/qlibx-0.1.0.tar.gz
  failure_class: null
  risk: null
```

The installed daily sample completed with two decisions, two execution callbacks, a final A000660
position, and the expected checkpoint run ID `sample-daily-closed-loop`.

## Remaining limitations

- The Python 3.11 fresh-wheel import/spec smoke passed, but the full source test suite was not rerun
  under 3.11 in this C6 milestone; this is not a release certification.
- Public monitoring supports the current no-short and benchmark-relative single-name-cap policy
  only. Sector, turnover and liquidity monitoring remain future work.
- Monitoring remains explicit and independent; daily flow does not invoke it automatically.
- The bundled set remains exactly three samples.
- No artifact was published or pushed.
