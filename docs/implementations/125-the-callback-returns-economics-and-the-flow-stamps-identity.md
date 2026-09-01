# 125 — the callback returns economics and the Flow stamps identity

## Why this exists

Two authoring contracts described the same plug-in. `vqapr.authoring.StrategyModel.decide(call)`
returned `Hold | Rebalance`; `vqapr.models.strategy_model.StrategyModel.on_occurrence(context)`
returned `NoDecision | EconomicPortfolioIntent`. The shipped scaffold taught both — `vqapr new
strategy` emitted the first, `vqapr new datamodel` emitted an engine-contract DataModel — so the
product itself presented one kind of extension in two languages.

The owner's reading of the duplication was right on two of three pairs and precisely half-right on
the third, and the half is the whole design:

- **`decide` == `on_occurrence`.** One callback per occurrence, same slot.
- **`Hold` == `NoDecision`.** Literally the same frozen one-field dataclass under two names. The
  adapter's entire contribution was `NoDecision(hold.reason)`. Their only real difference was a
  validation disagreement: `Hold` used `_identifier`, so `Hold(reason="no name scored above zero")`
  was refused while `NoDecision` accepted the identical string.
- **`Rebalance` == the *economic half* of `EconomicPortfolioIntent`.** Three of the intent's eight
  fields — `targets`, `cash_target`, `budget` — are the author's. The other five are facts about
  the run: `intent_id`, `strategy_id`, `source_refs`, `account_version_seen`, `model_state_ref`.

**DataModel already enforced the rule the Strategy side was violating.** `flow/materialize.py`
refuses an author-set `available_at` outright — *"DataModel output must not set package-owned
available_at"* — and `show_002` ships a `ForgingModel` whose only purpose is to demonstrate that
refusal. The Strategy contract *required* the equivalent five fields instead.

**And the Flow was already deriving all five, in order to check the author's copy.**
`_validate_intent_authority` compared `strategy_id`, `model_state_ref`, `account_version_seen` and
`source_refs` against values it computed itself; `_actual_source_refs` performed the identical walk
over `window.accesses` that `strategy_bridge._source_refs` did. Stamping what you already derive is
strictly less code than receiving and comparing it — this change removes a class of authoring error
rather than reporting it.

## What changed

**One decline type.** `NoDecision` is gone; `Hold` is the engine's decline type as well as the
author's, and it took the looser validation, because a reason is prose and not an identifier.

**One decision algebra.** `StrategyModel.on_occurrence(context) -> Hold | Rebalance`.
`models/strategy_model.py` imports both from `vqapr.authoring`, which imports nothing from
`models/` — the direction that carries no cycle, and the one the surface ruling picked.

**The Flow stamps.** `SimulationFlow._stamp_intent` builds the `EconomicPortfolioIntent` from the
decision plus the run's own facts, immediately after the callback returns. The id stays `uuid5`
over `(strategy_id, occurrence_id)`, so a replayed run mints byte-identical intents.
`_validate_intent_authority` loses its four re-derivation comparisons and keeps the one check that
is still about an authored value: a target outside the frozen instrument universe.

**The adapter stopped reaching up.** `_internal/strategy_bridge.py` no longer imports
`vqapr.public` at all — the imports it held (`EconomicPortfolioIntent`, `PortfolioTarget`,
`IntentSourceRef`, `NoDecision`) existed only to build the envelope. `_decide` returns
`prepared.decision`. The file shrank 334 → 288 lines and now does one thing: translate a
`StrategyModelContext` into an authored `StrategyCall`.

That closes the last entry in `test_the_facade_is_not_reached_up_to.py`'s expiring-exemption set —
and closes it the way the file said it could not be closed by deleting anything. Every importer of
`vqapr.public` under `src/` is now a module using the facade for what the facade is for, so the
two-set split and its expiry machinery are gone: **12 → 11 → 5 → 4**, and 4 is `len(PERMANENT)`.

## What did not change

**No workspace code.** `kwam-enhanced-index/vqapr-enhanced-index-3` writes all fourteen of its
strategies against `vqapr.authoring` and never named an intent field. Its DataModels use the engine
contract and are untouched. No component fingerprint moves, so no factor book needs rebuilding and
no parity comparison is owed.

**Declaration form.** `inputs()` vs `requirements()` — and `DataRequirement.of`'s `consumer_id`,
which is the same class of leak (the author hand-writes a component id the framework already knows,
and the scaffold hoists it to a `MODEL_ID` constant to make it bearable) — are deliberately out of
scope. That is the convergence that touches user code, and it is worth measuring separately now
that this one is in.

## Validation

- `uv run pytest tests/ -q` — 1273 passed, 0 failed.
- `uv run pytest tests/ -q -m ""` — the thirteen slow journeys included.
- `uv run ruff check src/` — clean.
- **All nine showcases run.** Five had hand-built intents in their emitted strategy templates;
  each lost its `uuid5` call, its `IntentSourceRef` reconstruction loop, and its `strategy_id`
  string. `show_003`'s strategy shed ten lines of provenance bookkeeping alone.

`tests/acceptance/test_time_002.py`'s provenance test was rewritten rather than deleted. It used to
hand the Flow three intents carrying a wrong `strategy_id`, `model_state_ref` and `source_refs` and
assert each was refused; there is no longer a way to construct one. It now asserts the property the
refusal protected — that a callback which reads its window produces an intent whose provenance,
strategy id, account version and id are all values it never named.

**Two showcases were broken before this change and are fixed here.** `show_006` and `show_008`
fill against `KrxExchange`, which resolves what a fill costs from the project's registered
instrument roster, and neither registered one — both refused at the first order with `no instrument
roster reached '<venue>'`. Unrelated to this work, but they are two of the five showcases whose
strategies it rewrites, and a showcase that cannot run cannot verify anything. They get the same
registration `show_005` already had and `show_004` gained in record `124`.

## What is next

`strategy_bridge.py` and the StrategyModel half of `_internal/models/agent_first.py` still exist,
because two capability surfaces still describe one read: the engine hands a
`StrategyModelContext` with `window.observations(requirement)`, and an authored model expects a
bounded `StrategyCall` with `read(alias)`. Converging those deletes both files.

The DataModel and Constraint halves of `vqapr.authoring` — `DataModel`, `DataCall`, `Output`,
`DerivedRow`, `Constraint`, `ConstraintCall` — have **no execution path through the CLI at all**:
`load_data_model` and `load_constraint` adapt nothing, so a component written against them cannot
be registered. Roughly 110 lines of contract plus the ~120 lines of `agent_first` that serve them
are unreachable. Deleting them is independent of the above and was deliberately not bundled here.
