# 030 — An execution price is the one mandatory registration

## Why this exists

A registration asymmetry the framework holds but never stated:

- **An observation dataset is optional.** A Strategy may declare no `DataRequirement` and return
  `NoDecision` forever. Running it is still a run.
- **An execution price is not optional.** Every run values its book and fills against the prices a
  venue published, so the execution input is required from the start — even for the Strategy that
  reads nothing.

`RunDefinition` types `exchange` and `execution_input_id` as `... | None`, `preflight_run` wrapped
its exchange work in `if definition.exchange is not None`, and only `run()` refused:

```
RunDefinition(no exchange, no execution_input)  -> accepted
preflight_run(...)                              -> PASSED, frozen.execution_input = None
run(...)                                        -> ValueError: public run requires a frozen
                                                   Exchange authority
```

Two things are wrong with refusing there.

**`preflight_run`'s own docstring promises a "run-ready declaration".** Returning a `FrozenRun` that
`run()` always rejects contradicts it. `FrozenRun` has exactly one consumer — `run()` — so a frozen
run without an execution price is never useful to anybody.

**The refusal was untyped.** A bare `ValueError` has no `as_dict()`, so the CLI reported
`stage: "unhandled"` — which tells an agent the framework broke when the truth is the declaration
was incomplete. This is the same defect class as record 029.

## The part that was actually dangerous

Both `_validate_instrument_universe` and `_validate_initial_account` lived **inside** that
`if definition.exchange is not None` block. A definition naming an instrument the Exchange does not
list, or an initial account incompatible with its mode, was frozen without either check running.
The declaration was never examined, and the run failed later for an unrelated-looking reason.

Refusing up front makes both checks unconditional. `test_a_run_without_an_execution_price_is_refused_before_it_is_frozen`
pins that: with an execution input supplied, an unlisted instrument now raises
`preflight.universe.unlisted_instrument` — reachable only because the definition got that far.

## Why not somewhere else

**Not in `RunDefinition`.** It is a pure value object with no workspace, so it could only raise a
bare `ValueError` — the untyped-refusal problem again. It is also legitimately built in-process by
callers who supply the pairing another way; it already enforces that exchange and execution input
are declared *together*, which is the invariant it can see.

**Not in `run()`.** That is where it already was, and it is too late by exactly one step.

`preflight_run` is the gate that promises run-readiness, holds the workspace, and already raises
typed `VqaprError`s for `preflight.account` and `preflight.universe`. `preflight.execution` joins
them.

## Trade-offs

- **`preflight_run` no longer freezes an exchange-less definition at all**, so a caller who wanted
  a frozen declaration purely to inspect agenda merging must now supply an execution input. That is
  the point: such a `FrozenRun` could not be run, and no caller in the repository wanted one — the
  two tests that did were asserting drift and slice behaviour, and now get a complete declaration.
- **The duplicated execution parquet is not addressed, because it is not a defect.** An execution
  table must carry `is_tradable`, and its `trade_at` is a different instant from an observation's
  `available_at`. Sharing one physical file would force those two instants to be the same value.
  The separate file is the design.

## Validation

```
uv run pytest -q                  586 passed (from 584)
uv run ruff check src/ tests/     clean
G-4 result invariance             64 fields identical
```

Two tests in `tests/flow/test_preflight.py`. `_setup` now supplies execution authority by default
with a `with_execution=False` switch for the refusal tests, because a definition without one is not
a run any caller could have had.
