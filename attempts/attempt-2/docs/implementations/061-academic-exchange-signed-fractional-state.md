# AcademicExchange signed fractional state

## Why this change exists

qlibx could materialize signed factor signals and construct `hypothetical_signed` portfolio
artifacts, but it stopped before package-owned execution and state accounting. The academic factor
showcase therefore used local turnover and return arithmetic and could not demonstrate Fill,
position, NAV, recovery, or execution lineage. Reusing `KrxExchange` or `Account` would have weakened
their deliberate long-only, cash, lot, and exact-cost invariants.

## User and system outcome

`QlibxProject.run_academic(spec)` now executes exact schema-v2 signed portfolio artifacts in a
separate hypothetical venue. Stock, ETF, tracking-only Index, and synthetic-unit-price Factor
listings use exact PIT prices at the close of the session after the portfolio evaluation session.
The result exposes fractional signed fills, financing balance, position cost basis, realized and
unrealized PnL, NAV, gross/net exposure, turnover, immutable lineage, and restartable checkpoints.

## Responsibility and flow changes

- `qlibx.academic` owns the fixed `academic.zero-friction.signed-fractional.v1` profile, explicit
  listing/price semantics, signed state models, fill model, and pure full-fill rebalance arithmetic.
- `AcademicExecutionFlow` loads only exact `portfolio_construction_result:v2` parents with the
  `hypothetical_signed` profile, maps each evaluation to the next session close, queries the
  registered observation at that exact time, and preflights the full rebalance before matching.
- Target quantity is `weight * pre-trade marked NAV / execution price`. Instruments absent from a
  new target are closed to zero. No cash, lot, liquidity, or gross-budget clipping is introduced.
- Each candidate execution is published before its checkpoint, but in-memory authority advances
  only after the checkpoint is durable. An interrupted run recomputes and idempotently reuses an
  orphan execution artifact; resume validates the full config and parent prefix before continuing.
- Academic artifacts depend on their exact parent portfolio, dataset registration/fingerprint,
  frozen config, and prior checkpoint. Production `KrxExchange`, `Fill`, and `Account` are unchanged.

## Alternatives and trade-offs

- Extending production `Account` was rejected because negative positions and reusable short
  proceeds would silently create margin and collateral semantics that the package does not own.
- Reusing production `Fill` was rejected because it has no unambiguous hypothetical marker.
- Same-session-close execution was rejected because close-derived factor signals could see and
  trade the same price. The fixed v1 convention is the next session close.
- Non-zero or configurable academic costs were deferred. Every friction term is serialized as
  exact zero and any non-zero profile input fails rather than being ignored.
- Factor returns are not compounded into a hidden price series. Factor execution requires an
  explicitly registered positive `SyntheticUnitPrice` observation.

## Validation

- `uv run pytest tests\test_academic_exchange.py tests\test_public_academic.py -q` — 10 passed.
- `uv run pytest -q` — 276 passed in 117.91 seconds.
- `uv run ruff check src\qlibx\academic.py src\qlibx\flow\academic.py src\qlibx\flow\__init__.py src\qlibx\project.py src\qlibx\__init__.py tests\test_academic_exchange.py tests\test_public_academic.py` — passed.
- `uv run python -c "import qlibx; print(qlibx.AcademicRunSpec.__name__)"` — printed
  `AcademicRunSpec`.
- `uv build` — built `qlibx-0.1.0.tar.gz` and `qlibx-0.1.0-py3-none-any.whl`.
- `uv run --no-project --isolated --with .\dist\qlibx-0.1.0-py3-none-any.whl ...` — loaded
  qlibx 0.1.0 and the new public API from an isolated `site-packages` path.
- `uv run python showcases\show_003_academic_exchange_factor_execution\run.py` — reproduced 23
  real-DW rebalances and 276 hypothetical stock fills. Negative positions were observed, every
  cost term was zero, and the independent oracle maximum deltas were `9.32e-10` NAV, `5.33e-15`
  quantity, and `2.23e-16` turnover.
- Repeated showcase runs were byte-identical: `summary.json`
  `BA60B35CAA858870AD753D578D7F43F78A38CA42E55DE72DA989D8DC7B5A4956` and `report.html`
  `A133F068674F003B6B35DAC899A15717F7B3ABF6FBD450C789820255944E13F9`.
- Static HTML inspection found one SVG, one table, 24 rows, and a complete closing document. The
  in-app browser blocked local `file://` navigation by policy, so interactive visual inspection was
  not available in this run.

## Remaining limitations and follow-up

This capability is research-only. It does not model or prove borrow availability, locate,
collateral, margin, recalls, short-proceeds encumbrance, borrow fees, dividends, corporate actions,
FX, financing rates, liquidity, partial fills, or production settlement. Production KRX and Account
remain long-only. A future non-zero cost profile and executable real short require separate product
decisions and independent acceptance evidence.
