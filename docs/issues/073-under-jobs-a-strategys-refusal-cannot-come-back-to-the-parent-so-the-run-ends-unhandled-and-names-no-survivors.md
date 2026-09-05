# 073 -- under `--jobs` a strategy's refusal cannot come back to the parent, so the run ends `unhandled` and names no survivors

**Status:** **CLOSED 2026-09-04** on `fix/073-the-run-reports-per-strategy`, record `docs/implementations/150-the-run-reports-per-strategy.md`. A worker returns a `StrategyOutcome` (the failure's `as_dict()`, never the exception); `run()` returns an outcome for every strategy, completed or failed, in both modes and continues past a refusal; the envelope is `ok:false`, `stage: run.strategy_failed`, with the same `strategies` map as a green run plus a `status` per strategy and the failed one's refusal in its block. A test raises inside a worker under `--jobs`. `not_started` was not needed: the run no longer stops.

**Status when filed:** open. Found 2026-09-04 by the scenario testbed run 4
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-009**, with **F-006** as the single-process
form and **F-008** as the ten minutes it cost), against `vqapr-0.4.0`. Confirmed against source
2026-09-04 on `fix/0.4.0-open-issues`; nothing on this branch touches the path. The heaviest
finding of that run: it cost two full ten-minute runs, and while the first one was alive nothing on
the surface could say whether a strategy that had stopped writing was dead or paused.

**Touches:** `src/vqapr/flow/orchestration.py:195-212` (the `--jobs` branch: `future.result()` in
submission order, the first exception escapes the `with`); `src/vqapr/evidence/artifacts.py:141-194`
(`SimulationFailure.__init__` is keyword-only and stores `failed_requirement`, `observed`, `cause`
on the instance); `src/vqapr/flow/context.py:454-477` (`failed_requirement=owner`, where `owner` is
the `Rebalance`, the publication evidence or the layer config); `src/vqapr/authoring.py:166,176`
(`Rebalance.target_weights` is a `MappingProxyType`); `src/vqapr/cli/envelope.py:104-` (anything
without `as_dict()` renders as `stage: unhandled`, `failures: []`).

## What happens

Eight strategies, `vqapr run ff-arm --jobs 4`. One of them (`ou_k0`) had its `Rebalance` refused at
its 308th session -- the refusal `071` describes. In a single process that is a structured
`simulation.callback.intent` failure. In a worker it became this, ten minutes later:

```json
{"ok": false, "stage": "unhandled", "family": null, "failures": [],
 "error": "TypeError: cannot pickle 'mappingproxy' object",
 "detail": ".vqapr/diagnostics/unhandled.txt"}
```

The diagnostics file holds three tracebacks: the `ValueError` from `Rebalance.__post_init__`, the
`SimulationFailure` the Flow wrapped it in, and `concurrent.futures.process._sendback_result`
failing to pickle that `SimulationFailure` on the way back to the parent. The real refusal is
visible only there.

On disk seven strategies had `strategy.json` and complete tables; `ou_k0` had 307 sessions of rows
and no record. The envelope mentioned none of the eight. The author found the seven with
`vqapr list strategies --run ff-arm`, and found what had happened to the eighth by reading the
diagnostics file.

The single-process form is the same reporting gap without the pickling error (**F-006**, an
earlier run of the same eight): strategies execute in registration order, the run stops at the first
exception, the three that had finished were not listed and the four after it never started. The
payload said which callback raised and nothing about the other seven.

## Why

Two independent things.

**The failure cannot cross a process boundary.** `SimulationFailure` is built with keyword-only
arguments and keeps its owner objects on `self`. `BaseException.__reduce__` pickles `(cls, args,
__dict__)`, and `__dict__` carries `failed_requirement=owner` -- for an intent-stage refusal that
is the `Rebalance` itself, whose `target_weights` is a `MappingProxyType`, which pickle refuses.
Had it pickled, the parent would have failed anyway: unpickling calls `cls(*args)` and the
constructor takes no positional arguments. So no `SimulationFailure` raised in a worker has ever
reached the parent as itself. `tests/flow/test_a_run_holds_several_strategies.py::
test_jobs_runs_the_strategies_in_processes_and_the_records_come_back` covers the happy path
only; no test raises inside a worker.

**The run has no per-strategy outcome.** `RunResult` carries records for strategies that finished
and the exception for the one that did not; there is no place in either the success or the
failure envelope for *this one completed, this one failed at session N, these did not start*. In
the `--jobs` branch the parent collects `future.result()` in submission order and re-raises the
first exception it meets, so a strategy that failed early in a later slot is reported after every
earlier one has run to completion -- the ten minutes of **F-008** -- and the ones that completed
are not named.

## What to do

- Make the failure picklable, or do not send it. The smallest change is a `__reduce__` on
  `SimulationFailure` that carries `as_dict()` plus the bounded scalars and rebuilds a
  `SimulationFailure`-shaped exception in the parent; the alternative is for
  `run_registered_strategy` to catch it in the worker and return a `{"failed": failure.as_dict()}`
  value beside the record path, so `future.result()` never raises for a refusal. Either way the
  parent must render the same `simulation.callback.intent` payload a single-process run renders.
- Give the run a per-strategy outcome and put it in both envelopes: `strategies: {<id>:
  {status: completed | failed | not_started, record?: ..., failure?: ..., last_session?: ...}}`.
  With that in place the third bullet of `071` (should one strategy's refusal stop the others?)
  has a place to record its answer, whichever way it goes: under `--jobs` the other workers finish
  anyway, and the payload should say so instead of hiding it behind `failures: []`.
- One sentence in `run --help` and the skill: an exception in one strategy ends the run for the
  strategies after it in a single process, and under `--jobs` the others run to completion but the
  run reports `ok: false`. Today the skill's "each strategy runs with its OWN account" reads as
  isolation and nothing corrects it.
- A test that raises inside a worker under `--jobs` and asserts the parent's payload names the
  strategy, the session and the refusal.

Related: `071` (the refusal that was lost here, and the identity it lacks), `016` (closed by
record `088`: a callback failure once dropped half the envelope; this is the same shape one
process boundary further out), `037` (a killed run and a live one look alike on disk).
