# 009 — A fingerprint is a receipt, not a gate

**Status:** open. Written 2026-08-27 from an owner audit of every digest in the package, prompted by
asking what a daily batch that lists one new ticker would do to a registered roster.
**Blocks 008.** The plan in progress for 008 is deliberating a comparison this file voids. **Read
"Stop the 008 comparison" first, before resuming any planning.**
**Touches:** `src/vqapr/_internal/extensions/loading.py`, `src/vqapr/workspace.py`,
`src/vqapr/_internal/extensions/identity.py`, `src/vqapr/data/store.py`,
`src/vqapr/_internal/{objects,catalog,catalog_store,publication}.py`, `src/vqapr/project.py`,
`src/vqapr/cli/`

## Stop the 008 comparison

008 recommended **freezing** the instrument roster at registration. A planning pass then verified
two of that recommendation's three premises were false and moved to **importing** it at every run,
gated by `component.load.fingerprint_drift`. The verification was correct and the conclusion is
still wrong, because **both options share a premise that does not hold**:

> a roster changing between runs is a dangerous event

It is not. A daily batch lists new tickers; issuers delist; a name is reclassified. **A roster grows
as a matter of course.** Under either option that ordinary growth costs the owner a command every
morning — and under IMPORT it costs more than that, because `fingerprint_drift` refuses **every**
run, including the ones that never touch the new name.

The question was never FREEZE vs IMPORT. It was **gate vs receipt**, and a roster wants a receipt:

```
read the current roster at run start        no copy, no gate
record which roster the run used            run record, as a fact
record what each fill was charged as        Fill.kind, already implemented
```

Nothing refuses. Nothing is copied into the project. What a past run treated as a share is
testified to by that run's own fills, which is stronger provenance than a gate ever gives, because
it survives the roster changing afterwards.

**Do not re-open FREEZE vs IMPORT.** Delete that section of 008 and proceed with the ownership move
it is actually about.

## The audit

Five distinct things in this package compute a digest. Only one of them refuses anything.

| | What is digested | Where | What it does | Refuses? |
| --- | --- | --- | --- | --- |
| **A** | **component source bytes** | `identity.py`, stored in `workspace.yaml` | identifies a strategy / datamodel / exchange / constraint | **yes, twice** |
| B | a data source file | `store.py:53-57`, memoised per path per run | rides on every intent as `IntentSourceRef` | no |
| C | a declaration's contents | `listings.py:389`, agendas, datasets | detects "same id, different declaration" | conflict only |
| D | a stored object's contents | `.vqapr/objects/sha256/<digest>` | **is the address** — crash-safe publication | different purpose |
| E | the installed skill file | `cli/skill.py` | reports whether the copy is current | no |

**E is right and stays.** The PRD requires it: a generated skill file modified by the user must be
detected by content fingerprint and not overwritten without explicit confirmation
(`docs/vqapr-prd.md:2124`). It was added last week after a stale installed skill silently invalidated
an agent-journey measurement, and it reports rather than refuses.

**C is right where it is a genuine conflict** — one id, two different declarations — but see
Decision 5, because today a conflict has no resolution other than deleting the workspace.

**A, B and D each need a decision, below.**

## What the PRD and architecture actually say

The audit was prompted by a fair question: is any of this doctrine, or did it accumulate?

**Reproducibility from file hashes is contradicted outright.** `docs/vqapr-architecture.md:927-934`:

> `available_at`이 커지면서 붙는 행은 그보다 이른 evaluation time에 보이지 않는다. PIT 술어가 이미
> 그것을 보장하므로, **재현을 위해 파일을 얼릴 필요가 없다.** ... **이것이 point-in-time 데이터를
> 쓰는 이유 그 자체다. 파일 불변성이 아니라 술어가 재현을 만든다.**

The architecture names the real risk in the next paragraph — restatement, a past row edited in
place — and treats it as a data-quality problem, not something a digest gate solves.

**The extension fingerprint is mandated as identity, not as a gate.** `docs/vqapr-prd.md:2216` lists
"version과 source fingerprint" among the things vqapr validates deterministically, under a heading
about **identification and compatibility** whose point is that *"source를 찾거나 load할 수 있다는
사실만으로 compatibility가 증명되지 않는다."* That asks the package to know **which** extension it
loaded. It does not ask the package to refuse a run because the author edited a line, and it does
not ask registration to refuse the same id under new bytes.

`docs/vqapr-prd.md:1931` uses "input·producer fingerprint" for **reuse judgement** — deciding whether
a stored artifact may be used without rerunning its producer. That is a cache-validity use, and it
is a receipt use.

**Conclusion: computing and recording A is doctrine. Refusing on A is not.** The two refusals below
are an implementation choice that no requirement asks for.

## Decision 1 — the roster takes no gate

Per "Stop the 008 comparison". The roster is read fresh at run start, recorded in the run record as
a digest **stated, not compared**, and testified to per fill by `Fill.kind`. A new listing must
never refuse a run.

