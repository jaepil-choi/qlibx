# Reading the envelope

Every vqapr command returns exactly **one line of JSON to stdout**, and success and failure have
the same shape on purpose: an agent has one parsing path instead of two.

Advisory lines — a skill installed from a different vqapr, say — go to **stderr**, so stdout stays
one document.

## Contents

- The two shapes
- Reading a refusal: `fix` first
- The three things to branch on: `status`, `stage`, `cause`
- When `examples` is empty

## The two shapes

The shape is always:

```json
{"ok": true, "stage": "...", ...}
```
or
```json
{"ok": false, "stage": "...", "mutation": false, "retry_precondition": null,
 "correlation_id": "...", "failures": [...]}
```

**`ok`** — did the command succeed?
**`stage`** — which operation was under way when the command stopped (the closed set is listed
below)
**`mutation`** — whether anything was written before the refusal; `retry_precondition` says what
must hold before retrying when it was
**`correlation_id`** — quote it when you report the refusal anywhere
**`error`** — the exception as one line, `Type: message`; the whole traceback is in each
failure's `cause`. When a `detail` key is present it names a diagnostics file holding the same
traceback, written beside the workspace as a convenience, never as a substitute
**`failures`** — an array of structured diagnostics, **one entry per unmet requirement**: vqapr
collects every failure of an operation before refusing, so fix them all in one pass. Every entry
carries exactly these keys, in this order: `code`, `status`, `source`, `requirement`, `observed`,
`fix`, `cause`, `examples`, `example_total`. All nine are always present, including on a `usage`
refusal from the argument parser; `source`'s three fields (`file`, `key_path`, `line`) and
`observed` may be `null`, `examples` **may be empty**, and `fix` is always a sentence you can act
on.

When `ok` is false, read `fix` first. It is the sentence that fixes *this* occurrence, written as
an action you can take. `requirement` says what was needed and `observed` says what was found;
`source` says where — it is an object with `file`, `key_path` and `line`, any of which may be
`null` when the failure does not have that kind of location. Read `source` as structure, never by
parsing a formatted string out of the other fields.

Beyond `fix`, an agent branches on three things, in this order:

1. **`status` — who must act.** A closed set with HTTP's numbers, on purpose: you already know
   what 404 and 409 mean. **4xx: your submission is wrong** — a declaration, an argument, a data
   file, a precondition — and retrying without changing it is pointless. **5xx: your submission
   is fine; something that ran failed** — your own code (502), the framework (500), or the
   machine (503). Branch on `status` before you branch on `code`. `code` names the specific
   situation (`dataset.field_missing`, `workspace.locked`) and the set of codes is open in beta;
   **a `code` you do not recognise is handled as its `status`**, the way an HTTP client treats an
   unknown 4xx as 400. There is no per-status catalogue to look up: `fix`, `requirement`,
   `observed` and `source` carry the specific answer, and prose restating them goes stale every
   release.
2. **`stage` — which operation was under way.** One of: `usage` (the command line itself),
   `open` (opening the workspace), `read` (reading a source, roster or record file), `register`
   (proving and writing a declaration), `lookup` (resolving a reference), `remove`, `write`
   (writing the workspace document), `load` (importing and constructing your component), `check`
   (the judgments `vqapr check` makes and `vqapr run` repeats), `freeze` (freezing a run's
   authority before it executes), `run` (executing: callbacks, fills, valuations, datamodel
   computations), `record` (writing a record or a datamodel's dataset). The same `code` can be
   raised at more than one stage — `datamodel.output_registered` at `check` and at `freeze` — and
   the stage tells you how far the command got.
3. **`cause` — what actually happened, whole.** An object with `type`, `message`, `where`,
   `origin` and `traceback`. When an exception was involved, `type`/`message`/`traceback` are the
   exception as Python would print it, **never truncated**; when the framework refused
   deliberately without one, those three are `null`. `where` is always set: the innermost frame
   that is not the interpreter's, as `file:line (function)`. `origin` says whose frame that is:
   `"user"` for a file outside the vqapr package, `"framework"` for one inside it. The
   classification above is not guaranteed to be MECE in beta, so `cause` is how you decide
   *correctly* after `status` let you decide *quickly*. Two readings matter most: **`origin:
   "user"` with status 502 means your own code raised** — go to `where`, it is your line; and
   **`origin: "framework"` with status 500 means the framework failed** — that is not yours to
   fix, so file an issue upstream and quote `cause` whole, traceback included.

**`examples` is empty for structural checks, and that is not a bug.** A check on a column's
*type* has no offending row to quote, so it reports `"examples": [], "example_total": 0`. A check
on row *contents* — a duplicated key, a null in a key field — quotes up to five offending values
and `example_total` says how many there were before truncation. An empty `examples` next to a
non-zero `example_total` never happens; if you see one, that is worth reporting.

Fix the inputs and retry.

