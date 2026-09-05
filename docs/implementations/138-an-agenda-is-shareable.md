# 138 — an agenda is shareable: a strategy config is keyed by the strategy

**Closes:** `docs/issues/040`. **Step:** 6 of
`docs/refactoring/2026-09-02-the-convergence-campaign.md` (M6).
**Authority:** the owner's ruling of 2026-08-31 in `040` (an agenda is shareable); design
`docs/design/the-panel-the-surface-and-the-run.md` §4.1, which names `040` as the prerequisite of
Noun 3; campaign §Step 6 (the acceptance criterion).

## Why this exists

The workspace keyed its `strategy_configs` section by `agenda_id`. That made an agenda drive at
most one strategy, and it made the second registration fail with a sentence about the agenda —
*"agenda_id 'krx-rebalance' must keep its existing declaration"* — when the author's file had no
`agendas:` section at all. The run-spec template, and the declaration reader behind it, were
already keyed by the component: the template said what the workspace refused.

The cost was not the refusal. It was the workaround: one cadence copied n times under n ids so
that n strategies could be compared, with nothing keeping the copies in step. A comparison across
factor models is the normal shape of this literature; `vqapr-enhanced-index-3` measured six
byte-identical agendas for six factors.

## Rulings

| question | ruling |
|---|---|
| cardinality | an agenda is a cadence, and cadences are shared: several strategies may name one agenda. |
| identity | the binding is keyed by the **strategy** (its component id). One strategy naming two agendas is the conflict. |
| the refusal | names the strategy the author wrote and the agenda it is already bound to. |
| the document | written forward as `{component_id: {agenda_id, agenda_role}}`; the agenda-keyed shape `{agenda_id: {component, agenda_role}}` decodes for one release. No migration command. |

## What changed

- **`workspace.py`.** `_merge_strategy_config` keys by the component id. `_merge_declaration`
  takes a `noun` — what the key *is* — so the conflict sentence names `component_id`, and for a
  strategy config the observation is *"strategy 'ou-k0' is already bound to agenda
  'krx-rebalance'"*. `strategy_config(component_id)` looks the binding up by the strategy;
  `_config_lookup` says *strategy* or *agenda* in its missing-sentence accordingly. Reference
  edges (`references_to`, `remove`) name a blocking config by its component id, because that is
  the key now; nothing else in that code changed.
- **`workspace_codec.py`.** Encodes the forward shape; decodes either shape by its field set and
  lands both on the component-keyed section. The agenda check that followed the old decode is
  unchanged and now runs on the agenda the binding names.
- **`flow/preflight.py`.** The drift check looks the binding up by the definition's component.
- **`cli/new.py`.** The template's `agenda_id` comment says a cadence is shared. The declaration
  reader (`declarations._apply`) needed nothing: it was keyed by component already.
- **Tests.** `tests/test_an_agenda_is_shareable.py`: three strategies share one agenda and all
  three register, list and reopen; one strategy bound twice is refused naming the strategy and
  the held agenda, and re-binding the same is idempotent; lookup by strategy, and its missing
  sentence; an agenda-keyed document decodes to the same binding and the next write is in the
  new shape. Expectations re-keyed in `test_workspace.py`, `test_workspace_remove_and_force.py`
  (a blocker is *"strategy config 'mom'"*, the component), `flow/test_preflight.py`.

## What this does not do

- No workspace migration verb. A document opens in either shape; the first write is forward.
  Two releases from now the old branch of `_decode` can go.
- `vqapr list strategy-configs` already printed both halves of the relation (`040` observed it
  as a symptom); it is now a plain listing of a two-field binding and is unchanged.
- The near-identical agendas that testbeds declared as the workaround are theirs to remove;
  the package offers `remove agenda` and refuses while a config still names one.

## Validation

```
uv run ruff check src/                            All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs          1308 passed, 14 deselected
PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs  14 passed
```

Branch parent `develop @ 1094ab7d` (record `137` merged), measured: **1304 passed / 14
deselected** fast; **14** slow; showcases 9 of 9.

**Showcases: 9 of 9.** Every showcase completes on this tree; `show_006` and `show_008`
register several strategy configs and are unchanged by the re-keying.
