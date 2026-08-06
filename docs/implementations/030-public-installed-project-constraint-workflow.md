# 030 Public installed-project constraint workflow

## Intent

Close the default public-workflow portion of `GAP-CONSTRAINT-001`. The pure no-short and
benchmark-relative single-name-cap calculations and artifact-backed flows already existed, but an
installed user had no root public specification or `QlibxProject` facade for selecting adjustment
and independent validation. The internal request also accepted arbitrary floor values and caller-
authored config fingerprints, which was too broad for the current fixed 10% MVP claim.

## Observable outcome

An installed user can opt into constraint adjustment and then independently validate its immutable
artifact. A constraint-free Strategy still runs without benchmark registration. The public policy
supports exactly:

- no short positions; and
- `weight <= max(10%, PIT benchmark constituent weight)`.

Missing, ambiguous, future-hidden, or incomplete benchmark data fails with `CommitStatus.NONE`.
One-share lot flooring can leave a positive residual breach; adjustment still publishes the exact
residual, while independent validation returns `eligible=false` rather than silently redistributing
or approving the candidate.

## Responsibilities and flow

- `MvpConstraintPolicy` states the honest current policy boundary. It fixes no-short and the 10%
  floor while allowing an explicit benchmark role and optional exact dataset binding.
- `ConstraintAdjustmentSpec` owns invocation input, account-state identity, capital, and execution
  lot inputs. It rejects naive timestamps and duplicate instruments, canonicalizes mapping-like lot
  order by instrument, and derives a deterministic fingerprint from policy and sizing inputs.
- `ConstraintValidationSpec` independently freezes the selected policy and cutoff and derives its
  own config fingerprint.
- `QlibxProject.adjust_constraints` and `QlibxProject.validate_constraints` translate those public
  specs to the existing `ConstraintFlow`. They remain separate operations; adjustment completion is
  not execution eligibility.
- Validation now requires the exact benchmark `AccessRecord` tuple used by adjustment. A changed
  dataset registration fails with `CONSTRAINT_BENCHMARK_IDENTITY_MISMATCH`, even when policy ID,
  cutoff, and observed numeric values happen to match.
- The separate `constraint-workflow-v1` sample creates a signed portfolio without benchmark data,
  then selects the public constraint capability. Its two benchmark weights come from the audited
  K200 projection and become available at the confirmed next distinct session at 09:00 Asia/Seoul.
  Its lot prices are the two real 2024-01-03 closes.

## Evidence and failure authority

Adjustment lineage includes the source portfolio artifact, canonical config fingerprint, explicit
account-state identity, and benchmark registration. Validation lineage includes the adjustment
artifact, its own config fingerprint, and the same benchmark registration. Neither operation owns
orders, Account commits, or Strategy Memory. Requirement, coverage, lot, cutoff, declaration, and
benchmark-identity failures therefore remain `CommitStatus.NONE` and publish failure evidence only.

## Alternatives and trade-offs

Exposing `ConstraintDeclaration` and the internal request models directly from the package root was
rejected. That would let the public MVP claim arbitrary floors and arbitrary fingerprints. The
existing internal types remain reusable inside lower-level workflows, while the root facade is
narrower and truthful.

Automatically attaching constraints to `run_daily` was rejected. Strategy-only research and other
constraint-free workflows must not acquire benchmark requirements, and the current daily Strategy
returns decision targets rather than a portfolio-construction artifact. A later execution gate can
compose the public operations explicitly if its order-conversion contract is approved.

Comparing only benchmark values was rejected. Equal numbers from different registrations do not
establish producer identity, PIT lineage, or reproducible validation. Exact access identity is the
safer current local contract.

The adjustment remains deterministic clipping plus order-delta lot flooring, not an optimizer. It
does not redistribute residual cash or search for a globally feasible portfolio.

## Validation

- Public constraint models/facade plus pure constraint unit tests:
  `uv run --cache-dir .uv-cache pytest tests/test_public_constraints.py tests/test_portfolio_constraints.py -q --basetemp C:\tmp\qlibx-m12-public-constraints-20260807b -p no:cacheprovider`
  -> 8 passed in 1.74s.
- New and existing sample compatibility:
  `uv run --cache-dir .uv-cache pytest tests/test_public_constraint_sample.py tests/test_public_daily_sample.py tests/test_sample.py -q --basetemp C:\tmp\qlibx-m12-public-samples-20260807a -p no:cacheprovider`
  -> 9 passed in 7.99s.
- Public constraint plus existing real-DW acceptance:
  `uv run --cache-dir .uv-cache pytest tests/acceptance/test_research_scenarios.py::test_uc_constraint_002_and_uc_constraint_adjust_001_use_confirmed_k200_cutoff tests/acceptance/test_research_scenarios.py::test_uc_signal_001_and_uc_constraint_001_complete_direct_real_dw_research tests/test_public_constraints.py tests/test_public_constraint_sample.py -q --basetemp C:\tmp\qlibx-m12-constraint-acceptance-20260807a -p no:cacheprovider`
  -> 11 passed in 6.93s.
- Checkout sample smoke -> A000660 adjusted to zero, A005930 adjusted to
  0.31752577319587627 with unresolved excess 0.00032577319587628883, and independent validation
  returned `eligible=false`.
- Full suite:
  `uv run --cache-dir .uv-cache pytest -q --basetemp C:\tmp\qlibx-m12-full-20260807a -p no:cacheprovider`
  -> 134 passed in 106.32s.
- `uv run --cache-dir .uv-cache ruff check .` -> passed.
- `git diff --check` -> passed with only Git's informational LF-to-CRLF warnings.
- `uv build --cache-dir .uv-cache` -> built `dist\qlibx-0.1.0.tar.gz` and
  `dist\qlibx-0.1.0-py3-none-any.whl`.
- Wheel inspection -> 103 entries; includes `qlibx/constraints.py` and all seven
  `qlibx/resources/samples/constraint_workflow` files.
- Installed-wheel smoke from `C:\tmp\qlibx-wheel-target-m12-20260807` imported qlibx from that
  exact target, materialized the constraint sample into a fresh project, and reproduced the
  checkout result: A000660 0.0, A005930 0.31752577319587627, unresolved excess
  0.00032577319587628883, `eligible=false`.

The initial repository-local pytest basetemp attempt failed during pytest cleanup with
`PermissionError: [WinError 5]` under `.agent/runs`. Following the profile-specific Windows
workflow, validation uses task-scoped `C:\tmp` basetemp paths. One initial assertion also omitted
`include_failure=True` when listing failure evidence; the production catalog had published the
failure correctly and the test query was fixed. The first sandboxed build could not fetch
`uv-build` from PyPI (`os error 10061`); the same command succeeded after scoped network
escalation, so no dependency or build configuration change was required.

## Remaining limitations

- Only no-short and the fixed 10%/benchmark single-name cap are current public constraints.
- Sector, turnover, liquidity, leverage, gross/net exposure, and override policies remain future.
- Adjustment and validation do not create orders or mutate Account/Memory.
- The local exact-access comparison does not define external registry or distributed-data identity.
- Partial fills, pending/cancel/reject lifecycle, settlement timing, and OMS reconciliation remain
  outside this workflow.