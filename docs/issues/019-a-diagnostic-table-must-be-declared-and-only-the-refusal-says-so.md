# 019 — A diagnostic table must be declared, and only the refusal says so

**Status when filed:** open. Found 2026-08-30 by the final first-time-user journey in
`kwam-enhanced-index/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-007**,
`slowed`, and it cost a wasted run.
**Touches:** `src/vqapr/_internal/models/agent_first.py:356`, the `vqapr new strategy` scaffold in
`src/vqapr/cli/new.py`, and the installed skill's run-reading section.

## What led the reporter to expect otherwise

Emitting a small table from `decide()` — how many names landed in each of the six Fama-French
portfolios — via `StrategyResult(diagnostics={...})`. Two sentences made that read as sufficient.

The skill's run-reading section:

> Every run records three tables, plus any the model formed

which reads as: form one and it is recorded. And `StrategyResult`'s own docstring, which introduces
`diagnostics` as a convenience:

> `next_state` and `diagnostics` default to the empty case, because most strategies carry no
> cross-callback state and emit no diagnostic tables

framing the empty default as saving typing, not as a declaration you must override.

## What happens

```json
{"code": "simulation.callback.intent.ValueError",
 "observed": "decide() emitted undeclared diagnostic tables: ['ff3.formation']",
 "requirement": "the guarded boundary must complete without raising"}
```

No `fix`, no `explain`, no `source` — **016** again. The message names the problem precisely and
says nothing about the remedy: not the method to override, not the type to return, not where to
look.

## The remedy exists and is documented in exactly one place

A second `StrategyModel` member:

```python
def diagnostics(self) -> tuple[DiagnosticTable, ...]:
    return (DiagnosticTable(table_id="ff3.formation",
                            semantic_fields=("portfolio", "names", "market_equity")),)
```

`StrategyModel.diagnostics.__doc__` states it exactly — *"Declare every diagnostic table this
Strategy may emit. Empty by default."* — and nothing routes a reader there. The scaffold
`vqapr new strategy` emits does not mention `diagnostics` at all, in code or in comment. The skill
does not mention it. The failure that enforces it does not name it.

The reporter found it by `inspect.signature`/`getdoc` on every member of `vqapr.authoring
.StrategyModel`, and it worked first time. That is the same enumerate-the-module move that found the
answers to 017, 020 and 021 — four findings in one journey resolved by introspection rather than by
documentation.

## The behaviour is right

Declare before you emit is the same rule as `DataRequirement`, and the docstring is correct. This is
`message` and `docs`, not `code`. What is missing is the sentence connecting the refusal to the
method that satisfies it.

## What closes it

Any one of these alone would have saved the run; the first is the cheapest and the last is the most
durable.

1. A `fix` on the refusal: *"declare it by overriding `StrategyModel.diagnostics()` to return a
   `DiagnosticTable` for each table `decide()` may emit"*.
2. The `vqapr new strategy` scaffold carrying a commented-out `diagnostics()` returning an empty
   tuple, the way it already carries the members a strategy must have.
3. The skill's *"plus any the model formed"* becoming *"plus any the model declared and formed"*,
   with the method named.
