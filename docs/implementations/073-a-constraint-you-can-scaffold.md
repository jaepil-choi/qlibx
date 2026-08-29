# 073 — A constraint you can scaffold

The run-spec template offered an optional `constraints:` list. There was no `vqapr new constraint`,
`register --help` named only `datamodel` and `strategy`, and the shipped skill contained the word
`constraint` zero times.

So the only way to learn the contract was to register an empty subclass and read the refusal:

```
Can't instantiate abstract class without an implementation for abstract methods
'constraint_id', 'evaluate', 'project', 'requirements', 'validate_intended'
```

Five members, no documented signature or return type — and `project` is a **semantic** contract,
not a shape one. Guessing it wrong produces a backtest that looks correct and is not. A
first-time-user agent asked for a 20% single-name cap correctly refused to guess, and the
requirement went unmet.

## The scaffold is a position cap

Not a stub. A position cap is what the mission actually wanted, it needs no dataset, and it
exercises all five members meaningfully — a template that raises on its first callback teaches
nothing.

`project` gets the longest docstring, because it is the member nobody could guess:

> **The feasible set.** Return the lower and upper weight bound for EVERY instrument in
> `instruments`. Not the offenders, not a correction — the box the optimiser must stay inside.
> Both bounds are mandatory for every name: the evaluator rejects a projection that does not cover
> every window instrument on both sides, because a missing bound would silently widen the feasible
> set rather than fail.

`validate_intended` and `evaluate` are separated in prose too, since the difference is easy to miss:
the first judges the weights a Strategy proposed, the second judges the book that was committed and
marked, and they differ whenever execution does not fill what was intended.

**`constraint_id` is fixed to the id the scaffold was given**, so the crash record `068` closed
cannot be reproduced by anyone who starts here:

```
$ vqapr register constraint cap20b cap20.py
component.load.constraint_id_mismatch: registered as 'cap20b', constraint_id returns 'cap20'
```

## Four plumbing sites, and a fifth that was not on the list

The completion gate's architect lane named four places a third authored kind has to appear, and all
four were real: `_KINDS` in `cli/new.py`, `_TEMPLATES` plus `render()` in `extension/scaffold.py`,
`AUTHORED_KINDS` in `cli/register.py`, and the `_sole_subclass` base map there, which raises
`KeyError` on a kind it does not know.

A fifth turned up by running it: `_DECLARATION_KIND` in `cli/new.py`, read while emitting the
companion `.yaml`. Missing it produced `KeyError: <ComponentKind.CONSTRAINT: 'constraint'>` as
`stage: "unhandled"` — the failure shape this whole slice exists to remove, from a table nobody
listed. Its docstring now says the three tables are the same three kinds.

**`--dataset` became per-kind.** A DataModel and a StrategyModel are defined by what they read; a
Constraint is a rule about weights and reads nothing — the shipped `NoShort` returns an empty
`requirements()` for exactly that reason. Demanding a dataset would have made an author invent one
to scaffold a rule that never opens it.

## The class name is now parsed, not split

`new.py` derived the emitted class as `source.split("class ", 1)[1].split("(", 1)[0]` — the first
occurrence of `"class "` **anywhere in the file, including inside a docstring**. This template's
prose contains "register an empty subclass and read", and `subclass and` contains that substring,
so the emitted declaration named half a paragraph as its `object_name`. It registered, and failed
one command later with an `AttributeError` quoting the paragraph.

It is an `ast` walk now. `register.py` already parses its equivalent with `ast` and says why —
*"Found by parsing rather than importing"* — and this is the same fact about the same file.

## It caps size, and says nothing about sign

The first version of this template did not hold together, and the completion gate's architect lane
found it: `project` returned a lower bound of `0`, forbidding a short outright; `validate_intended`
tested the **signed** weight against `CAP`, so a proposed `-0.30` was not an offender; and
`evaluate` tested the **absolute** weight, so the same `-0.30` was one. For `{A: +0.10, B: -0.30}`
with `CAP=0.2`, the projection refused it, the intent check passed it, and the monitoring check
failed it. Three members of one rule disagreeing about one book -- in the scaffold that exists
because this contract cannot be guessed.

It is a pure size cap now: `project` returns `-CAP`/`+CAP`, and both checks measure `abs(weight)`.
Shorting within the cap is permitted, and forbidding it is a separate rule.

That is how the shipped pair already divides them -- `SingleNameCap` caps size and measures on
`abs`, `NoShort` tests the sign and nothing else -- and constraints intersect, so declaring both in
a run spec gives long-only-with-a-cap without either rule knowing about the other. Folding a
no-short into a cap's `project` taught the opposite, silently.

## `--cap`, and why the test asserts both directions

`--cap` defaults to `0.2`, the mission's number, and is exposed as a flag the way `--lookback` and
`--field` already are for a strategy: the marked place to change should not require editing the
file.

The end-to-end test asserts the rule **bites** and **permits**, because either alone is passable by
a broken constraint. Against the one-instrument fixture the scaffold strategy proposes 100% of the
book in a single name, which a 20% cap forbids, so the run refuses by name — `stage != "unhandled"`
is asserted, because a bound constraint is a decision and not a crash. Scaffolded again with
`--cap 1.0`, the identical file runs to `ok:true`. A constraint that refused everything would pass
the first assertion and fail the second.

## Validation

```
uv run pytest tests/ -q      # 1311 passed, 14 deselected
uv run ruff check src/vqapr/ tests/ showcases/   # 15 findings, the same list as 7ae3d3af
```

`tests/cli/test_commands.py::test_new_constraint_emits_a_rule_that_registers_and_runs_unedited`
covers: scaffolding with no `--dataset`; all five members present in the emitted source rather than
left to a `TypeError`; `project`'s contract stated; registration through the emitted declaration;
the mismatch refusal proving the scaffold cannot reproduce `068`'s crash; and both run directions.

Two lint findings I introduced in the KRX journey file were caught by diffing ruff's output against
`7ae3d3af` entry by entry rather than by comparing counts, and fixed.
