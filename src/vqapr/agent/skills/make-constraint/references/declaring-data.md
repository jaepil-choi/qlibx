# A constraint declares the data it needs

## And fails before producing a result if it is absent

A missing input is never read as "within limits". The constraint declares what it requires, and if
that data is not there the evaluation **fails before a result exists** rather than producing a
verdict nobody can justify.

The built-in benchmark-weight cap is the worked case. A name **confirmed** to be outside the
benchmark has `w_i^index(t) = 0`. But if the membership or the weight data is **missing**, the
evaluation fails — it does not assume zero, which would silently cap that name at 10% on the
strength of a gap in the data.

## The declaration must have an identity

Not a bare pair of numbers. The result has to be able to say **which constraint** compared **which
value** against **which bound**, and by how much it was exceeded — and a nameless threshold cannot
appear in that sentence.

That is also why the three fields of a violation record are enough: which rule, what the limit was,
what it actually was. Requiring every judgement to also transcribe everything it read would make
observation heavy, and heavy observation cannot run often, so it would end up running less.

## A fixed value for a period belongs to a DataModel

A constraint that needs a constant which is fixed for a period — a quarterly index divisor, a
mandate limit that changes annually, a periodically-set risk budget — should **subscribe to it**,
not carry it.

Publish it as a DataModel output and read it here. Two reasons:

- **The value is data with a `available_at`**, and a constant frozen into source has none. When it
  changed, and when that change became knowable, is exactly what a point-in-time evaluation needs.
- **A constraint's source is not a place values are versioned.** Editing the file to change the
  number re-registers the component under a new fingerprint, which reads as a different rule rather
  than the same rule with a new input.

The `make-datamodel` skill covers publishing one.

## Time-varying data is normal here

The benchmark cap subscribes to **time-varying point-in-time** constituent weights, and any
constraint that references an index, a sector map or a mandate schedule will do the same.

Declare it as an input like any other, with a lookback that matches the question: a cross-sectional
bound wants every name on the same instant, which is `CalendarLookback`.

## What to check before you rely on it

After a run, `vqapr.monitoring` should hold rows for this constraint. An empty table means it never
evaluated — a data requirement that was not met, or a strategy that never named it — and that is
not the same as never breaching.
