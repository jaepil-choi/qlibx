# 016 — Make signals, and measure what they predict

## Why this exists

Canon specified `transforms/` and `analysis/` file by file, with a stated reason for each entry, and
both shipped as zero-byte files. Nothing downstream was possible without them: the three
market-and-price alphas of the next milestone are cross-sectional operations over neutralised
signals measured by an information coefficient, and every one of those words named an empty file.

This milestone implements that specification and proves it by reproducing a figure from an
externally published research report on committed real market data.

## What was built

| Deliverable | Location |
|---|---|
| Causal window primitive | `src/vqapr/transforms/window.py` |
| Cross-sectional operations | `src/vqapr/transforms/cross_section.py` |
| Missing-value handling | `src/vqapr/transforms/missing.py` |
| Neutralisation by regression | `src/vqapr/transforms/neutralize.py` |
| Constituent-to-exposure mapping | `src/vqapr/transforms/lookthrough.py` |
| Signal statistics | `src/vqapr/analysis/signal.py` |
| Performance statistics | `src/vqapr/analysis/performance.py` |
| Figure-3 fixture and generator | `tests/fixtures/report_figure_03/`, `scripts/extract_report_figure_03_fixture.py` |
| Vendor cross-section fixture | `tests/fixtures/real_k200/`, `scripts/extract_real_k200_fixture.py` |
| Headline falsification | `tests/acceptance/test_figure_03_neutralization.py` |
| Real-spine signal run | `showcases/show_007_signal_measurement/` |

## How it works

**The window primitive guards a leak the point-in-time boundary cannot see.** That boundary stops a
strategy *reading* outside point-in-time; it cannot stop a rolling statistic *reaching* outside the
window it was already handed. `apply_causal` closes that the only way a rule cannot be forgotten:
there is no index to reach with. It slices the trailing window itself and hands the callable nothing
but values, so a callable that wanted the future would have to be given it. Alignment across series
is refused in the driver before any step, and warm-up reports absence rather than a number computed
from a short window.

**Neutralisation is exact because the refusal has to be honest.** Under floating point a rank
deficient exposure matrix is a small pivot and the code must guess a threshold. Under `Fraction` it
is a zero pivot, so deficiency is a structural fact that can be detected and *named*. The proof that
neutralisation is not a no-op is weighted orthogonality asserted on the rational residual before any
quantisation, so the primary falsifier carries no tunable number.

**Analysis reads what was stored and never manufactures a return.** `performance.py` accepts the
mark type the valuation layer produces and refuses anything else by name, so handing it a price
panel raises rather than returning a plausible number the ledger never agreed to. That enforcement
is by input type, not by docstring.

**Look-through is a matrix, not a product feature.** `exposure = L @ holdings` covers depositary
receipts, futures and funds of funds alike; nothing in the module knows what an exchange-traded fund
is. Canon requires that the package never expand a holding on its own, so both panels arrive as
arguments and there is no discovery path.

## The retarget, stated plainly

**The published figure-3 numbers could not be reproduced, and the milestone says so rather than
implying otherwise.**

The bm-scaled report states its figures over 2018-01-02 to 2026-07-28, 2,102 observations. That
input no longer exists. All three recorded source hashes fail against what is on disk, and against
the older manifest's hashes, so the cache is a third state. Reading the data directly showed why:
every panel now spans 2020-01-03 to 2026-05-22, 1,562 rows — two years late and two months early —
and no panel anywhere in the reference repository covers the published range.

Autonomous recovery was attempted and is unavailable: the reference project's environment cannot be
built here, because `pyqlib` publishes only cp312 wheels and this machine runs CPython 3.13.

The user chose to **retarget to the window that exists** rather than weaken the criterion. The
generator applies the report's own recipe — transcribed unchanged — to the panels that do exist.
What is preserved is that the target is still produced by somebody else's method from somebody
else's data. What is lost is the ability to quote the published figures.

| | published | retargeted |
|---|---:|---:|
| baseline annualised return | 0.14043 | 0.43623 |
| baseline information ratio | 0.54740 | 1.46755 |
| demeaned annualised return | 0.06502 | 0.24875 |
| demeaned information ratio | 0.40331 | 1.27162 |
| mean absolute beta, baseline → demeaned | — | 0.46193 → 0.10833 |

**Both halves of figure 3's claim survive the new window**: neutralisation drops the return
substantially, and it drives the market beta toward zero. The second half is the one an earlier plan
revision silently dropped and the review lanes caught.

Because the target is recomputed, the upstream manifest carries **no authority** over it and the
panels are pinned by their own hashes, which the fixture manifest states. The return matrix is
un-gated in the sense of having no upstream hash, but it is authenticated by the headline criterion
itself: four numbers cannot be reproduced to a thousandth from the wrong returns.

## Trade-offs

**Report-derived panels are committed.** About 5.5 MB, which touched the earlier no-redistribution
constraint. The alternative — skipping when absent — was rejected by both review lanes, because a
criterion that cannot fail on a clean checkout is not a criterion. Narrowing was shown to be
arithmetically unsound: the cross-sectional demean counts every universe member, so dropping one
instrument shifts every demeaned weight, the gross rescale, and through the benchmark leg both
rolling betas.

**Perfect correlation is special-cased, deliberately.** `Decimal.sqrt` is correctly rounded, so a
signal correlated with itself returned 0.9999999999999999999999999998. Comparing with a tolerance
would have made the anchor weaker than the claim it anchors, so the sums run in exact rationals and
perfect correlation is recognised structurally instead.

**The capability check runs in a subprocess.** In-suite it would be guaranteed-red: `conftest`
imports duckdb session-wide and `vqapr.public` pulls in the data, flow and evidence layers. Canon
refuses an import-linter tool contract, so the signature is the primary contract and the subprocess
check is corroboration. A control probe proves the check can go red.