## Decision 2 — the component fingerprint stops refusing

A is computed, stored and recorded exactly as now. **Both refusals go.**

**Refusal 1, at load** (`loading.py:78-90`): the source no longer matches the registered fingerprint,
so the run is refused with `component.load.fingerprint_drift`, fix `"re-register the component"`.

**Refusal 2, at registration** (`workspace.py:803-820`): the same `component_id` with different bytes
is refused with `component.register.conflict`, fix `"register the changed source under a new
component_id such as 'simple_mom-eb043fb3fe40'"`.

**They point at each other.** Editing one line and re-running gives:

```
vqapr run spec.yaml        -> fingerprint_drift.  fix: re-register the component
vqapr register strategy simple_mom strategy_simple_mom.py
                           -> register.conflict.  fix: use a NEW component_id
```

The load refusal names a repair the registration refusal forbids. This repository has met that shape
before and named it: *"a refusal that names a repair it has itself disabled sends the reader in a
circle, which is worse than a generic error"* (`docs/implementations/057`).

The code knows. `workspace.py:800-803` says so in a comment before raising:

> `# Editing a registered component is the ordinary development loop, and "use a new identity"`
> `# without saying which one leaves every user to invent the same fingerprint-suffix scheme by hand.`

Editing a registered component **is** the ordinary development loop — switching an equal-weight
signal to value-weight is one line — and the answer chosen was that every edit mints a new identity.
The real cost is not one command:

```
1. register the component under a new id            simple_mom-eb043fb3fe40
2. add a strategy_configs binding for the new id    (configs are keyed by component_id)
3. edit spec.yaml to name the new id
4. run
```

Four steps per edit, and the workspace accumulates `simple_mom`, `simple_mom-eb04...`,
`simple_mom-91c7...` for what is one strategy.

**Provenance does not need the gate, because the receipt already exists.** `public.py:500` writes
`source_digest = str(frozen.identity)` into every run record, and `flow/run.py:380-399` folds
`(component_id, fingerprint)` for the strategy, the exchange and every constraint into that identity.
Two runs of edited code already carry two different digests. Nothing is lost by letting the id stay.

**Removing the gate makes a use the owner wants possible, which the gate currently prevents.** Keeping
one id and recording a fingerprint per run yields *"this strategy ran 47 times across 12 distinct
fingerprints"* — a direct overfitting signal. Forcing a new id per edit scatters that history across
twelve component ids where nothing counts it.

**Also re-examine the preimage.** `identity.py:11-16` builds the fingerprint from extension kind, the
**installed `vqapr` package version**, full source bytes, qualname and canonical config. Upgrading
the package therefore changes every component's fingerprint without a character of user code
changing — the same defect as the roster's daily batch, one level up. Whether the package version
belongs in an identity that gates nothing is worth settling while the gate is being removed.

## Decision 3 — the data source digest goes

B is removed: `store.py:53-57,71`, `AccessRecord.source_digest` (`windows.py:25`), the within-run
consistency check at `simulation.py:1889-1891`, and the digest half of `IntentSourceRef`.

The owner's reasoning, recorded because it is the argument and not a preference: the code hash
already identifies the code, so a same-code same-period run producing different numbers is a data
difference by elimination — and it **must not happen at all**. Recording a digest to explain an event
that is itself a defect buys nothing.

The architecture agrees and says so first: reproduction comes from the PIT predicate, not from
freezing or hashing files (`vqapr-architecture.md:934`).

**Check the removal's edges rather than assuming they are clean.** `IntentSourceRef` is a public type
and the intent carries it; the strategy scaffold used to assemble source refs by hand before Step 7
removed that. Whether the ref keeps a `source_id` without a digest, or goes entirely, is the one part
of this decision to settle in code rather than here.

## Decision 4 — remove the unused publication machinery

> **AMENDED 2026-08-27, and the amendment is the point.** This decision as first written would
> have **broken the product**. It named `_internal/objects.py`, `catalog.py` and
> `catalog_store.py` as unused; they are not. `stage_object` is the persistence path
> `Project.materialize` writes through (`project.py:627,638`), `read_object` backs `read_output`
> and `read_lineage` (`project.py:458`), and `show_002` and `show_004` call those live. The sweep
> below counted `.publish()` callers and missed that the object store has a **second entrance**
> the publication layer never used.
>
> The genuinely dead layer was `publish_outputs` and `StrategyReplay.publish` only.
> `_internal/publication.py` imports from `catalog`/`catalog_store`/`objects` and nothing imports
> it back, so it was a leaf and came out alone.
>
> **What was removed:** `_internal/publication.py`, `StrategyReplay.publish`,
> `PublicationConflict`, and `tests/internal/test_publication_atomicity.py`. `StrategyReplay`
> itself survives as `StrategyDrive` — the decisions and threaded state every caller actually
> uses, minus the publication half nobody called.
>
> **The completeness criterion below is also wrong and is replaced.** `grep -r "objects/sha256"`
> cannot return nothing without materialize being broken. The criterion is instead: no module
> implements a *publication transaction*, and `Project.materialize` / `read_output` /
> `read_lineage` and their showcases still pass.

