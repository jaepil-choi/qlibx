# 132 — one StrategyModel

**Advances:** `docs/issues/archive/036` (the last third; M1.4 closes it).
**Step:** M1.3 of `docs/refactoring/2026-09-02-the-convergence-campaign.md`.
**Authority:** `docs/vqapr-architecture.md` §4.4, §5.1, §5.1.1, §9.1 · records `123`, `125`, `130`,
`131`.

## Why this exists

`vqapr.authoring.StrategyModel` and `vqapr.models.strategy_model.StrategyModel` were two classes,
and unlike the DataModel pair (`131`) **both were live**. The scaffold, the shipped sample and two
showcases wrote `decide(call) -> StrategyResult` against the first; five showcases and most test
doubles wrote `on_occurrence(context) -> Hold | Rebalance` against the second; and the loader
wrapped the first in `AdaptedStrategy`, an engine subclass in `_internal/strategy_bridge.py` that
instantiated the author's class **fresh on every callback**, rebuilt every argument in the other
shape, and translated the return. Each thing a Strategy does had two names, and one side of each
pair had to go.

## The rulings, and where each comes from

| pair | kept | because |
|---|---|---|
| `call.previous_state` / `result.next_state` vs `self.memory` | **`memory`** | Architecture §4.4/§5.1.1: memory is the one state both roles share, and the Flow snapshots and restores it in one place. `DataModel` already uses it. A strategy-only second state channel is the shape `036` exists to remove. |
| `result.diagnostics` + `diagnostics() -> DiagnosticTable` vs `self.recorder` + `tables() -> TableSpec` | **recorder** | §5.1 is explicit — *"기록은 context가 아니라 `self.recorder`로 한다"* — and §9.1 declares tables. `TableSpec` already carries the reserved-name check. |
| `account_requirements() -> AccountRequirement(consumer_id, …)` vs `account_history() -> AccountHistoryInput \| None` | **`account_history()`** | `consumer_id` is a framework fact, the same one record `123` took off `DataRequirement`. The Flow already accepted at most one consumer and re-stamped it `"strategy"`. |
| `context.account: AccountSnapshot` vs `call.account: EconomicAccountView` | **the view** | `version` is reserved for the framework (`130`), and the view is what `Constraint.monitor` already sees. |
| `on_occurrence(context) -> Hold \| Rebalance` vs `decide(call) -> StrategyResult` | **`decide(call) -> Hold \| Rebalance`** | With state and rows gone `StrategyResult` had one field left; `125` had already made the engine return the decision bare. The verb: `compute`, `project`, `monitor`, `decide` — what each role does. Architecture §5.1 marks the name illustrative; the design doc says `decide`. |
| fresh instance per callback vs one instance, state restored | **one instance** | §5.1.1's normative content is the property — a fresh instance with restored state decides the same — and the Flow already restores `memory` and payload before every callback. The adapter's mechanism also made the `self.network` §5.1.1 explicitly allows impossible: it would reload on every call. |

## What changed

### One class, on the author's surface

`authoring.StrategyModel(Model)` carries `recorder`, `tables()`, `account_history()`,
`save_payload`/`load_payload` and one abstract member, `decide`. `models/strategy_model.py`
re-exports it, as `data_model.py` does. `authoring.StrategyCall` is the ABC —
`occurrence_id`, `evaluation_time`, `account`, `account_history`, `constraint_bounds`, `read` —
and `StrategyModelContext` is its one implementation, the way the other two contexts are of
theirs. `StrategyResult`, `DiagnosticTable`, `DeclaredAccountHistory` and `AccountRequirement`
are deleted; `AccountHistory` takes the author's `AccountHistoryInput` directly.

`tables()` and `recorder` stay on `StrategyModel` rather than rising to `Model`. Architecture §4.4
gives a DataModel a recorder too, but `flow/materialize.py` does not wire one today, and lifting a
member nothing calls onto the shared base is the defect `131` deleted. They move up when
materialize does. **Open gap, noted here.**

### The account a callback sees is the last valuation's

The bridge scraped a committed NAV out of history and offered no per-instrument marks, which is why
`EconomicAccountView.values` was documented as absent on the strategy side. The Flow now builds the
callback's view with the same `build_account_view` monitoring uses (`130`), from the snapshot and
the last committed `AccountMark`: `nav`, `nav_observed_at` and `values` are real, and `weights()`
means one thing on both sides of a decision. Before the first valuation there is no mark, and the
view says so with `nav=None` rather than a fabricated zero.

