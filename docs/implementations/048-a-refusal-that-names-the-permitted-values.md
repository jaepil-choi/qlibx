# 048 — A refusal that names the permitted values, and a scaffold for the declaration that needed it most

Measured on a fresh reader who registered a dataset and two components successfully, then spent
**16 `register` invocations** on a single `execution_inputs` declaration and never landed it.

## 1. A wrong enum value was an unhandled crash

`cli/register.py` built the fill convention with a raw lookup:

```python
FillSelector[str(_required(fill, "selector", name=f"{name}.fill")).upper()]
```

A miss raises `KeyError`, which reaches the envelope as `stage:"unhandled"`, `failures: []`, and a
traceback file. The reader guessed six times — `close`, `market`, `close_price`, `last`, `vwap`,
`next_open` — and every attempt returned the identical crash with no new information.

**Every guess was price vocabulary. The members are `SAME_DAY` and `NEXT_ELIGIBLE`, which are
scheduling words.** The field sits directly beside `trade_price`, so `selector` reads as "which
price is selected" when it actually means "which session is filled in". Guessing cannot converge on
a vocabulary the field name argues against — no quantity of attempts would have found it. That is
what makes this different from an ordinary missing-value error and why the refusal has to carry the
list rather than merely reject the input.

The correct pattern already existed **three functions away in the same file**: `_role` caught
`KeyError` and named the permitted values. It was generalized into `_enum`, and both callers now
use it. The permitted members ride in `examples` as well as in `requirement`, so an agent can
branch on the array without parsing prose.

```
declaration.read.value_not_permitted
  requirement: execution_inputs.krx.fill.selector must be one of: same_day, next_eligible
  examples:    ["same_day", "next_eligible"]
```

Six attempts becomes one.

## 2. `execution_inputs` had no scaffold, and it is the deepest thing `register` accepts

Ten required keys across two nested blocks (`table` with six, `fill` with four). With no template,
the reader discovered them one refusal at a time — ten structured round trips before even reaching
the enum crash. Record 047 added `vqapr new dataset` for exactly this reason and stopped there;
`execution-input` is the declaration that needed it more, because it nests.

`vqapr new execution-input --out <path>` now emits all ten with comments, and **the emitted
`selector` is a valid member rather than a placeholder** — a template that emits a value the
validator rejects would reproduce defect 1 through the fix for defect 2. A test pins the emitted
value against `FillSelector.__members__` so the two cannot drift.

The comment states what `selector` means, since the name misleads:

```yaml
selector: same_day            # SCHEDULING rule, not a price choice. One of:
#   same_day       fill at the instant selected within the same session
#   next_eligible  fill at the next session where the name is tradable
```

## 3. A scaffold could write a file `register` would refuse

`vqapr new datamodel alpha --out comp` wrote a file named `comp`, reported `ok:true`, and then
`register` refused it because a component is imported and an extensionless file is not a loadable
module. The default path already appended `.py`; only an explicit `--out` was taken verbatim.

The failure landed one command away from the flag that caused it. `--out` is now held to the same
rule as the default.

## What was not changed

The reader also hit two things left alone deliberately:

- **`available_at` needs a convention the framework cannot supply.** They localized the naive date
  column to the KRX close using outside knowledge of the venue's session times. That judgement is
  the user's by design; record 047's template and the `available_at_not_tz` refusal already say so.
  Recorded as `slowed`, correctly.
- **A Windows console renders the source's Korean column headers as mojibake** unless output is
  forced to UTF-8. That is the console's code page, not vqapr's writing — `emit()` already writes
  UTF-8 bytes. Recorded, not acted on.

## Validation

```
uv run pytest -q            691 passed   (687 before, +4)
uv run ruff check src/ tests/   clean
```

The four new tests pin the measured failures: a bad enum value yields
`declaration.read.value_not_permitted` naming both members, the execution-input template carries
all ten keys, its emitted selector is a real `FillSelector` member, and a scaffold with an
extensionless `--out` still produces a `.py`.

Manually: the same declaration the reader could not register now refuses once, names both permitted
values, and accepts the corrected value.
