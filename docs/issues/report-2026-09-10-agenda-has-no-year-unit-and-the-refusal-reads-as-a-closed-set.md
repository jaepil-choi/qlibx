# `agenda.every` has no year unit, and its refusal reads as a closed set

**Status: CLOSED by record `244` (2026-09-10, 0.14.2) — the refusal states the grammar (the count is free; the units are d, w, M and m, h), a `y` unit is told `12M`, and the run-backtest skill says the same; no year unit is added.**

| | |
|---|---|
| vqapr version | `0.11.0` |
| installed from | `../../vqapr/dist/vqapr-0.11.0-py3-none-any.whl` |
| reported | 2026-09-10 |
| reporter | `kwam-enhanced-index/vqapr-enhanced-index-3`, agent session |
| python / OS | 3.12 / Windows 11 |

## What I was doing

Migrating a 0.9.0.dev1 tree to 0.11.0. Two of its datamodel runs form the Fama-French annual
sorts, which rebalance **once a year, in June**. Under 0.9 that was an enumerated `sessions:` list
of the eight June formations. 0.10 removed `sessions:`, so the cadence had to be declared as an
`agenda`.

## What I expected

`every: 1y`, by analogy with `1d`, `1w` and `1M`.

## What happened

Refused, and the message names four units:

```python
>>> from datetime import time
>>> from vqapr.public import RunAgenda
>>> RunAgenda(every="1y", at=(time(16, 0),), days_from="equity-daily")
ValidationError: 1 validation error for RunAgenda
  Value error, every must be a count and a unit such as 1d, 1w, 1M, 5m or 1h; got '1y'
```

The same for `1Y`.

**`12M` works.** So does `365d`, `52w` and `4M` — `every` takes an arbitrary count, and only the
UNIT set is closed (`d`, `w`, `M`, `m`, `h`, no `y`). Confirmed by running it rather than by
reading: the annual run declared `every: 12M` fires 8 times over 2019-06-28 .. 2026-06-30 and
writes the same 2,082 rows as the same model under `1M` with a June gate.

```
12M run: ok=True  sessions=8  rows=2082
```

## Reproduction

Reproduced every time:

1. `RunAgenda(every="1y", at=(time(16, 0),), days_from="<any dataset>")` — refused.
2. The same with `every="12M"` — accepted, and a run declared with it fires annually.

## Impact

No wrong numbers, and a working spelling exists. The cost was a wrong design decision that stood
for the length of the migration.

Reading "a count and a unit **such as** 1d, 1w, 1M, 5m or 1h" beside a refusal of `1y`, I took the
list for the set of accepted values — a natural reading when the refusal is the only place the
grammar is stated — and concluded an annual cadence could not be declared at all. So I moved the
schedule **into the model**:

```python
if call.evaluation_time.astimezone(_SEOUL).month != FORMATION_MONTH:
    return []
```

That runs, and it is worse in a way nothing reports. The declaration then says `every: 1M` while
the model produces on one firing in twelve: `check` expands 85 occurrences, the record says
`sessions: 85`, and a reader has to open the component to learn the run is annual. A schedule that
a run declares is a fact about the run; a schedule hidden in a model is a fact about neither.

I found `12M` only because a later question — whether quarterly (`3M`) was expressible — made me
enumerate what `every` accepts. Having found it, both runs now declare `every: 12M` and the gate
stays only as a guard against `start` moving off a June.

## What would have prevented it

Either accepting `1y` as an alias for `12M`, or the refusal saying the shape rather than examples:
*"every is a count and one of the units d, w, M (days) or m, h (intraday); got '1y'. For a yearly
cadence use 12M."* The second is the smaller change and fixes the reading, not just this case —
`2w` and `5d` are equally undiscoverable from the current wording.

`run-declaration.md` has the same shape: it lists `1d | 2d | 1w | 1M` as though those four were
the values, where they are examples of a grammar. A line saying the count is free would make the
whole space visible.
