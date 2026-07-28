# Verify peer-momentum parity between integration-codex and qlibx

Status: complete

## Purpose

Produce reproducible evidence showing whether the peer-momentum strategy built in
`references/qlib-integration-codex/` and the same strategy expressed through qlibx produce the
same signed weights and the same Qlib execution result.

## Scope and non-goals

- Work only on the current branch.
- Keep all new code and outputs under `experiments/exp_004_peer_momentum_parity/`.
- Treat `references/qlib-integration-codex/` and all upstream/user data as read-only.
- Do not change `src/`, `tests/`, package dependencies, or canonical data registration.
- Do not compare the unrelated five-day own-return momentum used by experiment 003.
- Do not promote experiment code to production as part of this task.

## Acceptance criteria

- Load the exact matrices and stored alpha from the completed integration-codex run.
- Independently calculate leave-one-out equal-weight peer momentum through qlibx
  `StrategyDefinition`, `DecisionContext`, `DecisionResult`, and `run_decision`.
- Compare every date/ticker weight, including maximum absolute error, nonzero selection agreement,
  first divergence, and exposure totals.
- Execute both the stored reference weights and the qlibx-generated weights through the public
  qlibx signed execution API with the original run's cash, liquidity, short-cap, inventory, and
  zero-cost settings.
- Compare orders, fills, signed positions, daily accounts, and final active PnL; clearly distinguish
  exact equality from numerical or semantic divergence.
- Record the runnable command, evidence, limitations, and conclusion in the experiment manifest
  and output summary.

## Repository context

- Reference strategy: `references/qlib-integration-codex/peer_momentum_runtime/signed_alpha.py`.
- Reference leave-one-out return: `references/qlib-integration-codex/peer_momentum_runtime/peer_return.py`.
- Completed reference artifacts: `references/qlib-integration-codex/outputs/signed_peer_momentum/`.
- Public qlibx strategy contracts: `src/qlibx/strategy.py`.
- Public signed execution entry point: `src/qlibx/execution.py::run_signed_execution`.
- The reference strategy source cannot currently be re-imported because its historical
  `kwam_enhanced_index` dependency is absent, but its completed run catalog and exact input/output
  matrices are present. Those immutable saved outputs form the baseline.

## Milestones

- [x] M1: Identify the exact reference strategy, parameters, data matrices, run IDs, and stored alpha.
- [x] M2: Create a self-contained experiment that reconstructs the strategy with qlibx contracts.
- [x] M3: Validate full weight parity against the stored reference alpha.
- [x] M4: Validate Qlib orders, fills, positions, accounts, and PnL under the qlibx data contract.
- [x] M5: Conclude the experiment and preserve concise evidence.

## Progress

- 2026-07-28: Confirmed reference run covers 242 dates and 309 tickers, with alpha run
  `alpha-0de88a959dcae708d628d50a65fbc81f` and backtest run
  `backtest-62bb86575bef4a448d37e19dd363178a`.
- 2026-07-28: Confirmed the reference formula uses previous-day leave-one-out equal-weight industry
  return, five-step linear decay with `dense=False`, absolute top 5%, 25% long and short exposure,
  and 5% per-name cap.
- 2026-07-28: Implemented 242 deterministic qlibx StrategyAgent decisions; all invocation and result
  IDs were unique and all 74,778 output weights exactly matched the reference alpha.
- 2026-07-28: Executed the stored reference alpha and independently generated qlibx alpha through
  qlibx. Orders, positions, account tables, and final PnL matched exactly. Fill floating-point
  intermediates differed by at most 7.450580596923828e-09 and were equal at 1e-8 tolerance.
- 2026-07-28: Concluded the experiment as `PASS_WITH_FLOAT_TOLERANCE`.

## Discoveries

- Experiment 003 is not a peer-momentum implementation; it uses each stock's own rolling return.
- This parity experiment deliberately uses the stored-matrix `run_signed_execution` path, while
  StrategyAgent decisions are compared separately from Qlib execution. That prevents an execution
  match from hiding a signal mismatch; adaptive agents can also use `run_strategy_execution` with
  `SignedExecutionConfig` outside this experiment.
- The saved reference input contains 4,078 non-unit `position_unit_factor` cells (range
  0.0972863907040908 to 2.0). qlibx correctly rejects this input because corporate-action
  normalization is upstream ETL responsibility. Its unit-factor execution nevertheless produced
  the exact same orders, positions, accounts, and PnL for this run.
- Bit-level fill equality is false in 269 diagnostic/numeric cells, but the maximum difference is
  below 1e-8; filled quantities and every downstream economic result are unchanged.

## Decision log

- Use the saved integration-codex input matrices and run catalog as the baseline so both
  implementations receive byte-for-byte equivalent logical inputs.
- Implement the strategy independently in the experiment while using qlibx public strategy
  contracts; do not import reference strategy code into the qlibx implementation.
- Run qlibx execution once with the stored baseline alpha and once with the independently generated
  qlibx alpha. The first isolates execution parity; the second measures end-to-end parity.
- Define user-visible result parity as exact weights, selections, orders, positions, accounts, and
  PnL plus fill equivalence at absolute tolerance 1e-8. Preserve bit-exact status separately.

## Validation

- `uv run python experiments/exp_004_peer_momentum_parity/run.py` — passed in 163.4 seconds;
  generated `PASS_WITH_FLOAT_TOLERANCE` evidence.
- Ruff check on `run.py` and `strategy.py` — passed.
- Independent summary assertions for same result, zero weight difference, zero PnL difference, and
  1e-8 table equivalence — passed.
- `git diff --check` on experiment and plan — passed.

## Risks and recovery

- The missing historical `kwam_enhanced_index` source means decay/scaling semantics must be
  reconstructed and checked against the stored alpha. A mismatch will be reported, not hidden.
- Experiment outputs are reproducible and isolated. Recovery is to rerun the experiment command;
  no production or upstream state is modified.

## Next action

None. Any production promotion of the experiment-local peer-momentum StrategyAgent requires a
separate user-authorized task.
