# 040 — An agenda drives exactly one strategy; the template is keyed the other way round and the refusal names an object the author never touched

**Status:** **CLOSED 2026-09-02 — record `138`** (campaign Step 6, branch
`step-06-a-shareable-agenda`). The ruling of 2026-08-31 — **an agenda is shareable** — is
implemented: the workspace keys `strategy_configs` by the strategy's component id, three strategies
naming one agenda are three registrations, and the conflict is one strategy naming two agendas,
refused by naming the strategy and the agenda it already holds. A document written in the
agenda-keyed shape decodes for one release and is written forward. `tests/test_an_agenda_is_shareable.py`
holds the acceptance criterion.

**Status before that:** owner-decided 2026-08-31, not yet implemented. The ruling: an agenda is
shareable. The one-agenda-one-strategy cardinality is not intended, so the workspace document
re-keys its `strategy_configs` section away from `agenda_id` and existing workspaces migrate. The
duplicate-cadence workaround, and the near-identical agendas this journey left behind, go with it.

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-018**,
`slowed` / `message` with a `docs` component.
**Touches:** `src/vqapr/cli/new.py:150` (the run-spec template's `strategy_configs` block);
`workspace.strategy_config.register.conflict`; `vqapr list strategy-configs`.

## What the author was doing

Registering the second and third strategies of a comparison. The replicated paper's whole empirical
design is *the same trading rule on residuals from different factor models* — so `ou-k0`,
`ou-pca-k5` and `ou-ff5` are one OU signal, same thresholds, same daily cadence. Comparing them is
the point.

## What the template implies

```yaml
strategy_configs:
  COMPONENT_ID:                     # component_id of a registered StrategyModel
    agenda_id: daily-rebalance      # the agenda above whose occurrences drive it
```

**The key is the component.** `agenda_id` is a *value* pointing at something else, phrased as *"the
agenda whose occurrences drive it"* — a cadence being referenced, not consumed. The agendas template
reinforces it: an agenda is *"a cadence: the days a thing happens on, and the local time of day"*,
which is a description of a schedule, and schedules are shared.

Three entries naming one agenda is the near-unavoidable reading.

## What happened

```json
{"code": "workspace.strategy_config.register.conflict",
 "requirement": "agenda_id 'krx-rebalance' must keep its existing declaration or use a new identity",
 "observed": "a different declaration is already registered",
 "fix": "keep the registered declaration for 'krx-rebalance' unchanged, or choose a new agenda_id",
 "explain": "workspace-state"}
```

Isolated with two minimal registrations:

```
A.  strategy_configs: {ou-ff5: {agenda_id: krx-rebalance}}        -> REFUSED (conflict)
B.  agendas: {krx-rebalance-ff5: ...identical cadence...}
    strategy_configs: {ou-ff5: {agenda_id: krx-rebalance-ff5}}    -> {"ok": true}
```

Same component, same cadence, same everything except a duplicated agenda id. **A
`strategy_config`'s identity in the workspace is its `agenda_id`, not its component id, and an
agenda drives at most one strategy.**

Confirmed from the other side by `vqapr list strategy-configs`, which reports pairs —
`{"agenda_id": "krx-rebalance", "component_id": "ou-k0"}` — displaying both halves of a relation
that only one half keys.

## Two problems, and the second is the expensive one

**1. The template's shape implies the opposite contract.** If the agenda is the identity, the
template should be keyed by agenda id. As written, a reader keys by component, registers three, and
finds out at the second one.

**2. The refusal names an object the author did not touch.** Their file contained a
`strategy_configs:` block and **no `agendas:` section at all**. Nothing in it redeclared
`krx-rebalance`. Yet the requirement is *"agenda_id 'krx-rebalance' must keep its existing
declaration"* and the fix is *"keep the registered declaration for 'krx-rebalance' unchanged"* —
advice about a declaration they were not changing and had not included.

Several minutes went into checking `agendas.yaml` for drift and re-reading the immutability rules in
the skill's `workspace-state` section before the true hypothesis was tested. `source` is all-null
(`file`, `key_path`, `line`), so there was no pointer back into the file to correct them.

The sentence that would have saved the time:

> *"agenda 'krx-rebalance' already drives strategy 'ou-k0'; an agenda drives one strategy —
> register another agenda for 'ou-ff5'."*

## The residue

**Cost:** ~12 minutes, plus a permanent workspace of near-duplicate agendas — `krx-rebalance`,
`krx-rebalance-ff5`, `krx-rebalance-pca`, byte-identical apart from their ids. Any change to the
firing cadence now has to be made three times consistently, **and nothing checks that they agree.**

That last part is the durable cost. A comparison across factor models is the normal shape of this
literature, and the package's answer to it is n copies of one cadence with no mechanism keeping them
in step — which quietly makes "same cadence" an author's promise rather than a workspace invariant.

## What to settle

Whether the one-agenda-one-strategy cardinality is intended. If it is, the template should be keyed
by agenda and the refusal should name the strategy already holding the agenda. If it is not, an
agenda should be shareable and the duplicate-cadence workaround disappears with it.