### What went with the adapter

- `_internal/strategy_bridge.py` and `_internal/models/` (the whole package). `_internal/` now holds
  `atomic.py` and `filelock.py`, the two file primitives, and nothing with extension authority; the
  boundary test's exemption for `extension/loading.py` is removed.
- `_adapt_authored_strategy` in the loader, and the two deferred imports it needed. The ceiling in
  `test_a_deferred_import_states_its_reason.py` lowered 35 → 23, as that test instructs.
- `_validate_decision_invariants` and `_validated_bounds_cover`: the first re-ran
  `Rebalance.__post_init__`, the second re-checked coverage `project_constraints` enforces.
- `StrategyModelContext.intent()` and `source_refs()`: helpers that built an
  `EconomicPortfolioIntent`, which a callback has been refused for returning since `125`. Nothing
  in `src/` called them; their tests went with them.

### The recorder states the repair

The refusal `docs/issues/archive/019` fixed lived in the adapter's `_validated_diagnostics`. The property
— name what was written, name the method that declares it, name what *is* declared — now belongs
to `InvocationRecorder.append_batch`, which is the only gate left, and the `qa` test for `019` is
rewritten against it.

### Loader and scaffold

`load_strategy_model` accepts the class the scaffold emits with no adapter between them, checks the
arity of `decide`, and passes `required=False` to the requirements check as the other two loaders
do since `130`/`131`. The strategy template returns `va.Hold(...)` / `va.Rebalance.of(...)` and
fits the forty lines `test_authoring_contract.py` holds it to. `SKILL.md`'s example returns the
decision bare and its table paragraph names `tables()` and `self.recorder`.

## Trade-offs

**Thirty-two tests went.** Fast: 1285 → 1253. The strategy half of
`test_agent_first_invocation.py` tested the adapter; `test_context_helpers.py` tested the two dead
helpers; nine unit tests in `test_agent_first_authoring.py` tested the four deleted types; two in
the identity suite asserted the divergence this record ends. What they proved is either unreachable
or now asserted by `public.StrategyModel is authoring.StrategyModel`.

**`authoring` imports three engine modules** — `account.history`, `evidence.tables`,
`evidence.recorder` — so that `AccountHistory`, `TableSpec` and the recorder's type are the
author's. None of the three imports back; `account/history.py` names `AccountHistoryInput` under
`TYPE_CHECKING` only. The module's docstring claim that it is *"pure algebra"* is weaker than it
was, and that is stated rather than hidden: the author's surface now names what the author
receives.

**`pythonpath = ["."]` in the pytest configuration.** `tests/constraints/test_builtin.py` imports
`tests.constraints.support`, which resolves under `python -m pytest` (the cwd is on `sys.path`)
and not under a bare `uv run pytest` from a fresh shell. The gate command is the latter; the
setting makes the two agree instead of leaving the difference to whichever shell ran last.

**The strategy callback's `seen` tuple in `test_time_002` records positions, not a version.** The
assertion — the callback after a fill sees the filled book — is the same; the view has no version
to compare.

## Validation

```
uv run ruff check src/                           All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs         1253 passed, 14 deselected
PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs  14 passed
```

Branch parent `develop @ f6f623c1`, measured: **1285 passed / 14 deselected** fast; **14** slow;
showcases **6 of 9**.

**Showcases: 6 of 9, unchanged.** `show_001`/`show_004` (authored against `decide`) and
`show_003`/`show_007` (against `on_occurrence`) run on the merged contract without a
showcase-specific fix. `show_005`, `show_006`, `show_008` fail exactly as before —
`SingleNameCap.__init__() missing 1 required keyword-only argument: 'benchmark_dataset_id'` —
which is `docs/issues/archive/052`'s remaining half and not this contract's.

Directed checks:

- `public.<X> is authoring.<X>` for all five names in `CONVERGED_NAMES`: `True`. `DIVERGENT_NAMES`
  is gone with its inverse test.
- `tests/extension/test_scaffold_runs_on_real_dtypes.py` drives the emitted strategy scaffold
  through a `StrategyModelContext` built with the `EconomicAccountView` the Flow now builds.
- `tests/extension/test_one_authoring_surface.py::test_load_strategy_model_accepts_an_authored_strategy`
  asserts the loaded object is the author's class, not a wrapper.