`.vqapr/objects/sha256/` is a content-addressed store with a transactional catalog and crash-safe
atomic multi-output publication, built across commits `d01d6e5b` and `1ed5010b`. **Nothing uses it.**

```
.publish() callers, across src/ tests/ showcases/      0
StrategyReplay consumers outside project.py            0   (already verified in implementations/060)
_internal/publication.py importers                     project.py, and its own test
.vqapr/objects/ in testbed/                            absent  (only runs/)
.vqapr/objects/ in vqapr-testbed-2/workspace/          absent  (only materialized/)
```

Materialization writes to `.vqapr/materialized/` (`materialize.py:541`); run records write under
`store.root/runs/`. Neither path passes through the object store. `cli/run.py:293` says it in the
product's own words: *"delivered and tested, its publication half is not."*

`docs/implementations/060` preserved this capability at Step 5 on the grounds that Step 6 would need
it for `store.tables`. Step 6 has landed and the caller count is still zero. **The expected consumer
did not arrive.**

The rule to apply is this package's own, written when the effective-dated cost-band matcher was
removed for exactly this reason (`exchange/costs.py`):

> **"Machinery whose only user is its own test is not a feature."**

Remove `_internal/objects.py`, `_internal/catalog.py`, `_internal/catalog_store.py`,
`_internal/publication.py`, `StrategyReplay` and its factory in `project.py`, and
`tests/internal/test_publication_atomicity.py`. Per the repository rule, remove outright: no shim, no
alias, no deprecation. If atomic multi-output publication is wanted later it will be designed against
a caller that exists.

## Decision 5 — `register --force`, and a way to remove

Today a registration can be created and never corrected or withdrawn. `--force` exists on
`vqapr run` (replace a run record) and on `vqapr skill remove`; **`register` has neither `--force`
nor any counterpart.** The verb set is `new register check run list show skill` — there is no
removal verb at all.

The emitted templates state the consequence plainly: *"Registrations are immutable. During disposable
first-run setup, correct this YAML and **rebuild the project-local workspace**."* Deleting `.vqapr/`
and starting over is the documented repair for a typo in a dataset id.

Two additions:

```
vqapr register <file> --force        replace an existing registration in place
vqapr remove <kind> <id>             withdraw one, refusing when something still references it
                                     and naming what does
```

`remove` refusing with its references named is what keeps this from becoming a way to break a
workspace quietly — the workspace already knows those edges, since it refuses a config that names an
unregistered component (`workspace.py:1873`).

This is small, and it is a prerequisite for the others: Decision 1 gives the owner a roster that will
be re-registered as the world changes, and there is currently no command that does that.

## What stays

- **E, the skill fingerprint.** Required by `prd.md:2124`, and it reports rather than refuses.
- **C, as a conflict detector.** One id must not silently mean two different declarations. What
  changes is that a conflict now has a resolution (Decision 5) instead of only a message.
- **Computing and recording A.** The fingerprint keeps being derived and keeps landing in the run
  record. Only the two refusals go.
- **The frozen-run identity.** `frozen.identity` folds component fingerprints and is what makes a run
  record self-describing. It is the receipt this whole file argues for.

## What not to do

**Do not replace a removed gate with a warning that is really a gate.** A refusal the caller must
pass a flag to bypass, on an event that is ordinary, is the same friction with an extra step.

**Do not make the roster or the component id immutable "for provenance".** Provenance is the run
record plus `Fill.kind`. Both already exist, both already work, and both keep working when the world
changes underneath them — which is the property a gate does not have.

**Do not remove `C` along with `A`'s refusals.** Registering two different declarations under one id
is a genuine mistake and should still be refused; it just needs `--force` and `remove` to be
repairable.

## To measure when this is picked up

- **The edit loop, end to end.** Change one line of a registered strategy, run, and get a result with
  a new `source_digest` — in **two** commands, with no new component id, no new config binding and no
  spec edit. That is the acceptance test for Decision 2, and it should be written before the change.
- **The daily-batch case.** Add one ticker to a registered roster and re-run an existing spec that
  does not trade it. The result must be identical and nothing may refuse. That is the acceptance test
  for Decision 1.
- **A package upgrade.** Bump the installed version and load a registered component. Today every
  component's fingerprint moves; after Decision 2 nothing should refuse, and whether the recorded
  identity should move at all is the open question in that section.
- **The removal is complete.** After Decision 4, no module under `_internal/` implements a catalog or
  an object store, and `grep -r "objects/sha256"` finds nothing. A partial removal that leaves the
  catalog reachable is the failure mode, because the next session will build on what it finds.
