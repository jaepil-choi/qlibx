# 087 — `run` makes the judgments `check` makes

**Closes:** `docs/issues/archive/015-run-does-not-make-the-judgments-check-makes.md`.
**Branches:** `fix/015a-extract-judgments` (the move) and `fix/015b-run-refuses` (the refusal). Both
land in this record, because the move exists only to make the refusal possible and neither is
independently meaningful.
**Plan:** `.gjc/_session-01a05036-1aa4-7667-ad30-97381fbe23bd/plans/ralplan/campaign-015-027-r2/pending-approval.md`
(sha256 `e97e18116e6e1f15c3075a3fa1e523ca618b518243da5bb44595185b9c803f59`).

## Why this change exists

`check` runs eight judgments; `run` ran none of them. Not a missed call site — `_judgments` was
modelled as a `check`-verb concern and `run.py` contained no reference to it at all. A spec with a
real look-ahead (a fill at 15:30 with 85 decisions at or after it) was refused by `check` and run to
completion by `run`, which then wrote a permanent record that `vqapr list runs` shows beside two
legitimate runs with nothing marking it. There is no command that deletes a run, so the artifact is
permanent, and a reader cannot tell it apart from a good one.

The reporter's own summary of what they could not say: *"`check` and `run` enforce the same rules, so
a green `run` means what a green `check` means."*

## The decision, and who made it

Three options were on the table (`docs/issues/archive/015`, "The decision this needs"). The issue file and
the planning pass both recommended option 2 — perform the judgments, record the verdict on the
artifact, refuse unless a flag says otherwise.

**The user chose option 1: `run` performs the judgments and refuses. No escape flag. No verdict
recorded on the artifact.**

Their reasoning, adopted: under unconditional refusal no invalid record can be produced, so there is
no artifact left needing a verdict field. The issue file's "whichever is chosen, the run record must
carry the verdict" is a requirement conditional on an escape hatch existing; removing the hatch
dissolves it rather than working around it.

A consequence recorded in the plan's favour: `docs/issues/archive/009`'s "What not to do" warns against *"a
refusal the caller must pass a flag to bypass, on an event that is ordinary"*. Option 2 would have
had exactly that shape. Option 1 is more consistent with this codebase's own governing precedent than
the option both the issue file and the planner recommended.

**What this costs, stated plainly:** a deliberately-invalid run is no longer producible as evidence —
the exact artifact that made issue 015 provable cannot be made again. And `run` can now fail after
freezing a spec. Both were accepted knowingly.

## Step zero — the `develop` baseline

Every gate in this campaign reads against this measurement. Captured on `develop@8d040b9e`, clean
tree, before any branch was cut.

| suite | command | result |
|---|---|---|
| full | `uv run pytest tests/ -q -m ""` | **1350 passed**, 0 failed, 412.79s |
| slow only | `uv run pytest tests/ -q -m "slow"` | **14 passed**, 1336 deselected, 325.17s |
| fast (default) | `uv run pytest tests/ -q` | **1336 passed**, 14 deselected, 86.76s |

**The slow ran/skip profile, which is the part that makes the number comparable.** All **14 of 14**
slow marks **ran**; **none skipped**. Seven of them (`tests/agent/test_sample_panel.py`) are
`real_data`-gated at :25 and skip at :27-28 when the warehouse is unprovisioned — on this machine the
warehouse *is* provisioned, so "green" here means the strong sense of green. A later `test_all` that
reports 1350 passed with some of those seven skipped is **not** the same result and must not be
compared to this one as if it were.

The 14 marks live in exactly four files, located by the marker rather than by directory name:
`tests/agent/test_sample_panel.py` (7), `tests/flow/test_run_freezes_its_record.py` (5),
`tests/cli/test_krx_cost_journey.py` (1), `tests/extension/test_scaffold_runs_unedited.py` (1).
`tests/acceptance/` contains **zero** slow marks and runs entirely in the fast suite — the campaign's
first planning error was assuming otherwise from the directory name.

Only two slow tests reach `cli/run.py:run()`: `test_krx_cost_journey.py` and
`test_scaffold_runs_unedited.py`. They are the entire slow-side exposure of the 015b refusal, and
both pass the judgments by construction today.

