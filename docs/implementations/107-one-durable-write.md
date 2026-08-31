# 107 — One durable write

**Closes:** Step 3 of the approved structural plan.
**Branch:** `step-03-one-durable-write`.

## Why this change exists

Four implementations of "stage a temporary file beside the target, fsync it, `os.replace` it into
place" existed — `workspace.py:1424`, `_internal/catalog_store.py:209`, `_internal/objects.py:109`,
`flow/run_records.py:511`. Each had independently decided what to do about the parts that are easy
to forget, and they had decided differently.

**Only one of the four retried the swap.** The reasoning was written down only in `workspace.py`,
and it is not about workspaces:

> POSIX `rename` is unconditional, so a reader holding the old inode is simply left holding it and
> the swap succeeds. Windows refuses instead: `os.replace` onto a path another process currently
> has open fails with `WinError 5` […] The workspace lock does not cover this. It serialises
> *writers* against each other […] but a **reader** takes no lock, deliberately.

It is about `os.replace` on Windows, and it applies to every file in this package a reader can hold
open while a writer swaps it — a run record being read by `show run`, a catalog read by a concurrent
`Project.open()`. Three of the four were exposed to a race the fourth had already measured at **1
run in 10 with eight concurrent processes** and solved.

**Only two of the four fsynced.** `run_records.finish` did not, on the crash-safety-critical path,
with nothing documenting it as a choice.

## What changed

`src/vqapr/_internal/atomic.py` holds `write_atomically(target, payload, *, on_error, verify,
create_parent, encoding, attempts, backoff)`. `os.replace` now appears in exactly one module.

What stayed with the callers, because none of it was about durability:

- **`on_error`** — the failure vocabulary. `run_records.finish` maps `OSError` to a typed
  `RunRecordTaken` carrying the run id; `workspace._write` maps it to `workspace.write.failed` with
  an `explain` topic. A single hard-coded failure type would push each caller's vocabulary back into
  a `try/except` at every call site.
- **`verify`** — `objects.stage_object` re-reads the staged bytes and checks their digest before the
  swap. That is a content-addressed store's invariant, not a property of writing files, so it is a
  hook rather than behaviour every caller pays for.
- **`create_parent`** — see below.

## Two changes that are not pure extraction, both deliberate

**fsync is now universal.** `run_records.finish` did not fsync. Nothing defended the omission, and
it is the one write in this package whose loss means a completed run has no record. It fsyncs now,
and this record says so rather than letting it arrive silently inside a "no behaviour change" step.

**The record file's bytes changed from CRLF to LF on Windows.** Two of the four former writers
opened in text mode with the platform default newline, so `run_records` wrote `\r\n` on this
platform. The shared writer encodes and writes bytes, so a `str` payload lands with the newlines it
already carries. The artifacts are JSON and YAML read back by parsers, so the translation bought
nothing and cost byte-identity across platforms. Pinned by
`test_a_finished_record_is_valid_json_with_the_newline_it_was_given`.

## The regression the tests caught, and the parameter it produced

The first version of this step lost a real behaviour, and the test for it failed rather than the
suite going quietly green.

`RunRecordWriter.finish` writes into a directory it claimed at the start of the run. **If that
directory is gone by the end, another run took the id** — only possible when someone forced an id
already in use — and this run's rows went with it. The original detected that because
`tempfile.mkstemp(dir=directory, …)` raised, and mapped it to `RunRecordTaken`.

The shared writer created parent directories, which turned that detection into a **silent recreation
of state another run now owns**. Two fixes, both necessary:

1. `create_parent=False`, so the directory's absence stays the signal.
2. The `mkstemp` call moved *inside* the error mapping. It had been outside it, so a stolen
   directory escaped as a raw `FileNotFoundError` — the unhandled shape `RunRecordTaken` exists to
   replace — instead of reaching `on_error` at all.

`test_a_stolen_run_directory_is_still_reported_rather_than_recreated` is the test that failed on
both, and it fails on either if they regress.

## The one-door boundary test needed restructuring, not another exception

`workspace.py` gained an `_internal.filelock` import in record `106`, and `run_records.py` gains an
`_internal.atomic` import here. `tests/boundaries/test_internal_has_one_door.py` forbade **all**
`_internal` imports outside `_internal/`, so each step wanted an exception appended.

A rule with a growing exception list is one nobody can state. The rule was never about all of
`_internal` — record `098` wrote it so that deleting the four extension adapters stays mechanical.
When it was written, the only `_internal` importers outside `_internal/` *were* those adapters and
`project.py`, so "imports `_internal`" and "reaches an extension authority" were the same set and
the test checked the cheaper one. They stopped being the same set the moment this refactoring began
extracting shared primitives into `_internal/`.

The test now checks what the rule always meant. `SHARED_PRIMITIVES` enumerates
`_internal.filelock` and `_internal.atomic` — the two modules this campaign is consolidating *into*,
neither an extension authority, neither scheduled for deletion — and a new test asserts that **no
shared-primitive allowance covers `_internal.extensions.*`**, for any importer, including the ones
on the allowance.

The AST walk also had to resolve `from vqapr._internal import atomic, filelock`, whose `node.module`
is the package and whose submodule is the alias. Without that, a shared primitive and an authority
spell their package identically and the distinction cannot be made at all.

**Proven to fail on the breach.** `from vqapr._internal.extensions import loading` was temporarily
injected into `run_records.py` — a module that *is* on the shared-primitive allowance — and the
authority test failed naming the edge. Then reverted, verified clean.

## Validation

| check | result |
|---|---|
| `os.replace` call sites in `src/` | **4 → 1** (`_internal/atomic.py`; one docstring mention remains in `workspace.py`) |
| `tests/internal/test_one_durable_write.py` (new) | 8 passed |
| `tests/boundaries/` | 36 passed |
| `pytest -m concurrency` | 7 passed |
| `tests/flow`, `tests/qa`, `tests/internal` | 366 passed |
| fast suite | **1477 passed**, 14 deselected |
| **`-m slow -rs`** | **14 of 14 passed**, no skip lines |
| `uv run ruff check src/` | All checks passed |

The slow journeys were run even though the plan does not mark this step `[test_all]`:
`.agent/project.yaml` requires them for "any change to run assembly, the record shape, or the
scaffolds", and this step changed the run-record **writer** and the bytes it emits. `-rs` reports
skip reasons and none appeared, so the 14 is the whole set rather than an invocation that happened
to run fewer.

The new tests assert the contract at all four former call sites: a failure staged before the swap
leaves an existing workspace, catalog and run record byte-identical and creates nothing where
nothing existed, leaves no `.tmp` behind, and never installs an object whose digest does not verify.
