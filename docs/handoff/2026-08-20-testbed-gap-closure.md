# Handoff — closing the gaps the testbed exposed

Status: in_progress
Branch: `jaepil-develop` · last commit `85649a5` · **tree is green: 586 passed, ruff clean**
**Nothing is uncommitted.** B7, A3 and B8 are closed. **B8 was withdrawn as a false finding** —
read the correction below before acting on any earlier copy of it.

Written because the session kept dropping mid-task. Everything below is verified, not remembered.

---

## Read this first: three false claims, and one of them was mine

**B8 — "a registered dataset cannot be used as an execution table … 3,302,492 rows duplicated on
disk. Largest single waste left." This was wrong, and I wrote it.** The duplication is the design,
not waste.

The column renaming is not the reason for the copy. `ExecutionTableSpec` takes every physical
column name as a mapping — `trade_at_field`, `instrument_field`, `price_fields` can all point at
whatever the observation parquet already calls them. Only `is_tradable_field` needs a column that
is genuinely absent, which is what forces a second file.

And it should force one. **`trade_at` is a different instant from `available_at`.** Sharing one
physical file makes the moment a price was *observable* and the moment it was *executable* the same
value by construction, which is exactly the conflation the framework exists to prevent. Making
`is_tradable_field` optional was considered and **rejected**: it would leave a user with no way to
declare a halt at all, against record 013.

What the investigation did turn up is a real defect, now fixed in `85649a5` — see below.

## Two review claims are also false

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

## B7 is finished — `e5ce32e`

`rescale(weights, *, long, short, grid=None)`. The version was **not** bumped, as asked.

What landed beyond the four steps this handoff originally listed: two refusals the grid makes
necessary. A budget not itself on the grid (weights on `0.01` cannot sum to `1.005`, and the
residual would silently land off-grid — the exact property the argument exists to guarantee), and a
grid finer than `QUANTUM`, which `optimize` already refuses for the same reason. Quantization pins
`ROUND_HALF_EVEN` instead of reading the ambient decimal context, so the module stays context
independent like the rest of `weighting.py`.

Ten tests. The load-bearing one is
`test_quantizing_after_rescale_is_what_the_grid_argument_replaces`: it reproduces the caller-side
bug — the total falling to `0.99` after quantizing — then shows the same call with `grid=` holding
both properties at once. Full reasoning in `docs/implementations/028-a-gridded-book-still-adds-up.md`.

### What B7 actually was, because the review misdescribed it

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
| `e5ce32e` | `rescale(..., grid=)` | the bug is reproduced in-test: three equal names quantized after rescaling sum to `0.99`, with `grid=` they sum to `1.00` and stay on the grid |
| `85649a5` | B8 investigation — `preflight.execution.missing` | preflight promised a "run-ready" `FrozenRun` that `run()` always rejects; `_validate_instrument_universe` and `_validate_initial_account` were **skipped entirely** when no exchange was declared |
| `43ca56f` | A3 — CLI answers in one shape, and `run` is proven to run | `vqapr run spec.yaml` completes: `occurrences=12, account_version=7`. Two defects found by walking it: argparse escaping the envelope, and `run` checking 3 of the 8 keys it needs |

Earlier in the same session: `f2f4013`…`c11d2e3` (hot-path performance, execution-priced valuation,
account history retention, fill-journal publication). Those are described in
`docs/implementations/021`–`027`.

---

## A3 is finished — `43ca56f`

The answer to *"are we actually registering and running like a real user?"* was **no**, and now it
is yes for the CLI: `tests/cli/test_commands.py` drives `new` → `register` → `list` → `run` through
`main(argv)` and reads the JSON an agent would get. `run` completes with `occurrences=12,
account_version=7` — both pinned, because `> 0` is also true of a run that did nothing.

Walking it found two real defects, described in `docs/implementations/029-the-cli-answers-in-one-shape.md`:

1. **argparse bypassed the envelope.** `parse_args` raises `SystemExit`, a `BaseException`, so it
   passed through `except Exception`. Every mistyped command answered `exit=2` with an **empty
   stdout** — the one reply an agent cannot parse.
2. **`run` checked 3 of the 8 keys it cannot run without.** The other five surfaced from inside the
   framework as `stage: "unhandled"`, which reads as "the framework broke" when the truth was "your
   spec is incomplete".

### Still open on the CLI, and it is a surface decision, not a bug

**`register` takes 2 kinds; `list` reads 8.** A user can register `datamodel|strategy` and nothing
else — datasets, sources, agendas, execution inputs and the three configs have no CLI path at all.
So a runnable workspace **cannot be reached through the CLI alone**; the e2e fixture registers them
through the library, which is precisely the gap. Closing it means designing a declaration surface
for five more kinds, so it is the owner's call, not a fix to ride along.

---

## Remaining work, in the order I would take it

**`register --dry-run` does not exist.** `dry-run`/`dry_run` appears **0 times** in `src/`
(re-verified at `43ca56f`). If it is wanted it is new work, and it belongs after the conformance
suite, which is what a dry run would check beyond the fingerprint.

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
uv run pytest -q                      # 586 passed
uv run ruff check src/ tests/         # clean
uv run python showcases/show_00N_*/run.py    # all eight run; 005 and 007 are the sharp ones
```

G-4 style result invariance: `.agent/tmp/g4_check.py` compares show_005 against
`.agent/tmp/g4-snapshot/trace-baseline.json`. Currently **64 fields identical**.

**The G-4 baseline was stale and has been re-cut.** It was captured before `c11d2e3` and had been
failing on `recorder.defaults.account` (`21` → `101`) ever since — not a regression, but the
documented widening from record 026: one row per held instrument per occurrence instead of one row
per occurrence. It was re-cut from the committed tree *before* the B7 change, so the pass above is
real evidence that `grid=None` moves nothing, not a reset. A known-false failure in a check this
handoff tells you to run is worse than no check.

**Two `ruff` gates, not one.** `ruff check src/ tests/` is the declared gate and is clean.
`ruff format --check` reports one pre-existing block in `weighting.py:155` (`sized = {...}`) that is
also unformatted on `HEAD~`. Left alone deliberately: it is nobody's change, and reformatting it
would put an unrelated hunk in a behaviour commit.