## Decision R1 — `tables_declared`, settled here for the 024 branch

The campaign deferred one product question to whoever read this code first: does a run that declared
a diagnostic table report it in `tables_declared`, or does the field go away? Settled by reading
`cli/run.py:454` and its neighbourhood, which is what the deferral was for.

**The empty list is not a bug, and the field is not lying.** There are two unrelated declaration
surfaces, and the envelope reads one of them:

| surface | declared where | read by |
|---|---|---|
| `store.tables` | the run spec's `store:` section (`flow/store_spec.py:43`, parsed at :72-79) | `tables_declared` (`cli/run.py:454`) |
| `StrategyModel.diagnostics()` | the component itself (`_internal/models/agent_first.py:466`) | `show run`'s `tables` (`public.py:642-651`, counting what was actually recorded) |

The journey declared `ff3.formation` through the second surface and read the first. `store.tables`
was genuinely empty, so `tables_declared: []` was an accurate answer to a question the reader was
not asking. `vqapr show run` reported 42 rows because it reads what was written, not what the spec's
`store:` section declared.

**Decision: keep the field, and make it report both surfaces.** Rejected removing it — a reader who
wants to know what a run declared has nowhere else to look, and `show run`'s `tables` answers a
different question (what got written, which is empty for a table declared but never formed).

The binding constraint from the plan is satisfied by construction: the envelope and `show run` do
not disagree once `tables_declared` names the union of both declaration surfaces, because the two
are then reporting the same declared set from different angles — declared versus recorded — rather
than one silently reading a narrower source than its name implies.

The deliberate comment at `cli/run.py:441-453` stays true and is NOT being overridden: it refuses to
emit a `publishes`-shaped claim, i.e. a machine-readable assertion that a *dataset* exists when
`list datasets` shows none. Naming a declared diagnostic table is not that claim. The 024 branch
must preserve that distinction in its wording, or it will re-open the thing that comment closed.

## What changed — `fix/015a-extract-judgments` (the move)

A pure relocation with no behaviour change, done first so the refusal branch has a clean interface
to consume and so a test failure there means something about the refusal rather than about the move.

**Why the move was needed at all.** `cli/check.py` imported `cli/run.py` for the run-spec vocabulary
(`MATERIALIZATION`, `spec_kind`, `require_declared_keys`). Calling the judgments from `run` would
have completed a cycle: `cli.run -> flow.judgments -> cli.run`. So the vocabulary moved below both
verbs and the edge disappeared instead of being routed around.

- **`src/vqapr/flow/run_spec.py` (new).** `SIMULATION`, `MATERIALIZATION` and `_REQUIRED_BY_KIND`,
  moved verbatim from `cli/run.py`. **Data only.** `spec_kind`, `require_declared_keys` and
  `_require_nested_keys` deliberately stayed in `cli/run.py`, because each raises `InputError` from
  `cli.inputs`; bringing them down would have put a `cli` import under `flow/` — the same layering
  violation in the quieter direction, an import edge rather than a cycle, so nothing would have
  crashed to reveal it.
- **`src/vqapr/flow/judgments.py` (new).** Both judgment functions and their six helpers, moved as a
  contiguous block. Two deliberate changes to the moved code:
  - `_materialization_judgments` → `materialization_judgments`, taking `kind_spelling` as an injected
    callable. Its one use of `cli_kind` (`check.py:319` before the move) sat *inside* the function
    that moves, so leaving `cli_kind` in the CLI required injecting it. Restating `AUTHORED_KINDS`
    was not an option — `cli/register.py:1041-1042` forbids exactly that.
  - `_judgments` → `judgments`, now RETURNING `(failures, blocked)` instead of mutating a
    caller-supplied `blocked` list. The out-parameter was the reason this contract was easy to
    overlook: a caller that forgets it reports a spec whose judgment could not answer as clean,
    which is issue 015's divergence reproduced one layer down.
- **`src/vqapr/cli/check.py`.** Imports the two functions from their new home; passes `cli_kind` in;
  extends `blocked` from the returned list **before** the `continue`, because the phase loop compares
  `len(blocked)` against `blocked_before` further down to decide whether the phase may be reported as
  passed. Three imports (`Mapping`, `datetime`, `get_close_matches`) went dead here and were removed;
  two others (`load_exchange`, `load_strategy_model`) moved with the judgments.
