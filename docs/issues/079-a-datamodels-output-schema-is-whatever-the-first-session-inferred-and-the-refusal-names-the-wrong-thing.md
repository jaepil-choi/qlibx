# 079 — a datamodel's output schema is whatever the first session inferred, and the refusal names the wrong thing

**Status:** OPEN. Found 2026-09-04 by `kwam-enhanced-index/vqapr-enhanced-index-3` (A1), building
an annual fundamentals dataset whose `compute` returns `Decimal`. The run died eight sessions in.
Reproduced here against this branch with two ratios computed by ordinary division under the default
decimal context.

**Touches:** `src/vqapr/flow/datamodel.py:250-270` (`DataModelOutput.append`: the schema is captured
from the first non-empty session's inferred table and imposed on every session after it, and the
`type_drift` refusal built from the failure).

## What happens

`append` writes one session at a time:

```python
table = pa.Table.from_pylist([dict(row) for row in rows], schema=self._schema)
...
if self._schema is None:
    self._schema = table.schema
```

For a `Decimal` value field, pyarrow infers `decimal128(precision, scale)` from the values it is
given. A Python `Decimal` is arbitrary-precision, so the same expression produces different scales
on different sessions — a ratio that lands on 27 decimal places in one formation year and 28 in the
next is the ordinary case, not a pathology:

```
a = Decimal(402192) / Decimal(391688)   ->  1.026817262719307203692735034   (scale 27)
b = Decimal(1) / Decimal(3)             ->  0.3333333333333333333333333333  (scale 28)

session 1 (a alone) -> schema decimal128(28, 27)
session 2 (b, under that schema) -> ArrowInvalid: Rescaling Decimal value would cause data loss
```

The first session's inference becomes the dataset's contract, and nothing declared it. The author
never wrote a precision, cannot see one, and `value_fields` — the one place they say what the
dataset holds — carries names only (`flow/materialize.py:100-135`).

## The refusal names something that did not happen

```
[datamodel.output.type_drift] every session's rows must carry one type per value field
observed: ArrowInvalid: Decimal type with precision 28 does not fit into precision inferred
          from first array element: 29
fix: return the same scalar type for each field on every session; the first session's types
     are the dataset's
```

The scalar type was `Decimal` in all eight sessions. `requirement` and `fix` both say "type", and
following the `fix` — making every field return the same type — changes nothing, because it was
already true. The one accurate sentence in that envelope is pyarrow's own, carried in `observed`;
the reporter found the cause in five minutes once they stopped believing the layer above it, after
fifteen spent obeying it.

Note the shape: the structured diagnosis is not merely unhelpful, it **contradicts** the raw error
it wraps. `077` closed the case where a judgment that could not look reported as passed; this is a
refusal that could not name its cause and named one anyway.

## What to do

In order of preference:

1. **Let the declaration fix the schema.** A `Decimal` value field could carry a declared
   `decimal128(38, s)` in `value_fields`, so the dataset's type is something the author wrote and
   can read back. That is a surface change and wants an owner ruling.
2. **Failing that, say precision.** `requirement` and `fix` must name the concept that actually
   drifted, and the `fix` must be actionable: *"the first session fixed this field at
   decimal128(28, 27); this session needs scale 28. Declare a precision, or return `float`."*
3. **At minimum, stop asserting.** Where the framework cannot tell type drift from precision
   drift, raise pyarrow's message unwrapped. An accurate fact with no explanation beats a wrong
   explanation — the standing rule `077` was closed on.

The workaround the reporter used — returning `float` for continuous quantities, since a DOUBLE has
no precision to infer — costs accuracy beyond 16 significant digits and is the right answer for
most panels. It should be in the skill either way, but it is not a substitute for 1 or 2: an author
who genuinely needs `Decimal` (money, exact ratios) has no path today.

## Related

`077` (a diagnosis that states what it did not verify), `078` (the same shape in order planning),
record `137` (Panel), and `023`/`027` (what a dataset's declaration does and does not say).
