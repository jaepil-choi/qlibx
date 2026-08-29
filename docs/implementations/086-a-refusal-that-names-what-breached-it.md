# 086 — A refusal that names what breached it

`0.2.0` was built and installed into a clean project, and a first-time user was turned loose on
four scenarios with nothing but the installed package. All four completed. Two blockers came back,
and both are the same shape: a fact the framework computes and the surface discards.

## A constraint refused a run and would not say why

```
SimulationFailure: simulation.callback.intent: economic intent violates projected constraints
```

Which constraint. Which instrument. By how much. None of it.

The `ConstraintFinding` one frame below carries all of it — the constraint's id, what it measured,
the bound, and an `offenders` tuple in its evidence. `_raise_intended_constraint_failure` took no
arguments and threw the finding away.

So the journey did this to diagnose a 20% cap: ran the strategy **again without the constraint**,
read `vqapr.weight` to find the breaching name, then opened the scaffold's Python source. Its own
words:

> A first-time user cannot diagnose *why* a constrained run failed from the CLI output alone —
> they must fall back to inspecting a separate unconstrained run's weight table or reading scaffold
> source, which is closer proximity to internals than the documented surface intends.

Now:

```
economic intent violates 'cap20': A measured 0.900000000000 against a bound of 0.2
(excess 0.700000000000)
```

Offenders are bounded at five with a count for the rest, the same rule `Failure.bounded` applies
everywhere else — a cap breached by four hundred names must not print four hundred.

## `show model` described two kinds of three

Record `085` fixed `show model` for a DataModel and left the constraint falling through to the
StrategyModel loader, where it raised a bare `TypeError` as `stage: "unhandled"`.

That is worse than the DataModel case it replaced. A constraint is the component a reader most
needs to inspect **before trusting it** — it is a rule that will silently reshape their book — and
it was the one kind that could not be inspected at all.

It describes all three now. A constraint reports its `constraint_id`, what it reads, and two
stated answers rather than blanks:

```json
"decides": "the feasible set every instrument's weight must lie in",
"weights": "bounds only; a constraint narrows weights and never proposes them"
```

Empty lists would have been true and useless. *Reads nothing* is the ordinary answer for a rule
about weights, and saying so is different from returning `{}`.

## Both were mine, and both were half-fixes

The first is the defect class this whole run has been closing — a fact computed and dropped before
it reaches the reader, exactly like `roster_digest` in record `070` and `Fill.kind` in `067`.

The second is sharper: record `085` fixed `show model` **one kind short**, a day after the boundary
gates twice caught me shipping a guard narrower than the defect it was written for. The pattern held
even after being named.

## What the journey confirmed

All four scenarios completed on the installed build, and the mission question answered itself
without exploration:

```
stock  269 fills   commission 7049.31 + tax 23362.40   = 12.94 bps
etf    284 fills   commission 7564.26 + tax     0.00   =  3.00 bps
```

`vqapr show dataset ma5-values --limit 10` read back the materialized column. The scaffolds ran
unedited. Every refusal outside the constraint path carried an actionable `fix`.

## Validation

```
uv run pytest tests/ -q -m ""    # 1350 passed, clean
uv run pytest tests/ -q          # 1336 passed, 14 deselected
uv run ruff check src/vqapr/ tests/ showcases/   # 15, compared entry by entry: none introduced
```

`tests/internal/test_public_simulation.py` pinned the old message. It now asserts the constraint
id, the measurement and the bound — a stronger claim than the string it replaced, which would have
passed for any refusal mentioning "projected constraints".
