# The agent-first surface: design from the caller inward

## Why this document exists

The migration so far was built bottom-up: read what the engine exposes, wrap it in a
bridge, translate the caller. That produces a surface shaped like the engine. The
criterion was supposed to be different — whether a research agent can *use* it.

This document works in the other direction. It starts from what an agent tried to say and
could not, and derives the surface from that.

## The evidence base

Nine defects were found while migrating real code onto this surface. **Not one was found
by reading it.** Each appeared only when a real strategy had to be written against it.
That makes them requirements rather than a bug list — each is a sentence an agent needed
to say and the surface could not express.

| The agent wanted to say | What actually happened |
|---|---|
| "read this dataset" | registered, but invisible to `simulate` |
| "apply this constraint" | every constraint-bearing run failed on identity |
| "this venue trades fractionally" | no field existed; a tiny `quantity_step` was the only approximation |
| "run this factor" | a model taking a constructor argument could not be built at all |
| "decide on NAV" | `nav` was hardcoded `None` in both bridges |
| "record this diagnostic" | rows validated against their schema, then discarded |
| "publish what this run decided" | no route from a completed run to a dataset |
| "inspect the costs" | `SimulationSummary` was four integers |
| "install a model I wrote" | the loader refused the authoring contract it ships |

Three of these were reported by workers who tried to use the surface and asked rather than
routing around it. That is the intended signal: **an agent blocked by the surface is the
measurement.**

## Principle 1 — the agent states economics, the framework stamps facts

An intent carries four fields no agent should supply: `intent_id`, `strategy_id`,
`source_refs`, `account_version`.

These are not conveniences withheld. They are *framework facts*, and an agent that mints
them can get them wrong in ways that corrupt provenance without failing loudly. The engine
already rebuilds `source_refs` from the accesses it observed and refuses any intent whose
ordering disagrees — measured this session as
`intent source_refs do not exactly match sources read through ModelWindow`.

So the legacy surface hands an agent a loaded weapon and then checks whether it fired
correctly. The authoring contract removes the weapon:

```python
return StrategyResult(
    decision=Rebalance(target_weights=..., cash_weight=..., budget=BUDGET),
    next_state=...,
    diagnostics={...},
)
```

`Hold(reason=...)` and `Rebalance(...)` are the whole vocabulary. Identity, provenance and
versioning are stamped by the framework because it is the only party that can know them.

**This principle is already satisfied and proven.** Five factors reproduce their locked
baseline exactly — 636,324 weights, decimal for decimal, and all five Kimchi correlations
to six places — from models that mint nothing.

**Open consequence:** `extension/scaffold.py` generates the template a new agent copies,
and that template hand-mints all four fields. The package teaches the ceremony it exists
to remove. The scaffold cannot be migrated alone; it moves with the CLI registration path
and the loader conformance check, which is one unit.

## Principle 2 — a declaration with no field is a sentence that cannot be spoken

`venues.Academic` had no `fractional_allowed`. An agent wanting an unquantized academic
venue had no way to say so, and the closest approximation — a very fine `quantity_step` —
silently produced different economics, because the bridge hardcoded `fractional_allowed=False`
and `TradeRule.quantize` floored every quantity regardless.

That cost a showcase its baseline parity and took a two-directional diff to find.

The rule: **an absent field is indistinguishable from an unsupported capability.** An agent
cannot tell "this system will not do that" from "I do not know how to ask." Both look like
a wrong number.

Corollary: defaults must be stated, not assumed. `fractional_allowed` defaults to `False`
because a share is indivisible — a real-venue default, written down, with the permissive
case requiring an explicit request.

## Principle 3 — post-run readback is a first-class requirement, not an afterthought

`SimulationSummary` deliberately exposed four integers so a caller could not reach engine
internals. That was the right instinct and the wrong bound: **a run whose costs and fills
cannot be inspected is not usable for research**, which is the entire purpose.

`CompletedRun` now carries the committed account, the recorder tables, and a publish route.
The test is whether an agent can answer research questions from what a run returns:

- what did it hold, and at what version — `completed.account`
- what did it pay — `completed.fills()` carries commission, tax, dealt quantity
- what did it record — `completed.table(id)`, including author-declared diagnostics
- what can the next run subscribe to — `completed.publish_allocation(...)`

**Design smell to watch:** every one of these was added *after* a real caller needed it.
The surface should be designed against the questions, not extended each time one is asked.

