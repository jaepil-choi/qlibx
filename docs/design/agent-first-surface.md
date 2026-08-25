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