- **`src/vqapr/cli/run.py`.** Sources the three constants from `flow/run_spec.py` rather than
  defining them. 38 lines of relocated definitions removed.
- **Five test sites** updated to the new module: two monkeypatch sites that rebind `_judge_universe`
  (`tests/cli/test_check.py:256-263`, `tests/qa/test_check_collects.py:188-193`) and three direct
  private imports (`_judge_period` twice, `_judge_datasets_and_fields`, `_judge_weights`). They broke
  on the MOVE, not on the signature change — `judgments` and `materialization_judgments` have exactly
  one caller each and no test calls either directly.
- **`tests/characterization/refusal_codes.baseline.json`** regenerated.

## Validation — `fix/015a-extract-judgments`

**Gate:** fast suite plus the four named files. No `test_all`: there is no behaviour change, and the
two slow tests that reach `cli/run.py:run()` cannot observe a relocation.

| check | result |
|---|---|
| `tests/cli/test_check.py`, `tests/qa/test_check_collects.py`, `tests/qa/test_check_does_not_mutate.py` | 23 passed |
| `tests/characterization/test_refusal_codes.py` | 6 passed after regeneration |
| full fast suite | **1336 passed, 14 deselected**, 89.32s — identical to the step-zero baseline |
| `import vqapr.cli.run`, `import vqapr.cli.check`, `import vqapr.flow.judgments`, `import vqapr.flow.run_spec` | all succeed |
| `grep -rn "from vqapr.cli\|import vqapr.cli" src/vqapr/flow/` | **0 matches** — the branch's own criterion |

**The baseline diff shape**, verified rather than hand-counted — three readers of this campaign
produced three different totals (17, 19, 21) for this one fact, which is why the criterion is a shape
and not a number:

- codes added: **none**
- codes removed: **none**
- relocated `cli/check.py` → `flow/judgments.py`: every `check.*` entry, and nothing landed anywhere else
- still in `cli/check.py`: exactly `run.check.declaration_invalid` and `run.check.preflight_refused`,
  which are raised by `check()` itself and correctly did not move

**Byte-identical observable output.** A probe ran `check` against three specs — a multi-defect spec,
a missing spec, and one with a judgment monkeypatched to raise — on a `develop@8d040b9e` worktree and
on this branch, using the suite's own workspace fixture so the judgments were actually reached.
After scrubbing absolute temp paths the two envelopes are **byte-for-byte identical**. The multi-defect
case produced four independent refusals (`check.period.uncovered`, `check.universe.absent`,
`check.weights.mode_conflict`, `workspace.component.lookup.missing`), confirming collection survived;
the blocked case recorded `{'check': 'universe', 'error_type': 'KeyError'}` with `ok: false` and
`judgments` absent from `passed`, confirming the returned-blocked contract behaves as the
out-parameter did.

## What changed — `fix/015b-run-refuses` (the refusal)

- **`_refuse_if_judged` in `src/vqapr/cli/run.py` (new).** Raises `VqaprError` at a new stage
  `run.judgments`, family `INTENT`, carrying the judgments' own `Failure` objects. Because the
  envelope is built from `VqaprError.as_dict`, every entry in `failures[]` already carries the six
  fields; nothing new had to be invented to satisfy that criterion.
- **The codes are `check`'s, not new ones.** A reader with handling for
  `check.execution.not_after_decision` gets the same code from both verbs. Re-coding into a `run.*`
  namespace would have renamed a defect the reader may already handle, which is the opposite of the
  parity being delivered.
- **Blocked counts as refused.** `judgments()` returns questions it could not ANSWER separately from
  questions it answered no to, and `check` treats both as not-ok. Refusing only on the answered-no
  list would have let a spec nothing was proven about run to completion — issue 015's divergence
  reproduced inside its own fix. A blocked judgment has no code of its own, so it gets
  **`run.check.judgment_blocked`**, in the existing `run.check.*` namespace, naming which judgment
  could not answer and why.
