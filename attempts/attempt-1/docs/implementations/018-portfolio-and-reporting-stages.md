# Two declared stages start reporting failures

Specifies PRD 5.6. Closes the gap `015-stage-based-errors.md` and `017-stage-recovery-in-the-skill.md`
both recorded as open.

## Why this change exists

`PORTFOLIO` and `REPORTING` were in `errors.STAGES` and raised nowhere. Every failure in
`portfolio.py` (13) and `reporting.py` (6) was a bare `ValueError`, so an agent that mis-ordered
a report or passed incomplete bounds got a string and no stage — it could not tell which step of
the journey it was in, and the stage-recovery reference had to carry a note telling it to match
those failures by message.

A declared stage that never arrives is worse than an undeclared one. It reads as a promise.

## The judgement at each site

The rule from `015-stage-based-errors.md`: *which stage is the caller in, and could they have caused
this?* All nineteen answered the same way. They are input-contract checks at the top of
`construct_enhanced_index`, `compose_report`, `render_report` and `analyze_stored_run` — the
caller supplied the value and the caller can supply a different one.

Nothing was promoted that the caller could not have caused. Infeasibility and solver failure were
already **returned** as `EnhancedIndexResult.status` rather than raised, and they stay that way: a
portfolio that cannot be built is a result, not a broken contract.

## What the context carries

The message says a rule broke; `context` says which name broke it, because that is the question
the agent has to answer before it can talk to the user:

```python
raise QlibxError(
    "PORTFOLIO",
    "lot_size must be present and positive for every physical instrument",
    expected="Every physical instrument declares a positive lot size.",
    context={"invalid": sorted({str(name) for name in lots.index[lots.isna() | lots.le(0)]})},
)
```

- `portfolio`: `invalid` (lot size, bounds, cost), `duplicated` / `missing_or_non_positive`
  (price), `undeclared` (instrument type), `uncovered` and `only_in_*` (look-through axes),
  `constituents_with_missing`, and both timestamps on the look-ahead refusal.
- `reporting`: `available` and `unknown` for section ids, `missing_from_order` / `not_selected`
  for the ordering mismatch, `run_kind` for a non-backtest run.

The unsupported-renderer case became `errors.unknown_name("REPORTING", "renderer", ...)` rather
than a hand-written failure, so it lands in the same shape as every other named lookup in the
package and the agent reads its options from `context["available"]`.

Look-ahead is the one worth naming: `ETF constituent data was not available at decision time` now
carries `constituent_available_at` and `decision_time`, so the agent can see how far ahead the
constituents were instead of re-deriving it.

## `optimization.py` cannot follow, and that is the layering working

The other 22 bare `ValueError`s are in `optimization.py`, which is layer 0.
`test_kernel_has_no_intra_package_dependencies` forbids it from importing `errors`, so it cannot
raise a `QlibxError` at all.

This is not a site-by-site judgement that got skipped. `LinearConstraint` and `OptimizerConfig`
are re-exported through `portfolio.__all__`, so a caller building a constraint does receive a
stageless failure from a public surface. Fixing it means deciding whether `optimization` belongs
in the kernel — an architecture question, not a refactor, and one for the user to call. The
generated skill states the limitation instead of hiding it.

## Invariants

- `test_portfolio_input_failures_name_the_stage_and_the_offending_instruments` — lot size and
  bounds violations name `PORTFOLIO` and put the offending instrument in `context["invalid"]`.
- `test_composition_failures_name_the_reporting_stage_and_show_the_alternatives` — unknown
  section ids expose `context["available"]`; a bad order exposes `missing_from_order`.
- `test_an_unsupported_renderer_reports_the_ones_that_exist` — the shared named-lookup shape.
- `test_point_in_time_etf_lookthrough_is_separate_and_reports_solver_state` was already asserting
  the look-ahead refusal against `ValueError`. It now asserts `QlibxError`, the stage, and that
  the context timestamps actually show the look-ahead — strictly more than it checked before.
  This is the only existing test the change edited, and the assertion it replaced was the one
  this task exists to change.

## Validation

- `uv run pytest`: `164 passed` (161 at `13bfd7a` plus three new tests). `ruff check` and
  `ruff format --check` clean.
- The stage-recovery reference was updated in the same pass: the four symptoms that said "raised
  as a plain `ValueError`" now point at the context keys instead, and `UNCLASSIFIED_STAGES` no
  longer claims the whole of `PORTFOLIO` and `REPORTING` — it now says exactly what remains
  unclassified, which is the optimizer kernel's self-validation.
- Remaining bare `ValueError`s outside `_vendor`, for the next pass: `optimization` 22,
  `extensions` 11, `alpha/*` 20, `requirements` 5, `ensemble` 5, `serialization` 2, and one each
  in `skill` and `onboarding`.

## Still open

`ensemble.py` (5) is the next honest candidate — `ensemble requires at least one member` and
`ensemble members have incompatible axis semantics` are caller-caused failures in the
`PORTFOLIO` stage's neighbourhood. `extensions.py` (11) is `ONBOARDING`-adjacent. Neither was
touched here because this task's scope was the two stages that were declared and silent.