## Principle 4 — a refusal is a decision and needs a name

`Hold(reason="no-eligible-names")` is not a null result. It is the strategy saying why it
declined, and that reason belongs in the record.

`reason` is validated as a whitespace-free identifier, which is a real constraint an agent
must learn — prose fails at the callback boundary. This was found by running, not reading,
in both the scaffold templates and a migrated showcase.

## Principle 5 — YAML declares and installs; Python authors and runs

**Ruled by the owner.** The division is by what the thing *is*, not by convenience:

- `DataModel`, `StrategyModel` and later `Exchange` are pluggable modules. They are code,
  so they are **Python**.
- Datasets, execution inputs and the installation of an authored model are explicit
  declarations. The agent writes **YAML** and installs it with the **CLI**.

Writing a strategy is Python. Registering the strategy you just wrote is CLI.

### Why `Simulation` grew to nine fields

Measured, not inferred. `Project._engine_definition` is 104 lines of which 15 are
registration calls, and it performs five registrations **on every run**:
`register_execution_input`, `register_agenda`, `register_component` for the strategy,
`register_component` per constraint, `register_component` for the exchange, plus the
catalog dataset bridge.

So `Simulation` is large because it conflates two different times:

| decided once, at registration | decided per run |
|---|---|
| where the execution table lives, and its field names | the period |
| the venue | the account it starts from |
| which class the strategy is | which constraints apply |
| the datasets | the instruments |

Every run re-declares and re-registers the registration-time half. The field count is a
symptom; the cause is that a run is being asked to describe a workspace.

`cli/register.py` already understands exactly the sections this needs — `datasets`,
`execution_inputs`, `agendas`, `components`, `strategy_configs`, `valuation_configs`,
`monitoring_policies`. The declaration path exists; `Simulation` duplicates it.

Under the split, a run references registered names instead of restating them:

```python
Simulation(
    period=...,        # when
    account=...,       # from what
    constraints=(...), # under what rules
    instruments=(...), # over what
)
```

**This also dissolves most of the bridges**, because there is far less left for
`_engine_definition` to assemble.

## Principle 6 — bridges are a smell, not an architecture

**Ruled by the owner:** proliferating `_internal/*_bridge.py` is not a good pattern. That
is correct, and the seven of them are an artifact of having worked outward from the engine
rather than inward from the caller.

They exist because nine engine/authoring type pairs had nothing joining them:
`EconomicPortfolioIntent`/`Rebalance`, the two `ConstraintFinding`s, `ConstraintBounds`
`lower`/`upper` versus `lower_weights`/`upper_weights`, `DataRequirement`/`DatasetInput`,
`AccountSnapshot`/`EconomicAccountView`, and four more.

Sorted by what they become under Principle 5:

- `registration_bridge`, `schedule_bridge`, `venue_bridge` — largely **dissolve**. They
  translate registration-time declarations that move to the CLI path.
- `strategy_bridge`, `constraint_bridge` — the real seam, at the callback boundary. These
  should be a **contract implementation**, not an adapter: the authoring types are the
  contract and the engine consumes them, rather than two type systems being translated.
- `run_bridge`, `pit_bridge` — readback and point-in-time reads, which are genuine
  capabilities rather than translation. They belong on the surface under their own names.

The test for any survivor: if it exists to convert type A into type B, one of the two
types is in the wrong place.

## Principle 7 — an Exchange must be adjustable until it is pluggable

**Ruled by the owner:** exchange friction is inherent, and the answer is to make `Exchange`
pluggable later. Until then `Academic` and `KRX` must be **maximally adjustable**.

This reframes the `fractional_allowed` defect. It was not one missing field — it was an
adjustability gap, and the same gap will produce the next one. `venues.Academic` currently
carries five knobs: `listings`, `quantity_step`, `price_step`, `costs`,
`fractional_allowed`. A scenario needing `minimum_quantity`, a price band, or the
ETF/stock tax-exemption split still cannot be expressed.

The near-term requirement is therefore not "add the field a showcase needed" but "make
every economic term these two venues model reachable from their declaration".

## What is still open

### Where does strategy config live?

A model may take constructor arguments — `FactorPortfolio(factor="HML")`. If config goes
in the YAML, five factors need five registrations of the same class. If it goes in Python
at run time, the registration/execution boundary blurs again.

