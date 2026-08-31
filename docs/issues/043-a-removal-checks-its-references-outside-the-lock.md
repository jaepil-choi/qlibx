# 043 — `Workspace.remove()` checks references outside the lock, so a race can leave a workspace that will not open

**Status: CLOSED 2026-09-01** by
`docs/implementations/108-a-removal-and-its-check-see-one-snapshot.md` (Step 4 of the structural
plan). `references_to` now evaluates inside `_exclusive()` against the state the lock already read,
so the removal and its check see one snapshot. The plan's acceptance was deliberately the strongest
in the campaign and was not weakened: **a concurrency test that fails on the pre-fix tree first**,
then passes.

**Status when filed:** open. Found 2026-08-31 by the structural audit recorded in
`docs/refactoring/2026-08-31-vqapr-structural-refactoring.md` (§6, C2). Filed unfixed: the repair is
small, but it moves a read inside the exclusive section and this repository has measured that
reordering around these locks can make a race worse rather than better.
**Touches:** `src/vqapr/workspace.py:1034` (`remove`, `references_to`, `_exclusive`).

## The window

```python
blockers = self.references_to(kind, identity)   # its own _read(), no lock
if blockers:
    raise ...
with self._exclusive():                          # the lock starts here
    state = self._read()
    ...
```

The check and the write are two separate reads with no lock between them. A second process that
registers a strategy config naming the component being removed, in that window, loses: the removal
proceeds on a reference list that was already stale.

## Why the result is worse than a lost update

`_decode` validates forward references when a workspace is read. A document holding a config that
names a component nobody registered does not merely carry a dangling pointer — **`Workspace.open()`
raises**, and every command in the project fails until the file is hand-repaired.

So the failure mode is not "a removal that should have been refused". It is "the project no longer
opens", produced by two ordinary commands run concurrently.

This is not an exotic scenario for this repository: `pyproject.toml` declares a `concurrency` marker
and `tests/test_workspace_concurrency.py` exercises exactly this class.

## What closes it

Perform `references_to` inside `_exclusive()`, against the `state` the lock already read, so the
check and the write see one snapshot.

**Why it is filed rather than fixed in the same pass:** `run_records.py` records two attempts to fix
a neighbouring race by reordering operations around a lock, both of which made it **more** frequent
(9/12 and 12/12 failures) and were reverted. A change to lock scope here deserves its own pass with
a concurrency test that fails on the current code first — the same standard the two tests written
this week were held to.
