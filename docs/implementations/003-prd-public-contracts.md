# PRD public contracts and complete journeys

## Intent

Implement the canonical `docs/qlibx-prd.md` human and AI-agent journeys through installed public
surfaces. Project data, config, research, generated state and local extensions remain user-owned;
qlibx and Qlib site-packages remain immutable during project work.

## Outcome

### Agent onboarding and data

- Public `docs`, `schema`, `examples`, `errors`, `project`, `data`, `qlib`, `agent`, and `extension`
  commands expose versioned task guidance without private imports.
- Managed instruction planning preserves user content, is idempotent, detects stale plans, and can
  target both `AGENTS.md` and `CLAUDE.md`.
- Generated skills contain project/data, research, stored ensemble, signed execution, artifact
  reporting, error recovery, and exact extension-contract examples.
- Structured `QlibxError` values carry code, message, action and context. `qlibx errors <code>`
  provides recovery guidance and marks ambiguities that require user confirmation.
- Discovery and inspection are bounded and read-only. Registration requires explicit
  `available_at`, `ticker`, opaque information, key, frequency and timezone mappings.
- Registration writes only canonical Parquet below the configured generated-data root. Logical
  YAML defaults its time filter to `available_at`, and the standard matrix example explicitly uses
  `available_at` as its index. A separate event/observation field is optional and used only when
  the user explicitly maps and selects it.

### Strategy, alpha and Qlib feedback

- Strategy instances have stable identity, declared data/output contracts, bounded decision
  context, deterministic seed/state and named intermediate records.
- Child research can only narrow parent data/availability and receives a detached account view.
- `run_strategy_execution` calls the StrategyAgent inside Qlib's decision loop and supplies only
  previously confirmed Qlib feedback. Combined Strategy/Qlib checkpoints reproduce uninterrupted
  orders, fills, positions, account and decisions.
- Signed alpha transforms are deterministic and versioned. Exposure artifacts record method,
  data, window, coverage and missingness, and never label demeaning as exact neutrality.
- Fixed budgets rescale to the declared side budget; flexible budgets preserve unused exposure.

### Research, ensemble and portfolio

- `ResearchCatalog` stores frozen inputs, proposals, successful/failed/invalid publications,
  incomplete attempts, immutable artifacts, append-only events and a rebuildable DuckDB view.
- Context queries include prior records, searched ranges, active proposals, nearest neighbors,
  dataset snapshots, comparison sets and gaps. Semantic, empirical and incremental orthogonality
  are separate results.
- Three independent processes can publish to one project on one branch. Duplicate retries cache,
  conflicting identity fails, incomplete publication stays hidden/recoverable, and stale decisions
  fail compare-and-swap.
- Stored ensembles load verified member weights without importing or rerunning strategies, preserve
  member flexible exposure, net only the same ticker and record contribution/similarity/lineage.
- Enhanced-index construction distinguishes physical stock/ETF/cash from optional point-in-time
  look-through exposure, and reports cost, binding constraints, solver status, hard infeasibility,
  soft relaxation and unimplemented active exposure.

### Signed execution, artifacts and extensions

- Matched capitalization is explicitly a compatibility mode for Qlib's long-only account, not
  native short borrowing. Endowment is NAV-neutral, the active short is an actual Qlib SELL,
  partial fills advance only by dealt quantity, and every checkpoint reconciles `A = C - B`.
- Blocked cover keeps the necessary baseline; release occurs only after an actual cover fill.
  Reserve shortage and negative composite target fail explicitly. Active PnL uses active booksize.
- Project-local signal transforms, exposure analyzers and report renderers are loaded only below the
  configured extension root and validated against versioned public contracts.
- Complete JSON/Parquet artifacts can be exported/imported with hash verification. Named strategy
  intermediates are physical files. Stored reporting does not load the original strategy or create
  a canonical research record, and analysis/composition/rendering remain separate.

## Design choices and trade-offs

- `available_at` is the visibility boundary. If a user retains a separate event/observation field,
  that optional field is descriptive or analytical and never substitutes for availability.
- qlibx does not understand or modify correction factors or financial-field semantics. It copies
  only user-confirmed opaque information fields.
- Project extensions are trusted code; contract validation is not a security sandbox.
- Qlib remains the required execution dependency at exactly `pyqlib==0.9.7`.
- The matched-capitalization reserve is visible and finite; the implementation does not claim
  borrow, locate, recall, margin, forced buy-in or borrow-fee behavior.

## Exact validation

- Source checkout: `uv run pytest -q` -> 77 passed; Ruff check and format check passed.
- Installed final wheel, Python 3.10.20 -> 77 passed.
- Installed final wheel, Python 3.11.15 -> 77 passed.
- Installed final wheel, Python 3.12.13 -> 77 passed.
- All three environments imported qlibx from their `site-packages`, version 0.1.0, with
  `pyqlib==0.9.7`.
- Wheel and sdist each contain 56 files and exclude project config/data, tests, references,
  experiments, showcases, plans, local extensions and research state.
- Wheel SHA-256:
  `dd5853a55b877f4aeabedee1deaf45b2d255698a68bc62dc63a5288aa0bfb6cf`.
- Sdist SHA-256:
  `1f2e46a596a76537cfd392148f7787f04d2ecb702436b5bb9a164efc1297b393`.
- Rebuilding the wheel from the sdist produced the identical wheel SHA-256.
- `experiments/exp_003_event_time_qlib_pnl` proves 949 actual SELL orders/fills, 542 signed-short
  rows, zero negative composite quantity, no look-ahead and active PnL 732,258,791.25.
- `showcases/show_001_real_user_agent_journey`, run from the isolated Python 3.12 wheel, proves the
  complete research/ensemble/portfolio/Qlib/artifact/report/extension journey with 1,020 SELL
  orders, 2,201 positive fills, 1,180 short rows and active PnL 28,248,960.27.

Protected upstream hashes and Git boundaries are checked again in the completion audit; no package
release, stage, commit, push or publication is part of this task.