*Working answer, pending confirmation:* YAML registers the class under a name; config is
supplied **per run**, because running one registered model under five configurations is
exactly the factor testbed's real usage pattern.

## What the structure permits

Measured, not assumed:

- `public.py` is 419 lines with 11 definitions of its own, re-exporting from 28 modules
- **zero** engine files import it — `flow/`, `models/`, `portfolio/`, `valuation/`,
  `exchange/`, `data/` are all clean
- dependency runs one way: public → engine
- six real legacy consumers remain, plus six bridges written this session

So the backend separation is genuine and removal can be incremental: retire one legacy
consumer per dogfooding migration, and if removing one breaks something unrelated, that is
the coupling signal worth stopping for.

The breaking release stays a separate final step. Deletion is revertible; a release is not.

---

# The ruling — 2026-08-28

Everything above this line was written from the caller inward, before anything measured which
facade the product actually runs on. This section is that measurement, and the decision it forces.
Where the two disagree, this section wins.

## Which facade ships

**The CLI is the product. `vqapr.public` is its supported implementation surface.
`vqapr/project.py` and `vqapr.open` are unshipped and frozen.**

Not a preference — a tracer result. A PEP 669 line-level trace of a complete first-user CLI
journey (`list` · `new` · `register` · `check` · `run` · `show`, all kinds, two runs completing
`ok:true`), intersected with the 1309-test suite:

| module | executable lines | ran in the CLI journey | ran in the test suite |
|---|---:|---:|---:|
| `vqapr/project.py` | 619 | **0** | 464 |
| `vqapr/simulation.py` | 327 | **0** | 283 |
| `vqapr/_internal/constraint_bridge.py` | 177 | **0** | 100 |
| `vqapr/_internal/extensions/identity.py` | 168 | **0** | 159 |
| `vqapr/_internal/catalog_store.py` | 159 | **0** | 130 |
| `vqapr/_internal/catalog.py` | 158 | **0** | 145 |
| `vqapr/_internal/run_bridge.py` | 118 | **0** | 73 |
| `vqapr/_internal/venue_bridge.py` | 117 | **0** | 54 |
| `vqapr/venues.py` | 109 | **0** | 93 |
| `vqapr/materialization.py` | 82 | **0** | 75 |
| `vqapr/_internal/objects.py` | 71 | **0** | 66 |
| `vqapr/_internal/registration_bridge.py` | 69 | **0** | 58 |
| `vqapr/_internal/schedule_bridge.py` | 34 | **0** | 34 |

These modules are not under-exercised. They are exercised thoroughly, and **only by the tests
written for them**. `vqapr/project.py` has exactly one importer — `vqapr.open()` — and the CLI
never calls it. Outside `tests/`, the whole cluster has three consumers, and all three are
showcases: `show_001`, `show_002`, `show_004`.

So the layer the design document above calls "legacy" is the one the shipped product stands on, and
the layer it calls the destination is the one no shipped command reaches. That inversion is the
reason this ruling exists.

## What frozen means

- **No new callers.** Nothing in `src/` may add an import of `vqapr/project.py`, `vqapr.open`,
  `vqapr/simulation.py`, `vqapr/materialization.py`, or `vqapr/venues.py`.
- **No growth.** Do not extend these modules to serve a new requirement. If a CLI verb needs a
  capability that lives there, reach it through `vqapr.public` or lift the capability out.
- **No deletion, either.** Removing them is `G008`, and its conditions are below.
- Scaffolds keep emitting `from vqapr.public import ...`, because that is what the shipped product
  runs on. An emitted import is the most-copied artifact in the package; it must name the surface
  that will still exist after this ruling, and that surface is `vqapr.public`.

## The tripwire

The earlier count of "15 `src/` files import `vqapr.public`" conflated three different populations:
modules with a real `import` statement; files where the string sits inside **emitted template text**
(`cli/new.py:396`, `:505`; `extension/scaffold.py:62`); and **user-facing refusal strings**
(`workspace.py:548`, `:558`). Work in this very slice edits the template and string sites, so a
string count moves for reasons that have nothing to do with what it measures.

**Definition.** The tripwire is the count of modules under `src/` containing a real `import`
statement for `vqapr.public`, excluding every occurrence inside a string literal. An AST walk is
what makes that exclusion real: template text and refusal strings are `Constant` nodes and are
structurally invisible to it.

