# 191 — The values two packages exchange live in `domain/`, and two cycles die

**Date:** 2026-09-08. **Branch:** `develop` (layering campaign M2;
`docs/refactoring/2026-09-08-the-layering-campaign.md`, ExecPlan
`.agent/plans/active/layering-campaign.md`). **Reported by:**
`tests/boundaries/test_the_layers_hold.py`, armed by record `190` with these edges in `OPEN`.

## Why

Three of the four cycles the campaign measured have one cause, and it is not that the packages are
tangled. It is that a **value** two packages pass to each other was filed under the package that
happens to construct it:

- `account/account.py` imported `exchange.fills.Fill` to commit one; `exchange/venue.py` imported
  `account.snapshot.AccountSnapshot` to execute against one. Neither is wrong on its own, and
  together they are a cycle with no deferral hiding it.
- `exchange/venue.py` and `venues/krx.py` imported `orders.batches.OrderBatch`;
  `orders/planning.py` imported `exchange.listings.ExchangeRulesView`. That cycle *was* hidden --
  `exchange/execution_table.py` deferred both imports into `accepted_requests`, which is precisely
  the mechanism `test_a_deferred_import_states_its_reason.py` exists to cap.

`domain/values.py` has said what to do about this since record `162`:

> Portable values every layer shares and none owns.

`Mark` and `MarkBatch` moved there for exactly this reason. The rule was simply never applied to the
rest, so this record applies it: **a value two packages exchange lives in `domain/`; a package holds
behaviour.**

## What

**Four modules moved to `domain/`, one to `exchange/`, one package deleted.**

| from | to | what it holds |
|---|---|---|
| `exchange/costs.py` | `domain/costs.py` | `FillCost`, `SideCost`, `FREE` |
| `exchange/fills.py` | `domain/fills.py` | `Fill`, `FillBatch`, `ZeroDealtReason` |
| `orders/batches.py` | `domain/orders.py` | `OrderRequest`, `OrderBatch`, `ZeroDeltaDiagnostic` |
| `account/snapshot.py` | `domain/account_state.py` | `AccountSnapshot`, `AccountMark`, `AccountState` |
| `orders/planning.py` | `exchange/planning.py` | `plan_orders` |

`costs.py` moved whole rather than being split. `Fill.cost` is a `FillCost` and `SideCost.charge()`
builds one, so the two are a pair; leaving `SideCost` behind would have bought nothing but an
`exchange -> domain` edge and a file holding half a concept. That `SideCost` is declared on a
venue's `TradeRule` does not make it behaviour — it is the rate, and the rate is a value.

`account_state.py`, not `accounts.py`: the plural would read as the `account/` package's twin, and
what the module holds is one thing, the detached state execution planning is handed.

**`orders/` is deleted.** Once its values were in `domain/`, the package was one function.
`plan_orders` converts complete targets into orders **against a venue's rules** — it takes an
`ExchangeRulesView` and returns what a venue will accept — so it belongs beside the rules it reads
rather than in a package of its own. `tests/orders/test_planning.py` moved to
`tests/exchange/test_planning.py` with it.

**The two deferred imports in `exchange/execution_table.py:534-535` are hoisted to the header.**
They were deferred because the cycle was real; the cycle is gone rather than deferred, which is the
only acceptable reason to remove one.

**Both ratchets tightened in this commit, which is what they are for.**

- `CEILING` 12 -> 10, with the reason recorded in its docstring beside the earlier steps.
- `OPEN` loses `("account", "exchange")` and `("exchange", "orders")`, and `orders` leaves `LAYERS`
  because the node no longer exists.

`("account", "authoring")` stays open and its annotation is corrected from M2 to M3.
`account/history.py` still reaches `authoring.AccountHistoryInput` under `TYPE_CHECKING`, and the
right answer is not to move the value to `domain/` — it is that `AccountHistory` (what a
`StrategyModel` receives) and `AccountHistoryInput` (what it declares) are one contract and belong
in one package. That happens in M3 when `authoring/` exists, and it deletes the deferral rather
than relocating it.

## Trade-offs

**`domain/` grew by four modules, to eleven.** That is the cost of the rule, and it is the right
cost: a package that holds only behaviour can be read for what it decides, and a value in `domain/`
can be handed to any layer without dragging one along. The alternative — the status quo — pays for
a smaller `domain/` with cycles that Python cannot report.

**Every one of these is a breaking import path.** `vqapr.exchange.fills`, `vqapr.exchange.costs`,
`vqapr.orders.*` and `vqapr.account.snapshot` are gone. `vqapr.public` re-exports every affected
name (`Fill`, `FillCost`, `SideCost`, `AccountSnapshot`, `ZeroDealtReason`, ...), so the documented
surface is unchanged and the nine showcases needed no edit; 27 files under `tests/` did.

**`plan_orders` in `exchange/` invites the reading that planning is the venue's.** It is not: the
function is pure and the venue supplies only rules. The module docstring already says so
("Deterministic execution-time conversion from complete targets to venue orders"), and
`exchange/venue.py` remains the only thing that executes.

## Validation

- `uv run ruff check src/` — clean. Import ordering was fixed only in files this change touched;
  `ruff --fix` also reformatted 19 unrelated test files with pre-existing `I001`, and those were
  reverted rather than carried in this commit.
- `uv run pyright` — `0 errors, 0 warnings, 0 informations`.
- `uv run pytest tests/characterization/test_refusal_codes.py -q` — 10 passed. **0 codes lost**,
  which is the gate this milestone had to clear: four modules changed file, and every refusal they
  raise still resolves.
- `uv run pytest tests/boundaries/ -q` — 37 passed, after both ratchets were tightened. Before
  tightening they failed exactly as designed: `assert 10 == 12` and *"these OPEN entries no longer
  violate anything: [('account', 'exchange'), ('exchange', 'orders')]"*.
- `uv run pytest tests/ -q` — 1578 passed, 2 failed: the two pre-existing
  `tests/agent/test_the_release_records_what_it_ships.py` failures recorded in record `190`,
  unchanged in count and identity.
- `uv run pytest tests/ -q -m ""` — 1603 passed, 2 failed in 339 s: identical in count and
  identity to the pre-M1 baseline. The slow set adds no failure.
