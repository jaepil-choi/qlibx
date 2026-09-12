# 116 — A materialization is a run

**Closes:** Step 10b of the approved structural plan.
**Branch:** `step-10b-a-materialization-is-a-run`.

## Why this change exists

A materialization already produced exactly the facts a run record carries — which declarations
produced it, how many rows, over what window — and wrote them to `.lineage.json`.

**`list runs` does not index that file and `show run` cannot read it.** So the same question had two
answers in two formats, and one of them was invisible to both commands. A user who materialized a
dataset and then asked the product what it had done was told nothing.

Owner ruling: a materialization writes a run record with `kind: materialization`, absorbing
`.lineage.json`'s per-invocation content. Record `115` declared the field set for this kind a story
before its producer existed, so this story adds a producer rather than also changing the reader.

## What changed

`_write_materialization_record` in `flow/materialize.py` writes a `RunRecordWriter` record with
`kind=MATERIALIZATION_KIND`, answering the six fields `record_fields(MATERIALIZATION_KIND)` declares:
`dataset_id`, `source_digest`, `declared_digest`, `rows`, `span`, `period`.

**Written inside `flow/materialize.py`, not in the CLI's `_materialize`.** That is the whole
difference between this and a CLI feature: a public-API caller — the showcases, a notebook,
`vqapr.materialize` — gets a record too. Putting it in the verb would have reproduced the split that
`docs/issues/archive/012` records, where `check` and `run` each decided for themselves.

**The run id is derived from what was produced, not from a clock.** Two materializations of the same
dataset over the same evaluation times *are* the same run, and giving them the same id makes a re-run
visible as a replacement rather than as a second history. A wall-clock id would make every invocation
unique and turn `list runs` into a log of every time anyone rebuilt a dataset, which is not the
question a reader is asking when they list runs.

**`.lineage.json` is dual-written for one release, and cannot drift.** `_lineage_payload`'s
`invocations` block is now a *projection* of `_materialization_period`, the same structure the record
carries. It used to build that block itself, so the record and the lineage file were two computations
of one set of facts — the shape record `112` argues against and `docs/issues/archive/012` is the cost of.
Retiring the file is a separate owner-gated decision and is **not** in this story.

## R1's lesson, applied before it could happen again

By the time the record is written the dataset is registered and the parquet is on disk. A refusal
here would discard completed work over its own bookkeeping — exactly the defect record `113` fixed on
the run path, where a roster file going bad after a run finished threw the whole record away.

So a record failure is absorbed and reported as `record_path=None`. It catches `OSError` and
`VqaprError` only; a programming error still escapes. `test_a_record_failure_does_not_discard_a_completed_materialization`
pins it.

The field-set check keeps the run kind's guarantee: a field named without a builder, or a builder
without a field, raises `KeyError` at the write rather than producing a record quietly missing an
answer.

## Validation

| check | result |
|---|---|
| `tests/flow/test_a_materialization_is_a_run.py` (new) | 7 passed |
| fast suite | **1494 passed**, 14 deselected |
| **`-m slow -rs`** | **14 of 14 passed**, no skip lines |
| `uv run ruff check src/` | All checks passed |

The tests assert the properties rather than the implementation: the record lands where `list runs`
looks, it declares its kind, `show run` projects it through the materialization field set rather than
rendering six nulls from a run's, every declared field is answered, the lineage file equals the
record's projection, a re-run of the same window reuses its id while a different window does not, and
a write failure returns `None` instead of raising.
