# 124 — the unshipped half is deleted

## Why this exists

`docs/design/agent-first-surface.md` measured, on 2026-08-28, which of two facades the product
actually runs on. A PEP 669 line-level trace of a complete CLI journey found that
`vqapr/project.py`, `vqapr/simulation.py`, `vqapr/materialization.py`, `vqapr/venues.py` and the
`_internal` bridges beneath them executed **zero lines**, and were exercised only by the tests
written for them. The ruling named that inversion and then froze the cluster rather than removing
it, on the grounds that deletion was `G008` and `G008` was gated.

Two things had to be true before this could be discharged, and by 2026-09-01 both were.

**The freeze's no-deletion half was already retired.** The owner ruling of 2026-09-01 — *"필요하면
고치는건데 merge 할 때 어떤 것이 correct 한지 검토해야지"* — replaced the standing prohibition with
merge review.

**`G008`'s gates never covered this deletion.** `gjc-handoff/session-03/goals.json` states `G008`
as *"Hard-remove the old qlibx API"*: relocate `flow/`, `data/`, `account/` and the rest beneath
`vqapr._internal`, delete `vqapr.public`, and cut a breaking `0.2.0a1`. That is the opposite
direction, written on 2026-08-24 — four days before the trace that inverted the finding. Its two
gates protect a release rollback and a parity baseline; this change cuts no release and touches
neither `vqapr.public` nor the CLI. `G010` — *"migrate the 9 showcase run.py files onto
`Project.register` / `Project.materialize` / `Project.simulate`"* — is obsolete for the same
reason, and is discharged here in the opposite direction.

## What changed

**Deleted (13 modules, 4,001 lines under `src/`):**

| | |
|---|---|
| `vqapr/project.py` | 1,036 — the `Project` facade `vqapr.open()` returned |
| `vqapr/simulation.py` | 547 — the `Simulation`/`Schedule`/`Cadence` declaration types |
| `vqapr/venues.py` | 206 — `Academic`/`Listing`/`VenueCost` |
| `vqapr/materialization.py` | 161 — no `import` statement anywhere in `src/` |
| `vqapr/extension/identity.py` | 282 — importers were two deleted bridges |
| `vqapr/_internal/{catalog,catalog_store}.py` | 498 — the content-addressed catalog |
| `vqapr/_internal/objects.py` | 107 — its object store |
| `vqapr/_internal/{constraint,registration,run,schedule,venue}_bridge.py` | 954 |

`vqapr/__init__.py` loses `open()` and three of its four capability names. `authoring` remains: a
registered StrategyModel may be written against it, and `extension/loading.py` adapts it onto the
engine contract at load time.

**Trimmed, not deleted:** `_internal/pit_bridge.py` loses `CatalogResolver` (read through the
deleted catalog) and `StoreResolver` — which claimed in its own docstring to be *"what this module
fills in production"* and had no importer anywhere in `src/`. The three functions
`strategy_bridge` actually calls survive.

**Kept deliberately:** `_internal/{atomic,filelock}.py`, `_internal/pit_bridge.py`,
`_internal/strategy_bridge.py`, `_internal/models/agent_first.py`, `vqapr/authoring.py` and
`agent/sample/` are all on live paths — the first two under `workspace.py` and `run_records.py`,
the next three under `extension/loading.py`, and `agent/sample/journey.py` as the fixture
`tests/extension/test_scaffold_runs_unedited.py` and `tests/flow/test_run_freezes_its_record.py`
drive the shipped scaffold and run-record paths with.

**Three showcases moved onto `vqapr.public`**, which is what made the deletion possible: they were
the cluster's only consumers outside `tests/`.

- `show_001_execution_input_registration` — explicit `register_dataset` /
  `register_execution_input` / `register_component` / `register_agenda`, then `preflight_run` +
  `run`. Its authored `ShowcaseStrategy` now declares the dataset read the loader requires, and
  the decision is conditioned on that read rather than declaring one it ignores. Its exchange
  became a registered component. The invalid-execution-input claim moved from
  `Project.simulate` to `register_execution_input`, which is where the refusal actually belongs.
- `show_002_datamodel_materialization` — its three DataModels moved from `vqapr.authoring` to
  `vqapr.public`, because `load_data_model` adapts nothing and the authoring `DataModel` has no
  path through the CLI at all. The `_flatten_persisted` helper is gone: a materialized parquet is
  already flat.
