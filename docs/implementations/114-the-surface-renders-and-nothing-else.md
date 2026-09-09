# 114 — The surface renders and nothing else

**Closes:** Step 9 of the approved structural plan, and the second half of `docs/issues/archive/030`.
**Branch:** `step-09-the-surface-renders-and-nothing-else`.

## Part one — three pieces of domain logic leave the CLI

`docs/vqapr-architecture.md` §10.2 makes the CLI a product surface, not a layer. Three functions
contradicted that, and one of them was known to at the time it was written.

**`_fill_summary` → `analysis/execution.py` as `fill_summary`.** It was added to `cli/run.py` under
time pressure in the 0.2.0a2 batch and acknowledged as misplaced in its own issue. It is not
rendering: it is the aggregate `docs/issues/archive/039` shows nobody could compute by hand in time — a
3.1% zero-dealt rate against a 1.2% baseline, reachable only by reading 47,318 rows.

**It now takes rows rather than a `SimulationResult`**, which is the part that matters. That makes
it a pure function of data, testable with a list of dicts, with no `flow` import — and therefore no
repeat of the inversion record `113` had to undo. The tests got simpler as a direct result:
`fill_summary(_result(("vqapr.fill", rows)))` became `fill_summary(rows)`.

**`_recorded` and `_tables_declared` → `flow/reporting.py`.** These take `SimulationResult` and
`StoreSpec`, both `flow` types. Record `113` paid for the lesson that a module's home follows its
dependencies rather than a plan's suggestion, so they go beside `flow/records.py` rather than into
`evidence/`, and `FILL_TABLE`/`FRAMEWORK_TABLES` travel with them.

**`_lookback_arguments` → `authoring_lookback.py` as `lookback_declaration`.** A domain rule wearing
argparse clothes: the strategy scaffold takes rows only, because its emitted `len(values) >=
LOOKBACK` guard counts observations and a calendar window would make it count observations against a
number of days (`docs/issues/archive/033`). It now takes `kind`, `rows` and `calendar` rather than a
`Namespace`, so a second surface that scaffolds a component can apply the same rule without building
an argparse object to do it.

`cli/run.py` 806 → 715. `cli/new.py` 906 → 867.

## Part two — `cli.usage` is inside the six-field guarantee

`docs/issues/archive/030` left this open explicitly, as *"a decision, not an omission"*. The reporter could
not tell whether it was issue 016 and said so.

**The facts.** `SKILL.md` guarantees, unconditionally: *"Every entry carries `code`, `source`,
`requirement`, `observed`, `fix` and `explain`"*, and tells the reader to **read `fix` first**. A
`cli.usage.rejected` refusal carried three of the six, and no `fix` — on the first refusal a new
user will ever see.

And the repository had already answered, in a test:
`test_list_unknown_kind_is_a_usage_shape_with_no_failure_fields_by_design`, whose stated reasoning
was that usage rejections *"never claimed the six-field contract in the first place"*.

**That reasoning was checkable and false.** `SKILL.md` claims it with no exception. The document and
the test disagreed, and issue 030 reopened it precisely so the answer would be ruled rather than
left to whichever a reader found first.

**The ruling: `cli.usage` is inside the guarantee.** An exception carved at the most common entry
point is not an exception; it is the guarantee not holding where it is needed most. The three
missing keys cost nothing, and `fix` is genuinely actionable — `run \`<prog> --help\` to see the
arguments this command accepts`.

`source` and `explain` are `null` rather than absent: argparse rejected the command line, so there
is no file to point at and no package concept to explain. `SKILL.md` already permitted a null
location and now names this case. **`family` stays `None`** — a different question, unchanged, and
correctly so: `FailureFamily` is a closed set of *package* stages and this failure reached none of
them.

The test that asserted the opposite was **rewritten, not deleted**, and carries the reasoning for
the reversal so the next reader sees a ruling rather than a flip. It now checks all six keys are
present, that `fix` is non-empty, names an action, and differs from `requirement`.

## Validation

| check | result |
|---|---|
| `cli/run.py` | 806 → **715 lines** |
| `cli/new.py` | 906 → **867 lines** |
| `tests/qa/test_refusal_envelope_six_fields.py` | 9 passed |
| fast suite | **1475 passed**, 14 deselected |
| **`-m slow -rs`** | **14 of 14 passed**, no skip lines |
| `uv run ruff check src/` | All checks passed |
| refusal-code baseline | **no drift** — 0 added, 0 removed |

The baseline not moving is worth stating: three functions changed module and the refusal inventory
did not, because the refusals in them are raised as `InputError`, which the static pass folds by
call site rather than by defining module. `fill_summary` and `tables_declared` raise nothing.

## Correction, record `115` follow-up

This record originally stated `cli/run.py` 806 → **712** and `cli/new.py` 906 → **866**. Both
were wrong: the measured values are **715** and **867**, verified by
`git show 7b5f9591:<path> | wc -l` against `git show d6d3ae51:<path> | wc -l`. Three lines and
one line, and in the direction that made the reduction look slightly larger than it was.

Small, and worth correcting anyway. The house rule is measured numbers rather than estimates,
and a wrong exact number is worse than a rounded one because it invites the trust an exact
number earns. Found by the AI-slop lane of the VB002 cohort gate, which recomputed every
numeric claim in records `111`–`115` against git history; these two were the only ones that
did not match.
