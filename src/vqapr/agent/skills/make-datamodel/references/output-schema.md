# What `compute()` returns, and how it becomes a schema

## The first session writes the declaration

**The output dataset's `field_types` are read off the first non-empty session's rows** and
registered as the declaration. Every later session must fit that schema, and **nothing is cast.**

So the first session that produces rows is not an ordinary session — it is the one that decides
what the dataset *is*.

## The two failures this produces

**A type that changes between sessions.** A model that returns `int` on a quiet first session and
`float` afterwards passes session one and is refused on session two with
`datamodel.output.schema_mismatch`. The refusal quotes pyarrow and the established schema and does
not guess further.

Decide the type in the code rather than letting the data decide it:

```python
return [
    {"instrument": name, "value": float(v)}   # float on every session, including the empty-ish one
    for name, v in sorted(derived.items())
]
```

**A `Decimal` value field.** Refused at the first session (`datamodel.output.field_type`). A
dataset carries one numeric type per field and DECIMAL is not one a dataset may declare — cast to
`float` at the boundary.

That cast is a real decision, not a formality: it is where exact arithmetic stops. Do it once, at
the return, and keep `Decimal` inside the calculation if the calculation needs it.

## What to return

One dict per instrument. The fields are the ones the materialization spec declares.

**`available_at` is the package's to stamp.** A row that carries one is refused — the model does
not get to say when its own output became knowable.

Return `float` for a continuous quantity and `int` for a count. Those are the two that read
naturally; `VARCHAR` and `BOOLEAN` are available and are worth a comment when used, because a
string field in a computed panel usually means a label that would be better as its own dataset.

## An empty session is fine

A session that produces no rows is not a failure and does not set the schema — the *first
non-empty* session does. A model that legitimately has nothing to say early on can return an empty
list.

Be aware of the interaction: if the first several sessions are empty, the schema is set later than
you might assume, and a type inconsistency that would have failed on session two instead fails
much later in the run.

## Reading it back

Once the run completes, the output registers as an ordinary dataset. `vqapr show dataset <id>`
reads it, and any component may declare it as an input — **which is the point**: one model's
output is the next model's input, with no publishing step between them.
