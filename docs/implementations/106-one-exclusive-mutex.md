# 106 — One exclusive mutex, and a lease left alone

**Closes:** Step 2 of the approved structural plan, and audit finding **C4**.
**Branch:** `step-02-one-mutex`.

## Why this change exists

`catalog_store._exclusive`'s own docstring said it:

> *"Modeled directly on `Workspace._exclusive`: `O_CREAT | O_EXCL` is the portable primitive…"*

A copy, made knowingly, and recorded as such. It had drifted from its original in the two ways
copies drift — and both drifts were user-visible.

**They disagreed about the failure type.** `Workspace._exclusive` raised a typed `VqaprError` with
`workspace.write.locked`: six fields, a `fix`, an `explain` topic. `catalog_store._exclusive` raised
a **bare `TimeoutError`**, and `cli/main.py`'s outermost `except Exception` renders an untyped
exception as `stage: "unhandled"`. To an agent reading the envelope that is the signal for *"the
framework is broken"* — so a contended catalog, an ordinary and entirely recoverable condition, sent
the reader to suspect the package instead of waiting for the other writer. Two writers of the same
shape, one readable and one not, differing only in which file was edited later.

**They disagreed about a negative age.** `workspace._stale_lock_age` clamped at zero
(`max(0.0, ...)`); the catalog's copy did not. A lock written microseconds ago can carry an
`st_mtime` marginally ahead of `time.time()` — filesystem and clock resolution differ — and the
difference is an artifact, not information. Unclamped it reaches an operator as a negative age.

**And `30.0` / `120.0` were written out twice**, free to be tuned in one file and not the other.

## What changed

`src/vqapr/_internal/filelock.py` holds the mutex: `exclusive(lock, *, on_timeout, timeout,
stale_after)` plus `lock_age`, with `LOCK_TIMEOUT` and `LOCK_STALE_AFTER` defined once.
`CATALOG_LOCK_TIMEOUT` and `CATALOG_LOCK_STALE_AFTER` become aliases rather than second copies; the
names stay because callers and tests refer to them.

**`on_timeout` is a caller-supplied factory, not a fixed error type.** The two callers are refusing
different things to different readers — a workspace refusal names the workspace and carries
`WORKSPACE_STATE`, a catalog refusal names the catalog directory — and a shared lock that imposed
one failure vocabulary on both would push each caller's own vocabulary back into a `try/except` at
every call site. `Workspace._locked_refusal` and `catalog_store._locked_refusal` are what remain of
the two implementations, and they are the parts that were never about locking.

**What stayed in the catalog:** its directory create/unwind. A cycle that creates `.vqapr/` and then
commits nothing — the failed first registration — must leave the root exactly as it found it, or
`Project.open()` stops being safe to call before a first successful commit. That is the catalog's
business, not the lock's.

**New refusal code: `catalog.write.locked`**, in `src/vqapr/_internal/catalog_store.py`. The
baseline was regenerated deliberately, and the drift was exactly one code added and none removed —
which is what record `105`'s re-keyed gate is for: it reported the addition as a real event, and no
line-shift noise came with it.

## What is deliberately NOT in this step

**`flow/run_records.py`'s lock stays.** The plan originally described three interchangeable lock
sites and a mechanical extraction. They are not three of a kind. `run_records` is a run-length
**lease**: `_claim` (`:445-455`) writes the holder's pid, `heartbeat` (`:434-443`) touches the file
per chunk and **never raises**, `release` (`:459-467`) **never raises**, and staleness is what makes
a dead run's id reclaimable. Two of those properties are deliberate non-raising behaviour that a
mutex must not have.

Folding a lease into a mutex abstraction because both call `O_CREAT | O_EXCL` is pattern-matching on
the primitive rather than on the semantics. And `run_records.py:400-419` records two prior attempts
to simplify around that exact lock, each of which made a real race **measurably worse** — 9 of 12
and 12 of 12 failures — and each of which was reverted.

**So the metric is 3 → 2, and this record says so rather than claiming 1.** The tempting "one
exclusive lock" row is not in any table here. `grep -rl "O_CREAT | os.O_EXCL" src/vqapr` returns
exactly `_internal/filelock.py` and `flow/run_records.py`.

## One boundary test needed a decision rather than an update

`workspace.py` now imports `vqapr._internal.filelock`, and
`tests/boundaries/test_internal_has_one_door.py` (record `098`) forbids `_internal` imports outside
the four extension adapters and frozen `project.py`.

That rule exists so **deleting the four adapters stays mechanical**: a deletion whose callers all
name one path is four files removed and every stale import breaking loudly. `filelock` is not an
extension authority and is not scheduled for deletion — it is a shared primitive, and the structural
audit's own target structure names `_internal/filelock.py` as the single home for the exclusive
lock. `workspace.py` importing it costs the adapter deletion nothing.

So the permitted list gains `src/vqapr/workspace.py` with that reasoning written next to it, plus
the limit: this entry does **not** license a second door to the extension authorities. A future
`_internal/extensions/*` import from `workspace.py` belongs behind the adapters regardless.

## Validation

| check | result |
|---|---|
| exclusive-lock implementations | **3 → 2** (`_internal/filelock.py`, `flow/run_records.py`) |
| `tests/internal/test_one_mutex_two_callers.py` (new) | 8 passed |
| `pytest -m concurrency` | 7 passed |
| `tests/internal/` | 156 passed |
| `tests/test_workspace*.py` | 46 passed |
| fast suite | **1468 passed**, 14 deselected |
| `uv run ruff check src/` | All checks passed |
| baseline regeneration | deliberate; **one code added** (`catalog.write.locked`), none removed |

The new tests assert the two drifts specifically: a contended catalog now raises `VqaprError` with
`stage: "catalog.write"`, a populated `fix` and an `explain` topic rather than a bare
`TimeoutError`; and an `st_mtime` an hour in the future reads as `0.0` seconds old rather than
negative. Two further tests hold the line the extraction must not cross — the workspace still
refuses in its own vocabulary with `workspace.write.locked`, and the catalog directory is still
unwound when a cycle commits nothing but survives when it holds real state.
