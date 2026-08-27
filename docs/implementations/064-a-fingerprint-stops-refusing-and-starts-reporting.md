# 064 — A fingerprint stops refusing and starts reporting

Issue 009, Decisions 2 and 4, plus the repair path Decision 5 needs. Three milestones landed
together because the middle one is unusable without the last one: removing a refusal that names a
repair is only safe once the repair exists.

## What was wrong

Editing a registered component and re-running produced two refusals that pointed at each other.

```
vqapr run spec.yaml   -> component.load.fingerprint_drift
                         fix: "re-register the component"
vqapr register ...    -> workspace.component.register.conflict
                         fix: "register the changed source under a NEW component_id"
```

The load refusal named a repair the registration refusal forbade. `docs/implementations/057`
already named that shape: *"a refusal that names a repair it has itself disabled sends the reader
in a circle, which is worse than a generic error."*

The real cost was never one command. A new `component_id` needs a new `strategy_configs` binding
and a `spec.yaml` edit — four steps for a one-line change — and the workspace accumulated
`mom`, `mom-eb04...`, `mom-91c7...` for what is one strategy.

## What changed

**The two refusals are gone.** `loading.py` still computes the fingerprint on every load and
`register_component` still stores it; neither refuses on it now. Editing a registered component
and re-registering replaces it in place, under the same id.

**The run record states what actually loaded.** `source_digest` is now folded from the
as-loaded fingerprints of the strategy, the exchange and every constraint, computed at
`public.py` beside the loads that read them. `declared_digest` keeps the frozen declaration's
identity alongside it, so the pair stays legible: equal when nothing moved, different exactly
when it did. Without this the record would carry a digest describing bytes the run never
executed — a stale receipt, which is worse than the gate it replaced because it looks
authoritative.

**The module cache key moved to the as-loaded digest.** It was keyed on `ref.fingerprint`, which
is fine while those always agree and wrong the moment they can differ: two sources would map to
one `sys.modules` name and the first one loaded would be handed back, so an edit would appear to
have no effect. That is a worse failure than the refusal removed.

**`Workspace.remove` and the reverse index.** The workspace validated references in the forward
direction only, while decoding — a config naming a component that must exist. Withdrawing asks
the opposite question and nothing answered it, so `references_to` walks the document and
`remove` refuses while anything live still names the id, naming the blocker per 057. A dataset
refuses rather than reporting `()`, because its readers live in component requirements the
workspace does not index and an empty tuple would read as "safe to remove".

**Removal refuses on live declarations only, never on run records.** A finished run pins the
fingerprint it ran under inside its own frozen record, so a withdrawn registration does not
un-explain it. Refusing on run history would make a workspace un-prunable the moment it was used
once, which is immutability by the back door — the thing 009 removes.

**The dead publication layer is gone.** `_internal/publication.py`, `StrategyReplay.publish`,
`PublicationConflict`, and `test_publication_atomicity.py`. `StrategyReplay` survives as
`StrategyDrive` — the decisions and threaded state every caller actually uses, minus the half
nobody called.

## Two corrections to issue 009, both load-bearing

**Decision 4 as written would have broken the product.** It named `_internal/objects.py`,
`catalog.py` and `catalog_store.py` unused. They are not: `stage_object` is the persistence path
`Project.materialize` writes through, `read_object` backs `read_output`/`read_lineage`, and
`show_002` and `show_004` call them live. The sweep behind that claim counted `.publish()`
callers and missed that the object store has a second entrance the publication layer never used.
Only `publish_outputs` and `StrategyReplay.publish` were dead; `publication.py` was a leaf, so it
came out alone. **009's completeness criterion (`grep -r "objects/sha256"` finds nothing) is
unsatisfiable without breaking materialize** and has been replaced in the issue file.

**Decision 2's preimage premise is false.** It asks whether the installed package version belongs
in an identity that gates nothing. The gating preimage — `fingerprint_component` — is
`json({kind, object_name, config})` + NUL + source bytes, and carries neither a package version
nor a qualname. The version lives in `identity.py`, whose `compute_fingerprint`, `identify` and
`verify_no_drift` have **zero production callers**. No preimage was changed here.

## Trade-offs

**A run can now execute an edited component without being told.** That is the intended trade: the
run records what it ran, so the fact is recoverable from the record rather than enforced before
it. What this buys is that "this strategy ran 47 times across 12 distinct fingerprints" becomes
countable under one id — a direct overfitting signal that a new id per edit scattered across
twelve ids where nothing counted it.

**Two refusals left the inventory and two joined it.** `component.load.fingerprint_drift` and
`workspace.component.register.conflict` are gone; `workspace.remove.referenced` and
`workspace.remove.unsupported_kind` are new. The characterization baseline was regenerated and
the diff is exactly those four codes.

**`force=` on `register_component` is retained and gates nothing.** Replacement is the default,
because a refusal the caller must pass a flag to bypass, on an event that is ordinary, is the
same friction with an extra step. The parameter is an explicit spelling for a caller that wants
to say it meant it.

**Two tests changed meaning rather than being deleted.** `test_materialize` and `test_preflight`
pinned the removed refusals. They now pin what replaced them: an edited source loads and is
judged on its merits, so a stub that is not a `StrategyModel` is refused as
`component.load.wrong_type` and a mutated config as `component.load.construction_failed` —
refused for being unable to do the job rather than for having moved.

## Validation

- `uv run pytest tests/` — **1,282 passed**.
- All seven runnable showcases pass, including `show_002` and `show_004`, which 009's Decision 4
  as written would have broken.
- `tests/flow/test_edit_loop.py` is 009's stated acceptance criterion. Verified it fails against
  the pre-change `src/` — including with the literal `workspace.component.register.conflict` this
  work removes — and passes after.
- `tests/test_workspace_remove_and_force.py` covers the reverse index, the naming refusal, the
  leaf and dataset cases, and idempotent removal. Its refusal assertions read `observed` and
  `fix` rather than `str(error)`, because those are the fields a reader is shown.
- Refusal baseline regenerated deliberately: added `workspace.remove.referenced`,
  `workspace.remove.unsupported_kind`; removed `component.load.fingerprint_drift`,
  `workspace.component.register.conflict`. Nothing else moved.