- `show_004_krx_execution_profile` — **gained a claim rather than losing one.** Its module
  docstring said *"No `venues.Krx` exists on the supported surface"* and reproduced KRX economics
  on an academic venue with hand-declared `VenueCost` values. `vqapr.public` ships `KrxExchange`,
  so both profiles are now the real engine classes and the documented substitution is gone. It
  also loses `_register_momentum_score`, a 40-line bridge that re-exported a materialized dataset
  as a physical parquet because `Project.materialize` persisted only into the catalog;
  `flow/materialize.py` registers its own output.

## Validation

- `uv run pytest tests/ -q` — **1275 passed**, 14 deselected. Was 1279 before, with 24 files and
  ~4,500 lines of cluster-only tests removed and the survivors repaired.
- `uv run pytest tests/ -q -m ""` — **1289 passed**, 0 failed, 529s. The thirteen slow
  end-to-end journeys are the difference, and they are what actually exercises run assembly, the
  record shape and the emitted scaffolds; the manifest requires them before handoff for exactly
  the kind of change this is.
- `uv run ruff check src/` — clean. `tests/` carries nine pre-existing findings the manifest does
  not gate; the count is unchanged by this record.
- All three ported showcases run and produce their evidence. `show_004`'s numbers reproduce its
  committed README **exactly** — final NAV 1,895,960,196.32 / 1,865,987,436.94, 80 / 77 dealt
  fills, 12.55bp effective cost — which is the strongest available check that the port is faithful
  rather than merely green.

**Six test files were repaired rather than deleted**, because they test shipped behaviour and
only reached it through the deleted facade:

- `tests/flow/test_valuation_clock.py` — six tests of `flow/simulation.py`'s independent valuation
  clock, driven through `project.run_completed`. Its subprocess runner moved onto `preflight_run` +
  `run`. Its authored strategy gained the dataset declaration the loader requires, and the fixture
  gained a 07:00-stamped observation parquet so the 08:00 callback has something to read — the
  15:30 execution stamps are untouched, which is the separation the file exists to measure.
- `tests/internal/test_one_mutex_two_callers.py` → `test_the_workspace_mutex.py`. Its subject was
  that two exclusive-lock sites had drifted apart; one of them was the catalog. There is one now.
- `tests/internal/test_one_durable_write.py` — two of its four "former call site" cases were the
  catalog and the object store.
- `tests/internal/test_pit_bridge.py` — the four resolver tests went with the resolvers.
- Three boundary tests hold counts and exemption lists as their subject and each named, in its own
  failure message, what to update in the same commit: the deferred-import ceiling (99 → 44, with
  `JUSTIFIED` now empty), the `_internal` importer record, and the facade tripwire (11 → 5).

`tests/boundaries/test_the_frozen_cluster_gains_no_callers.py` is deleted. It watched four modules
that no longer exist, so it passes vacuously and would keep passing forever.

## What this did not do

**The remaining facade violation is `_internal/strategy_bridge.py`, and it is not a leftover.** It
was always the one entry in `EXPIRING_AT_G008` with a live importer outside the cluster, so no
amount of deleting the cluster could close it. Its exemption is re-tied, in
`test_the_facade_is_not_reached_up_to.py`, to the file it lives in rather than to an obsolete
goal: it expires when the two authoring contracts converge and there is nothing left to translate.

That convergence is the next decision, and it is a real one. `vqapr.authoring` (945 lines) defines
a second `DataModel`, `StrategyModel`, `Constraint`, `RowsLookback`, `CalendarLookback`,
`ConstraintBounds` and `ConstraintFinding` alongside the engine's own. Only the StrategyModel half
is reachable from the CLI — through `_adapt_authored_strategy` → `AdaptedStrategy` →
`agent_first` + `pit_bridge`, about 1,100 lines of adapter. The DataModel and Constraint halves
have no execution path at all: `load_data_model` and `load_constraint` adapt nothing.

Which contract survives is not a cleanup question. Real research code writes strategies against
`authoring` and datamodels against `public`, so either direction moves someone's files.

**The deletion surfaced new dead code** that the cluster was the only caller of. `uv run vulture`
now reports fifteen names, including `workspace_codec._encode_requirement` /
`_decode_requirement` and `COMPONENT_REGISTER_STAGE` in two modules. Each needs a ruling and none
is urgent; `deadcode` is declared in the manifest as not a gate for exactly this reason.
