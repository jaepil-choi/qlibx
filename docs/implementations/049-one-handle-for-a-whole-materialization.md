# 049 — One handle for a whole materialization

`materialize()` built a fresh `DuckDbObservationStore` for every evaluation time and gave it no
`ScanSession`. `public.run()` had already solved exactly this for a simulation, and said so in a
comment: *"One physical handle for the whole run. duckdb caches parquet metadata for a
connection's lifetime, and closing per query threw that away on every observation."* The DataModel
path never received the same treatment.

The cost is two things with one root:

1. **The `RowsLookback` bound is never estimated.** `scan.observation_rows` only estimates a lower
   bound when it is handed a session — `elif rows is not None and session is not None`. A
   `RowsLookback` carries no bound of its own, so without the estimate every evaluation ranks
   `count(...) OVER (PARTITION BY instrument ...)` across the source's **entire** history. The
   estimator needs a session because the instant grid it reads is only worth keeping if it
   survives past one query.
2. **The source digest is re-hashed per evaluation.** `DuckDbObservationStore` caches it per
   instance, and the class comment justifies that with "one store instance lives for exactly one
   run". In the materialize path the instance lived for exactly one *evaluation*, so a 116-month
   build took the SHA-256 of a 127 MB file 116 times.

## What changed

`data_model_window` takes an optional `store`, defaulting to `None` so every existing caller is
unaffected. `materialize()` builds one `ScanSession` and one store around its evaluation loop and
closes the session in a `finally`.

## Evidence

Found and measured from outside the package, in `kwam-enhanced-index/vqapr-testbed-2/`, building
Fama-French-family factors on 4,841 Korean names. The A/B constructs both code paths through the
public API against one registered workspace, so it reproduces on an unpatched package:

| | per evaluation | rows |
|---|---|---|
| store per evaluation, no session (what `materialize` did) | 2.90s | 885,969 |
| one store + one session (what `run()` does) | 1.47s | 885,969 |

**1.97x, identical output.** On the real build, 116 monthly evaluations plus 105 momentum plus 9
annual went from **445.8s to 265.4s — 1.68x**, with row counts identical at every phase
(372,726 / 321,781 / 16,113).

One phase got *slower*: `momentum_12_2`, 3.00s to 3.90s. It reads a derived 1.5 MB panel, below
`ROWS_BOUND_MIN_BYTES`, where `scan.py` documents that estimating costs more than it saves. The
session buys nothing there and its setup is the whole difference. That is the documented regime
working as designed, not a regression hiding inside an average.

A prediction worth recording because it was **wrong**: the finding first claimed
`annual_characteristics` would not benefit, since its statement requirement uses a
`CalendarLookback` that carries its own bound. Measured, that phase improved **2.31x** — the most
of any. A DataModel declares several requirements, and this one also reads `stock_daily` through a
`RowsLookback`. Reasoning about a model's headline lookback rather than about every requirement it
declares is what made the prediction wrong.

## Four smaller fixes, from the same build

**`publish_run_allocation` took evidence while `publish_run_record` took the result.** Two
publication functions with near-identical signatures, called two lines apart, wanted different
things, and passing the wrong one produced a bare `TypeError` from inside a `tuple()` call rather
than a typed refusal. It now accepts either.

**A dollar-neutral `rescale` needs `grid`.** `rescale` settles each side against its own target,
so long lands on exactly `+1` and short on exactly `-1`, but nothing makes their *sum* exact — a
~1,000-name book left `-1.674E-28` between the sides. That is invisible until the intent boundary,
which requires `sum(weights) + cash_target == 1` exactly and refuses at the 28th digit, because
`Decimal(1) - (-1.674E-28)` rounds back to `1`. The shipped showcase uses `long=0.02` on six
names, where the residual never surfaces, so the most standard long-short book there is hits an
error message with no pointer to the one-word fix. Documented in the docstring; no behaviour
change.

**A valuation agenda cannot outpace strategy execution instants.** A valuation occurrence reports
the mark the Account already committed; it does not derive a new one. Marks are committed at
execution instants, which exist only where a callback produced an intent or a `NoDecision` that
took a pending valuation. A daily valuation agenda over a monthly strategy agenda is accepted
without complaint and silently yields a monthly NAV series. Documented on `ValuationConfig`.

**A component conflict now names the id that would work.** Editing a registered component is the
ordinary development loop, and "use a new identity" without saying which one leaves every user to
invent the same fingerprint-suffix scheme by hand. The refusal now reports both fingerprints and
suggests `<id>-<fingerprint[:12]>`.

## Not done

`domain/rows.py:normalize_rows` validates every key of every row with
`any(char.isspace() for char in key)` — 53.6M `str.isspace` calls for 6.25M scalars in one
14-evaluation build, ranking second behind the query itself. The keys of a query result are the
same handful of registered field names on every row. Left alone deliberately: it is a validation
boundary, the finding has a frame ranking and **no A/B**, and a correctness boundary is the wrong
thing to change on a profile alone.

## Validation

```
uv run --no-sync ruff check src/ tests/          # clean
uv run --no-sync pytest -q                       # 691 passed
uv run --no-sync python showcases/show_00N_*/run.py   # all eight OK
```

`show_002` is the sharp one: it asserts PIT future-exclusion, package-owned `available_at`,
derived-dataset reread and producer-timestamp forgery rejection, all on the path that changed.

End to end in the testbed, the five factors rebuilt on the patched framework compare to published
Kimchi factors **byte-identically** to the pre-patch run — correlations 0.9177 (CMA) to 0.9847
(MOM), against 0.9416 and 0.9908 for the pandas replication the testbed checks alongside.

`ruff format --check` reports two pre-existing blocks in `weighting.py:155` and `workspace.py:500`
that are also unformatted on a clean tree. Left alone: they are nobody's change here, and
reformatting them would put an unrelated hunk in a behaviour commit.