- **Two insertion points, not one.**
  - Simulation: after `StoreSpec.of`, before `preflight_run`. The refusal is about the spec rather
    than about the definition built from it, and it matches the order `check` asks in — judgments
    precede declaration and preflight.
  - Materialization: inside `_materialize`, **after** the `--run-id`/`--force` refusals. `run()`
    returns for this kind before `Workspace.open` is reached, and these judgments need a workspace,
    so one is opened there. Hoisting the open to the top of `run()` would have reported an
    unopenable workspace ahead of a misused flag, inverting an order those refusals were
    deliberately given. A materialization has no `RunDefinition`, so there is no declaration or
    preflight phase for it to sit before.
- **`cli_kind` is passed in** from `cli/run.py`. `cli/register.py` imports nothing from `cli/run.py`,
  so naming it there adds no cycle, and the judgments stay free of `cli`.
- **`_judge_period` enriched** (`flow/judgments.py`). A naive boundary used to reach `_timestamp` in
  `cli/run.py`, which named the missing UTC offset and showed a well-formed instant. The judgment
  now answers first, so it carries the same `examples` and the same "must include a UTC offset"
  requirement. Without this, the parity `run` gained would have been paid for with a vaguer message
  than the one it replaced.
- **`run --help`** (`cli/main.py`) now says `run` judges before it freezes, and points at `check` as
  the verb that collects every problem at once rather than refusing on the first set.

### One test changed, and why it is not a weakened gate

`tests/cli/test_commands.py::test_run_refuses_a_date_boundary_as_structured_cli_input` asserted
`stage == "cli.input"` and `code == "cli.input.value_invalid"`. It now asserts
`stage == "run.judgments"` and `code == "check.period.uncovered"`.

This is the change being delivered, not an accommodation to it: the same spec is now refused by the
same judgment `check` uses, which is the entire point. The assertions that protect the *reader* are
unchanged and still pass — `"UTC offset" in requirement`, and
`examples == ["2024-01-02T00:00:00+09:00"]`. The refusal moved; the information did not shrink.

## Validation — `fix/015b-run-refuses`

**Gate:** fast suite (load-bearing `tests/cli/test_commands.py`) plus the five named files, plus
`test_all` for the two slow tests that reach `cli/run.py:run()`.

| check | result |
|---|---|
| the six named gate files | 63 passed |
| `tests/cli/test_run_makes_the_judgments_check_makes.py` (new) | 6 passed |
| `tests/characterization/test_refusal_codes.py` | 6 passed after regeneration |
| **full suite, all marks** | **1357 passed, 0 failed**, 532.03s |
| slow-only | **14 passed**, 1343 deselected, 446.23s |
| `test_krx_cost_journey.py` + `test_scaffold_runs_unedited.py` | 2 passed |

**Triage of newly-refusing tests, as D3 requires: there are none.** The baseline was 1350 passed;
this is 1357, and the difference is exactly the six new acceptance tests plus the one existing test
whose stage/code assertions were updated above. **No journey newly refuses.** The escalation gate in
the plan — stop and report if more than a couple of journeys refuse — was never approached, which
matches what the plan predicted from reading the fixtures: the two CLI-reaching slow tests pass the
judgments by construction, one asserting `check` ok is True on the identical spec immediately before
running it, the other using an agenda at 04:00 against a fill at 15:30.

**The slow ran/skip profile matches step zero**: 14 of 14 ran, none skipped, so the 1350 → 1357
comparison is between two measurements of the same thing.

### What the acceptance tests actually prove

`tests/cli/test_run_makes_the_judgments_check_makes.py` asserts the six properties the decision
requires, each as an observable result rather than an intention:

1. A spec `check` refuses is **not executed** by `run`, and the two refuse with overlapping codes.
2. The refusal carries all six envelope fields, in a `check.*` code, with `explain: run-precondition`.
3. A judgment that could not answer refuses the run, via `run.check.judgment_blocked`, naming the
   judgment and the exception type.
4. Independence survives: a spec with several defects yields several refusals in one call.
5. **A refused run writes no record** — `list runs` is byte-identical before and after. This is the
   one that matters most, because the permanent indistinguishable artifact was issue 015's actual
   harm.
6. **A spec `check` passes still runs.** Without this, a gate that refused everything would satisfy
   all five assertions above and destroy the product.
