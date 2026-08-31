# 105 — The configured gate was open, and two metrics were not metrics

**Closes:** Step 1 of the approved structural plan.
**Branch:** `step-01-the-configured-gate-is-open`.

Three things, none of them behavioural, all of them about instruments the following fifteen steps
depend on being trustworthy.

## (a) A configured gate that nobody ran

`pyproject.toml` selects `["E", "F", "I", "UP", "B", "SIM", "RUF"]` and the tree did not pass them.
Seven findings stood, and `.agent/project.yaml:commands` declared `install`, `import`, `build`,
`test` and `test_all` — **no `lint`**. A gate that is configured and uninvoked is not a gate; it is a
setting.

Four cleared under `ruff --fix`. The remaining three each needed a judgement:

- **`cli/new.py:743` (E501)** — the line is `_INSTRUMENTS_TEMPLATE = '''"""Declare what each
  instrument in your universe IS, then export the tables.`, and everything after `'''` is **emitted
  scaffold text**. Rewrapping the sentence would change what `vqapr new instruments` writes into a
  user's project. Fixed with the backslash continuation the file already uses four times
  (`_DATASET_TEMPLATE = """\`, `:70`, `:110`, `:141`, `:807`), which shortens the *source* line and
  emits byte-identical output. `tests/cli/test_new_instruments.py` passes unchanged, which is the
  proof.
- **`flow/simulation.py:1700` (E501)** — a three-clause `if`. Wrapped across four lines. The first
  attempt hoisted the third clause into a local, which **changed short-circuit order**: the set
  membership would have been evaluated before the `marked_at is not None` guard. Harmless in fact
  (`None in set` is legal), but Step 1 owes zero behavioural surface, so it was redone as pure
  reformatting with the clause order and short-circuit semantics untouched.
- **`public.py:144` (RUF022)** — `__all__` had `InstrumentRoster`, `build_roster` and `export_roster`
  appended after `instruments` rather than in sorted position. Same names, same set, three moved
  lines. `tests/boundaries/test_public.py` pins `__all__` as an exact tuple and was updated in the
  same commit.

`lint: uv run ruff check src/` is now declared. **Errors 7 → 0.**

## (b) A gate that fired on the one event it was never meant to catch

`tests/characterization/test_refusal_codes.py` compared `{(code, file, line)}` sets against
`refusal_codes.baseline.json`. The line number is the one component that moves for reasons unrelated
to what the gate measures: a docstring edited three functions above a `Failure.bounded` call shifts
it.

**Measured cost:** the baseline was regenerated **four times in one week**, and every one of those
diffs was a pure line shift — no code added, removed or renamed. A gate that fires that often on
non-events is one people learn to regenerate past. Fifteen further steps in this campaign move call
sites between and within modules; `flow/judgments.py` alone contributes 19 static entries.

The primary assertion is now keyed on `{(code, file)}`. What it still catches is everything it
exists for — a code **added**, **removed**, **renamed**, or **moved to a different file**, the last
being the one that matters most while relocating call sites. Only movement *within* one file stops
failing.

Line data is not discarded. It stays in the JSON, and a new test
`test_line_drift_is_reported_and_not_fatal` prints the drift with no assertion on it — deliberately,
because the moment it acquires one it becomes the gate this step removed.

**Demonstrated, not asserted.** This step's own `__all__` reorder shifted a refusal call site:

```
refusal-code line drift (1 call site(s), not a failure):
  src/vqapr/public.py:561 -> 562  run.roster.unreadable
```

The suite passed and `refusal_codes.baseline.json` was **never regenerated** — `git diff --stat` on
it is empty across this whole branch. Under the old key that same edit was a hard failure requiring
a regeneration commit. That is the defect, reproduced and closed inside the step that closes it.

`test_regenerating_is_opt_in_only` survives untouched: a gate that rewrites its own oracle is not a
gate, and that property was not traded away for this one.

## (c) The half of the freeze nothing watched

`docs/design/agent-first-surface.md` freezes five things — `project.py`, `simulation.py`,
`materialization.py`, `venues.py`, `vqapr.open` — on three counts, the first being **no new
callers**. Its own section "What the tripwire does not watch" says so plainly:

> The tripwire counts importers of `vqapr.public`, which is not one of the five frozen modules. […]
> A reader who runs the only command given here, sees 12, and concludes the whole freeze is intact
> would be reading a number that never looked.

That is what shipped. `test_the_facade_is_not_reached_up_to.py` watches the facade; **nothing watched
the five.** The document records their 2026-08-28 state so "a later reader can tell an inherited edge
from a new one" — a comparison no test performed.

`tests/boundaries/test_the_frozen_cluster_gains_no_callers.py` performs it. AST walk over `src/`,
pinning the three inherited edges, measured now and matching the document's own record:

```
src/vqapr/__init__.py            -> vqapr.project      (vqapr.open itself)
src/vqapr/_internal/venue_bridge.py -> vqapr.venues    (itself inside the frozen cluster)
src/vqapr/project.py             -> vqapr.simulation
```

The prohibition is on **adding**, so an added edge fails and a removed one is reported rather than
blocked — a removal is the direction `G008` eventually goes and cannot be a failure, but it must not
be silent either. `materialization.py` gets its own assertion, because the document singles it out as
having **no import statement anywhere in `src/`**; folding it into the edge set would let a first
importer pass as one new edge among several.

**Proven to fail on the breach.** A `from vqapr.simulation import Cadence` was temporarily injected
into `cli/list_.py`; the test failed naming the offending edge and quoting the ruling's own remedy.
Then reverted, with `git diff --stat` confirming a clean restore.

**The sanctioned exception is named rather than left to be argued.** Step 14 deletes
`_bridge_catalog_datasets` from `project.py` under an explicit owner ruling that removing dead wiring
is not "growth". That edit does not touch this test — it removes imports of `vqapr._internal.catalog*`
from *inside* `project.py`, which is not an edge into any of the five.

## The trajectory that is recorded and not asserted

`test_the_facade_is_not_reached_up_to.py`'s count assertion stays at **12**. Its docstring now
carries where the number goes — 12 today, **10** after the authoring-convergence step removes the
facade import from the two shipped-path bridges, **6** only at `G008` — and asserts none of it.

Encoding 6 as an acceptance would fail the suite for every commit between here and `G008`. And `0`
was never reachable: it came from a *string* count of 18 that the ruling itself repudiates. The step
that moves the number is the step that updates this assertion and the ruling's list in one commit.

## Validation

| check | result |
|---|---|
| `uv run ruff check src/` | **All checks passed** (was 7 errors) |
| `.agent/project.yaml` | `lint` command declared |
| `tests/boundaries/` | 35 passed (was 32; +3 frozen-cluster tests) |
| `tests/characterization/` | 77 passed (was 76; +1 drift reporter) |
| `tests/cli/test_new_instruments.py` | 10 passed — emitted scaffold bytes unchanged |
| fast suite | **1459 passed**, 14 deselected (baseline 1455 + 4 new tests) |
| `refusal_codes.baseline.json` | **not regenerated** — `git diff --stat` empty |

No behavioural change: the only `src/` edits are a backslash continuation that emits identical
bytes, an `if` wrapped across four lines with identical short-circuit order, and three `__all__`
entries moved into sorted position.
