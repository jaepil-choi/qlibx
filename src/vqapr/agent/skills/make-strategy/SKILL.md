---
name: make-strategy
description: Writes and validates a project-local vqapr StrategyModel — the code that turns signals into signed weights and intended positions, including instance memory, lookback warm-up, alpha budgets, and ensembles over other strategies. Use when the user wants to build, code, or test a trading strategy, alpha, or signal; mentions momentum, reversal, long-short, enhanced index, or ensemble; wants a factor's return series such as Fama-French SMB or HML, whose legs are value-weighted sorted portfolios; or asks how a strategy carries state between decisions.
---

# Write a vqapr StrategyModel

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## Start from the scaffold

```bash
vqapr new strategy <id> --dataset <dataset-id>
```

writes a `.py` that **runs as written**, plus the `.yaml` that registers it. Start there rather
than from a blank file: the scaffold is generated from the contracts the package enforces, so it
cannot drift from them, and this skill deliberately does not repeat its structure.

**Read the emitted file before reaching for `help()`.** It shows, where each one goes, the pieces
an author otherwise looks up: a second dataset and the `.current()` read of one value per name (in
`inputs`), state across callbacks (`self.memory`), and a table of your own (`tables()` and
`self.recorder.append` — on `self`, not on `call`). Its log records what was **decided**. A fill's
price, quantity and cost are read from `vqapr.fill` afterwards (`vqapr export` writes
`fills.csv`): a fill comes after its callback, and no callback follows the run's last fill, so a
strategy that logs fills from its callbacks loses the last day's.

Register it either way — the YAML with `vqapr register <file.yaml>`, or the source directly:

```bash
vqapr register strategy <id> <file.py>
```

The file must define **exactly one** `StrategyModel` subclass. Zero and two are both refused, and
the refusal says which.

## One strategy is one file

Re-registering an edited file keeps the id and records a new fingerprint, and a reader of the run
record sees that as **tuning** the same strategy.

A variant you do not mean as a tuning — another arm of a methodology, a different signal, even the
same class with one constant changed — is **a new file under a new id**. There is no config
channel, so which of the two you mean is a decision only you can make, and it is the decision that
determines whether the record reads as one strategy improved or two strategies compared.

**One file is also what is loaded.** vqapr loads the file by its path, so its directory is not on
the import path: `import helper` of a `helper.py` beside it is refused
(`component.construction_failed`, and the `fix` says why). Code several strategies share — a base
class for six portfolio legs, a list of dates — goes in a package installed in the environment, or
on `PYTHONPATH`; a leg that subclasses such a base registers by either route. The fingerprint
covers the strategy's own file only, so keep what you tune in that file.

## The shape

```python
from vqapr import public as vq

class Momentum(vq.StrategyModel):
    def inputs(self):
        read = vq.DatasetInput(
            dataset_id="prices", fields=("close",), lookback=vq.RowsLookback(rows=20)
        )
        return {"prices": read}

    def decide(self, call):
        window = call.read("prices", "close")   # instants x instruments
        ...
        return vq.Rebalance.of(long={"A": 2, "B": 1}, invested="0.9")
```

The author declares what it reads and returns what it wants. **Identity, provenance and the
account version are the framework's** and are never written by hand.

`inputs()` is evaluated at registration and at preflight, **before** any memory is restored and
before a run's `initial_model_memory` is applied — so what a model reads cannot depend on either.
A family of settings that changes the reads is a family of registered components, one file and one
id each.

What the read verbs hand back, and **the lookback member that is silently wrong for a
cross-sectional question**, are in [references/reading-inputs.md](references/reading-inputs.md).
Read it before declaring a lookback: the wrong one passes every check.

## The four things to get right

**Memory.** `self.memory` is strict JSON, restored before every `decide()` and snapshotted after.
**One instance serves the whole run** — never construct a new one per callback. Anything that will
not fit strict JSON goes through `save_payload` / `load_payload`, and preflight proves that pair
before the first callback in a way that catches the two usual mistakes.
[references/memory-and-payload.md](references/memory-and-payload.md).

**`Rebalance.of` versus `Rebalance.signed`.** `of` splits `invested` **evenly** between the two
sides, so it tops out at half a textbook long/short book and **cannot express "more shorts than
longs"**. When the signal decides the split, `signed` is the one you want.
[references/rebalance.md](references/rebalance.md) — read it before writing any short.

**Conviction, not weights.** `long={"A": 2, "B": 1}` means A is liked twice as much as B.
Normalising, rounding onto the canonical grid and balancing against cash is the package's
arithmetic. **You never make weights sum to one by hand.**

**A short is declared by which mapping a name appears in**, never by a negative number — except in
`signed`, where a negative number *is* the short. Mixing the two conventions is the error the
reference exists to prevent.

## Declining is a decision

```python
return vq.Hold(reason="no name scored above zero")
```

The reason is prose a human reads. Spaces are fine; only an empty string is refused. A warm-up
callback that has not seen enough history yet is a `Hold`, not a failure.

## Before you hand-roll portfolio arithmetic

`vqapr.public` exports about 160 names and **the CLI help does not list them**.

```python
import vqapr.public as public
[name for name in dir(public) if not name.startswith("_")]
```

A first-time journey hand-rolled 30/70 breakpoints and a bucket assignment that were already in
the package, and four of that journey's findings turned out to be answerable from this one module.
Check it first: [references/public-helpers.md](references/public-helpers.md).

## A factor is a portfolio

A factor's return — SMB, HML, momentum, any long-short spread — is the return of the portfolios
that mimic it. **Each leg is a StrategyModel in its own run, and the factor is arithmetic on their
daily NAV returns afterwards.** A DataModel cannot give it: it returns a value per instrument, and
a return needs something held. The Fama-French 2×3 recipe, its code, and the two things it cannot
express exactly are in [references/factor-portfolios.md](references/factor-portfolios.md).

## Composing strategies

A strategy can subscribe to another strategy's stored result — that is how an ensemble is built,
and it needs no publishing step in between.
[references/composition-and-budget.md](references/composition-and-budget.md) also covers budget
semantics: **an under-allocated result is never topped up for you.**

## Validate before you believe it

```bash
vqapr register strategy <id> <file.py>
vqapr check <run-id>
```

Registration validates the contract; `check` proves the run it is named in. A component that
imports and loads is **not** thereby compatible — being findable is not being valid.

If a declaration has drifted far from the contract, do not repair it. Generate a fresh one with
`vqapr new` and move your logic in; editing a correct template is faster than repairing a wrong
one.

## Stop condition

`vqapr register` accepted the file, `vqapr check <run-id>` returns `ok: true`, and the user has
agreed which of "a tuning" and "a new strategy" this file is.

---

A refusal carries its own status, stage and cause, plus `fix`, `requirement`, `observed` and
`source` — read it rather than looking for it here. A raise from your own file gives `source` the
file and the line, `cause.origin: "user"` and **status 502** — that is your code to fix, not a
defect to report. Status **500 is a vqapr defect**: do not work around it, report it with the
envelope. **503 is the machine** — retry unchanged.
