# 051 — The run record's constraint block has always been empty, and the only test on it asserts the key rather than the value

**Status: CLOSED 2026-09-02 by
[`130-a-declaration-two-consumers-and-a-block-that-was-always-empty.md`](../implementations/130-a-declaration-two-consumers-and-a-block-that-was-always-empty.md).**
Found while repointing the block at monitoring findings for the constraint convergence, not by a
user — which is itself part of the finding.

**Touches:** `src/vqapr/flow/records.py::contract_report`,
`tests/flow/test_run_freezes_its_record.py`.

## What happens

Every run record carries a `contract` block. Its job is to say, per declared constraint, how many
times it was checked and how many times it held — and to refuse to call a constraint `ok` when it
was never checked, because *"a declaration checked zero times is not a declaration that held"*.

**It has never contained anything.** The report walked the run's lifecycle entries like this:

```python
for entry in getattr(result.final_state, "lifecycle_trace", ()):
    evidence = getattr(entry, "evidence", None)
    for item in getattr(evidence, "intended", ()) or ():
        ...
```

A lifecycle entry has two fields:

```python
@dataclass(frozen=True, slots=True)
class LifecycleTrace:
    kind: LifecycleKind
    detail: object = None
```

**There is no `evidence` attribute.** The evidence is the `detail` — `simulation.py` builds
`LifecycleTrace(kind, evidence)` positionally. So `getattr(entry, "evidence", None)` is `None` on
every entry, the inner loop never executes, and `findings` is empty for every run ever recorded.

Confirmed in a live interpreter rather than by reading:

```
fields          : ('kind', 'detail')
has .evidence   : False
-> contract_report inner loop iterates: ()
```

The second `getattr` compounds it: the attribute it reaches for is `intended`, and the evidence
object's field is `constraints`. Either mistake alone would have emptied the block.

## Why it survived

`tests/flow/test_run_freezes_its_record.py` is the only test that touches it:

```python
assert "contract" in record
```

**The key, not the value.** A block that is correctly present and always empty passes that
assertion forever. `record_fields` excludes `contract` from its own value comparison too
(`set(RECORD_FIELDS) - {"contract", "roster"}`), so nothing else looked either.

This is the same shape as `docs/issues/024` — *"a run that declared a table reports none"* — one
layer over. That one was found by a user reading a record and asking why it was empty; this one was
not found, because the block it emptied is the one a user is least likely to read first.

## What it cost

Nothing observable yet, and that is the point: a run whose constraint breached could not say so in
its record, and no reader had reason to suspect the silence. Every claim of the form *"this run
honoured its declared limits"* made from a record was made from an empty block.

## The fix

Two parts, both in record `130`.

1. **Walk the right thing.** The counts come from the monitoring occurrences' reports, reached
   through the run's occurrence traces. This is also where they now belong: the constraint
   contract is a statement about the committed account, and the member that judged the decision
   was removed in the same change (PRD §7.1, architecture §5.7).
2. **Assert the value.** A test drives a run whose book breaches a declared limit and asserts the
   block names that constraint with `ok: false` and a non-zero `checked`.

**The `checked` counts are not comparable across this change** even where the block had been
intended to work: it counted decisions once per callback, and it counts observations once per
monitoring occurrence, which is a different cadence.