**Verified value: 11.** Confirmed on 2026-08-31 by `tests/boundaries/test_the_facade_is_not_reached_up_to.py`, which asserts it.

It was **12** until `docs/implementations/112-registration-without-the-cli.md` moved
`cli/register.py`'s declaration parsing into `vqapr/declarations.py`. That module reaches the
owning modules directly rather than the facade, so the verb stopped being an importer. The
original count was confirmed by running the command below on 2026-08-28.

```
PYTHONUTF8=1 uv run python -c "import ast,pathlib; print(sum(1 for p in pathlib.Path('src').rglob('*.py') if any(isinstance(n,ast.ImportFrom) and (n.module or '')=='vqapr.public' or isinstance(n,ast.Import) and any(a.name=='vqapr.public' for a in n.names) for n in ast.walk(ast.parse(p.read_text(encoding='utf-8'))))))"
```

The twelve, so a later count can be diffed rather than merely compared:

```
_internal/constraint_bridge.py   _internal/registration_bridge.py   _internal/run_bridge.py
_internal/schedule_bridge.py     _internal/strategy_bridge.py       _internal/venue_bridge.py
agent/sample/exchange.py         agent/sample/journey.py            cli/check.py
cli/run.py                       project.py
```

`cli/new.py` and `extension/scaffold.py` are deliberately **not** in this list. `new.py`'s real
imports are at `:38-42` and `scaffold.py`'s sole import is at `:15`; neither imports `vqapr.public`
at all, and their occurrences are inside the templates they emit.

For completeness and to stop the earlier error being inherited silently: the number **15** that was
circulating is the count of **files under `src/` containing the string `vqapr.public` anywhere**,
measured before this ruling was written. It is neither an importer count nor an occurrence count —
raw occurrences are roughly twice that, since `project.py` alone carries seven. Do not use it as the
tripwire.

It has already moved, inside the very change that wrote this section: the `src/vqapr/__init__.py`
docstring above now mentions `vqapr.public`, so the file count is **16** while the importer count is
unchanged at 12. That is the failure mode this section exists to describe, demonstrating itself.

## What the tripwire does not watch

**The tripwire counts importers of `vqapr.public`, which is not one of the five frozen modules.**
"What frozen means" prohibits adding imports of `project.py`, `vqapr.open`, `simulation.py`,
`materialization.py` and `venues.py`; the number 12 says nothing about any of them. A reader who
runs the only command given here, sees 12, and concludes the whole freeze is intact would be
reading a number that never looked.

The current state of the five, measured on 2026-08-28 so a later count is a diff rather than a
guess:

- `project.py` — exactly one importer in `src/`, `vqapr/__init__.py`, which is `vqapr.open()`.
- `venues.py` — imported by `_internal/venue_bridge.py`, which is itself inside the frozen cluster,
  and by `simulation.py:30` (`from vqapr import authoring, venues`), which is also inside it. The
  second edge was missing from this list until `docs/implementations/115-*.md`: the boundary test
  written to hold this record could not see the `from vqapr import X` spelling, so an inherited
  edge between two frozen modules went unrecorded in both places at once. Neither end is a new
  caller, which is why nothing was violated — but the list was not the record it claimed to be.
- `simulation.py` — imported only by `project.py`.
- `materialization.py` — **no `import` statement anywhere in `src/`**; reachable only as a lazily
  resolved capability name in `__init__.py`'s `_CAPABILITIES`.
- `vqapr.open` — called by no shipped command.

The prohibition is on **adding**, so those existing edges are legal; they are recorded here so a
later reader can tell an inherited edge from a new one.

## The second boundary: one door into `_internal/extensions`

The tripwire above watches modules reaching **up** to `vqapr.public`. This section watches the
other end: modules reaching **past** the four forwarding adapters under `extension/` into
`_internal/extensions/`, which is the same failure — a boundary documented in prose and enforced by
nothing — measured at the bottom of the package instead of the top. `docs/issues/029` is the file
that found it.

**The rule.** `vqapr.extension.component`, `.fingerprint`, `.loading` and `.registration` are the
only door. No module under `src/` outside `_internal/` may import `vqapr._internal.extensions.*`
directly, and a name the adapter does not yet forward is added to the adapter rather than routed
around it. Keeping the forwarding surface complete is maintenance of a transitional module, not
growth of it; the prohibition on growth is about logic, fallbacks and deprecation warnings.

