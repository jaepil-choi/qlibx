# Handoff — closing the gaps the testbed exposed

Status: in_progress
Branch: `jaepil-develop` · last commit `6c74f4e` · **tree is green: 567 passed, ruff clean**

Written because the session kept dropping mid-task. Everything below is verified, not remembered.

---

## Read this first: two review claims are false

A review agent's report drives this work. Two of its findings are wrong, and acting on them means
being told to use things that do not exist.

**A5 — "the framework ships `testing/conformance/{strategy_model,datamodel,exchange,constraint,runner}.py`."**
It does not. Those were 0-byte scaffold, verified unreferenced, deleted in `6756e67`. `testing/`
holds two empty `__init__.py` files and `public.__all__` exports nothing conformance-related. The
reviewer read canon §10.3's *declaration* as code. **"Not used" and "does not exist" call for
opposite work.**

**A6 — "`agent/` is unused."** Partly wrong. `agent/sample` and `agent/skill` are real. The three
files cited as evidence were empty scaffold, also deleted.

Everything else in the review checks out.

---

## Immediate state: one uncommitted edit

`src/vqapr/portfolio/weighting.py` — `_settle` now takes `grid: Decimal | None = None` and
quantizes members before settling the residual. Backward compatible (default `None`), which is why
567 still pass with the work half done.

**Remaining, ~15 minutes:**

1. Add `grid: Decimal | None = None` to `rescale`'s keyword-only parameters.
2. Pass it through both `_settle` calls at the end of `rescale` (weighting.py:207-208).
3. Tests: a gridded dollar-neutral book sums to exactly zero; the residual lands on the largest
   member; the result is order independent; `grid=None` is unchanged from today.
4. Commit. **Do not bump the version** — the user asked to hold it until the testbed round finishes.

### What B7 actually is, because the review misdescribes it

The review says the user invented `_settle` because the framework lacked it. Not so: `weighting.py`
**already has** `_settle` and `rescale` already calls it once per side. Both the framework and the
testbed have a function of that name.

The real gap is narrower. Framework `_settle` makes each side **sum** to its target but never puts
weights **on a grid**. So `rescale` returns exact ratios, the user quantizes afterwards, and
quantizing re-breaks the sum `_settle` just fixed — which is why their copy settles a *second* time
onto the largest name.

`QUANTUM` / `QUANTIZATION_EXPONENT` already live in `optimize.py`, so the grid concept is in the
framework; `rescale` simply does not know it.

**Order is load-bearing: quantize first, settle second.** The reverse is the bug being fixed.

---

## Done and committed

| commit | what | evidence |
|---|---|---|
| `660b159` | all four extension points get a registering door | Exchange/Constraint were registering with **no load validation**; a subclass replacing `execute()` was silently accepted |
| `41ff610` | `workspace.instruments()` / `.evaluation_times()` / `window.snapshot()` | first `snapshot()` attempt reproduced the stale-row bug; the test caught it |
| `28d64b8` | `context.source_refs()` / `context.intent(...)` | test pins the helper equals `SimulationFlow._actual_source_refs` |
| `55ee610` | workspace write serialisation | 8 real processes: **lock off 3/8 survived, lock on 8/8** |
| `6c74f4e` | `OperationAgenda.daily()` | DST derived, not typed: NY is `-05:00` in March and `-04:00` in April |

Earlier in the same session: `f2f4013`…`c11d2e3` (hot-path performance, execution-priced valuation,
account history retention, fill-journal publication). Those are described in
`docs/implementations/021`–`027`.

---

## Remaining work, in the order I would take it

**B8 — a registered dataset cannot be used as an execution table.**
`step3_run_alpha.py:104` reads the already-registered `k200-prices`, renames columns, and writes a
separate parquet: **3,302,492 rows duplicated on disk.** Largest single waste left.

**A3 — the `vqapr run` CLI is unverified.**
`cli/run.py` already does spec.yaml → `RunDefinition` → `preflight_run` → `run`, but the testbed
assembles `RunDefinition` by hand in two 302-line workers and never invokes the CLI. The user's
question — *"are we actually registering and running like a real user?"* — answers **no**: the
testbed uses the library API, so the CLI surface has no coverage at all.

**`register --dry-run` does not exist.** `dry-run`/`dry_run` appears **0 times** in `src/`. If it is
wanted it is new work, and it belongs after the conformance suite, which is what a dry run would
check beyond the fingerprint.

**`testing/` conformance suite.** Canon §10.2 says a component *"must pass the same conformance
suite to be registered"*. No such suite exists. This is a broken promise rather than dead scaffold,
which is why the empty package was kept rather than deleted. Either build it or withdraw the claim
from canon — the current state is neither.

---

## Not ours to decide

**A1 — replacing the testbed's `_project`/`_centre` with `neutralize()`.** Sequential
industry-demean-then-beta and simultaneous regression give different answers when industry and beta
are correlated. Which one the source research used is a fact the user holds, and it **changes
reproduction numbers**, so it must not ride along with framework work whose evidence is that
numbers do not move.

---

## How to verify anything here

```
uv run pytest -q                      # 567 passed
uv run ruff check src/ tests/         # clean
uv run python showcases/show_00N_*/run.py    # all eight run; 005 and 007 are the sharp ones
```

G-4 style result invariance: `.agent/tmp/g4_check.py` compares show_005 against
`.agent/tmp/g4-snapshot/trace-baseline.json`.