## Deliberately not built

No `fill_missing`, because filling zero is an economic claim. No import-linter tool contract, which
canon explicitly refuses. No ensemble weighting methods, enhanced-index conversion, order blotter or
report assets — those are later milestones, and `renderers.py`, `activity.py`, `ledger.py` and
`diagnostics.py` remain at zero bytes.

## What M2 gets for free

- **Signal construction**: rank, zscore, demean, winsorize, buckets, and a causal driver that
  already carries the two-series form beta needs.
- **Neutralisation**: exact, weighted, with a named refusal on rank deficiency, exercised against a
  dependent exposure set built from real classifications.
- **Measurement**: information coefficient and its rank form, hit rate, decay, and performance
  statistics that read stored marks.
- **A worked real-spine example**: `show_007` publishes recorded signal and account tables and
  re-hydrates marks field-for-field, which is the pattern M2's three alphas follow.

M2 therefore adds alpha definitions and a family ensemble, not infrastructure.

## Follow-ups

- **The report's industry exposure panels were not committed.** The approved plan made them
  mandatory members of the figure-3 fixture so the orthogonality falsifier could run against the
  report's own exposure matrix. They are not in the shipped fixture, so that falsifier runs against
  constructed exposures and against the real classifications in `tests/fixtures/real_k200`
  instead. Any later criterion whose *value* depends on an exposure matrix must commit those panels
  and establish their authority first.
- **The published figure-3 window is unrecoverable here.** If the reference cache is ever
  regenerated over the full range, the drift shows up as a failing `--check` — which compares the
  recomputed contract and span against the committed ones — and the retarget can be revisited. Note
  that the generator does not gate on the source hashes; it records them. The committed panels are
  protected by `test_every_committed_panel_matches_its_recorded_hash`, not by the generator.
- **Thinness is not what makes the exposure matrix singular, and an earlier version of this record
  said it was.** The refusal is caused by a complete dummy set summing to a market column, which is
  true for any industry widths. A genuine single-name industry alongside a market column is
  *accepted*, because that pair has determinant `n - 1`. The test now asserts both directions and
  the fixture's stated purpose is corrected. The claim was unfalsifiable as written, and the review
  lanes' own earlier framing of it was wrong in the same way.
- **The beta half of the headline claim runs no vqapr code.** `rolling_beta` is the reference
  recipe throughout; `window_beta` and `apply_causal` never touch the acceptance panels. The return
  half does exercise `demean` and `neutralize`, and the beta half is pinned against the contract,
  its sign, its window and an input perturbation — but it is a reproduction, not a product test.
- **The orthogonality falsifier asserts a derived quantum budget**, `n × 1e-12 × max|loading|`,
  rather than exact rational zero as the milestone originally specified. The residual is exactly
  orthogonal before it is returned; the return is quantised, and a red-team lane measured deviations
  up to 3e-12 on the returned values. The budget is derived from the quantum rather than tuned, and
  the departure is recorded here rather than left in the gap between the constraint and the code.
- **The beta window is pinned by the fixture, not by the tolerance.** A red-team sweep measured
  that any rolling window from 57 to 63 sessions reproduces the published beta figures inside the
  ratio ceiling, so the tolerance cannot separate a seven-session band around the true 60. The
  window is recorded in the fixture contract instead. Tightening a ceiling sized for float
  accumulation would not be the right fix.
- **A pipeline that ignored its benchmark argument would defeat the benchmark perturbation.** The
  gate proves the beta numbers are live given that the argument is consumed; it does not itself
  prove consumption. Named here rather than left for a later reader to discover.
- **`analysis/signal.py`'s general correlation path has no value-level assertion.** Every plus or
  minus one anchor lands on the exact-rational short circuit, so the square-root branch is covered
  only by an inequality. This is the same shape as the beta sign defect the red-team lane found:
  a real function whose answer space is certified by assertions that cannot distinguish it from a
  constant.
- **The capability probe covers one of five leaves.** `cross_section`, `missing`, `lookthrough` and
  `neutralize` could acquire a forbidden import without the boundary suite noticing.
- **`quantile_buckets` records no breakpoints.** Canon gives breakpoint recording as part of why
  the function exists, and the shipped version returns assignments only. Nothing in M1 consumes
  them, and canon assigns the recording itself to the membership DataModel, so this is a capability
  gap rather than a broken contract.
- **The showcase does not call `apply_causal` or any `analysis/` function.** The causal guarantee is
  structural and unit-tested rather than integration-dependent, and the mark re-hydration seam is
  proved field-for-field, but no analysis value has yet been computed from a run inside a showcase.
- **`scripts/evidence_calendar.py` imports modules that do not exist** (`runtime/calendar_derivation.py`
  and `runtime/timeline.py` are absent). Pre-existing, outside this milestone, and untouched.

## Validation

- `uv run pytest -q` — 478 passed, from 356 at the milestone start.
- `uv run ruff check` and `ruff format --check` clean; package imports with 115 pinned exports,
  including `Mark` and `MarkBatch` so the showcase and the analysis tests reach them through the
  public surface rather than through `vqapr.valuation.marks`.
- `uv run python showcases/show_007_signal_measurement/run.py` — one real run, 64 published and
  re-read signal rows, 21 account rows, 60 marks re-hydrated across 15 account versions all
  field-for-field equal to the committed ones, fill-journal replay matching exactly, identical
  SHA-256 manifests across two clean runs.
- `uv run python scripts/extract_report_figure_03_fixture.py --check` and the standing fixture tests
  confirm the committed panels remain the ones their manifests describe.