**Why the door is the adapter and not `_internal`.** The adapters are scheduled for deletion, and
the intuitive reading — do not add callers to a module that is going away — is backwards. A deletion
whose callers all name one path is four files removed with every stale import breaking loudly at
import time. A deletion reached by two paths is found by grep and is complete when somebody says it
is. The one-door rule is what keeps that cutover mechanical.

**Permitted importers of `vqapr._internal` outside `_internal/` itself, verified 2026-08-30:**

```
extension/component.py   extension/fingerprint.py   extension/loading.py
extension/registration.py   project.py
```

The first four are the adapters; naming `_internal` is their entire content. `project.py` is in the
frozen cluster above — unshipped, no new callers, no growth — so its `_internal` imports are
inherited edges recorded here rather than an example to copy.

`tests/boundaries/test_internal_has_one_door.py` enforces this list by AST walk, including
function-local imports, because the three bypasses `docs/issues/029` found were all inside function
bodies and a header-only check would have called those files clean. `tests/` are deliberately out of
scope: they may reach the physical home directly, and
`tests/extension/test_agent_first_internal_routes.py` exists to do exactly that.

**The deletion itself is not scheduled here.** It belongs to `G008` and its conditions are below.
Until 2026-08-30 all eight modules pinned it to `G004` instead, an id that had by then been
reassigned to a different, completed goal, so a reader who looked it up found evidence the deletion
had already happened. Those notes now cite this document, which is in `.agent/project.yaml`'s
canonical set and survives renumbering.

## The G008 admission conditions

`G008` — delete `vqapr.public`, relocate the retained authorities, and cut the breaking release —
is **blocked**, and this ruling does not unblock it. `gjc-handoff/session-03/goals.json` records
two independent gates verbatim, and both are still shut:

**Gate 1 — PLAN GATE.** The approved plan's escalation gate states: *"Do not begin T4
deletion/build Q unless all hold: … whole testbed — including `register.py` — passes T0 trace/row
comparator."* That comparator run was `G010`'s deliverable and **has not happened**. Beginning the
deletion now would also destroy the legacy path the parity comparison must run against, because T2
keeps it alive *"solely for baseline comparison"*.

**Gate 2 — OWNER APPROVAL.** The goal deletes `vqapr.public`, physically relocates **8,139** lines
across **38** files with **70** inbound references, and cuts a breaking **`0.2.0a1`** whose
rollback is a whole-cutover revert. Deletion is revertible; a release is not.

So a future session may open `G008` only when both hold: the T0 trace/row comparator has been run
over the whole testbed including `register.py` and its result is recorded, **and** the owner has
explicitly approved the deletion and the breaking release. Neither is implied by this ruling, and
writing these conditions down is not approval of them.

What it would cost, so the approval is an informed one: three showcases (`show_001`, `show_002`,
`show_004`) move back or are dropped, and roughly 2,200 executable lines plus 4,529 test lines
across 14 test files retire with the cluster.

## Why this is written here and not only in a handoff

It was written once already. `gjc-handoff/README.md` was correct and complete on 2026-08-25 — it
counted the legacy consumers file by file and recorded `G008`'s blockers. The next twenty commits
added three more `vqapr.public` importers, two of them in the newest and most deliberately designed
CLI code in the tree, because the knowledge lived in one handoff file the canonical document set
contradicted.

`.agent/project.yaml` names this file as `surface_design`, so a session reading its canonical
documents reaches this ruling. `docs/vqapr-architecture.md` is **not** in `canonical_documents`,
and its §2.6 and its module map now point here rather than asserting a sole documented surface.

## Where the evidence for this ruling lives

`testbed-claude/` holds the first-time-user journey that produced the measurement above — its
`REPORT.md`, `JOURNAL.md` and `FRICTION.md`, and the three observer documents `CODE-MAP.md`,
`AGENT-REVIEW.md` and `WHAT-GJC-THINKS.md` that the tracer numbers, the two-facade finding and the
scaffold-propagation finding all come from.

**It stays untracked and untouched, by owner ruling.** Nothing is `git add`ed out of it, no file is
relocated into `docs/`, and it is not committed. This ruling and
`docs/issues/011-the-documented-surface-cannot-reach-a-cost.md` cite it by path, which is the
intended durability: the conclusions are carried by tracked documents, and the raw journey stays
where a later run can regenerate or replace it without a repository decision.
