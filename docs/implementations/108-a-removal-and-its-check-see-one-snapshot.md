# 108 — A removal and its check see one snapshot

**Closes:** `docs/issues/archive/043`, and Step 4 of the approved structural plan.
**Branch:** `step-04-a-removal-sees-one-snapshot`.

## The window

```python
blockers = self.references_to(kind, identity)   # its own _read(), no lock
if blockers:
    raise ...
with self._exclusive():                          # the lock starts HERE
    state = self._read()
    ...
```

Two reads, no lock across them. A second process that registers a declaration naming the target in
that window loses: the removal proceeds on a reference list that was already stale.

**The result is worse than a lost update.** `_decode` validates forward references, so a document
holding a strategy config that names a component nobody registered does not merely carry a dangling
pointer — **`Workspace.open()` raises**, and every command in the project fails until the file is
hand-repaired. Two ordinary concurrent commands produce a workspace no command can open.

## What changed

`references_to` splits in two. The public method still performs its own read, for callers outside a
write cycle. `_references_in(state, kind, identity)` answers the same question against a state
already in hand, and `remove` calls that **inside** `_exclusive()`, against the state the lock
already read. One snapshot for the check and the write.

The `position` lookup moved after the reference check. It had been before it, and `_references_in`
is what raises the typed `remove.unsupported_kind` refusal for a kind like `dataset` — reordering
without care would have turned that into a bare `KeyError` from the dict.

## The proof, which is the point of this step

Issue 043 was filed **unfixed on purpose**, and said why: `run_records.py:400-419` records two prior
attempts to fix a neighbouring race by reordering around a lock, each of which made it *measurably
worse* — 9 of 12 and 12 of 12 failures — and each of which was reverted. So the issue set a
standard: a concurrency test that **fails on the current code first**.

`tests/test_workspace_remove_races_registration.py` was written and run **before** the source
changed, with `git status --short src/` empty to prove it. Both tests failed:

```
FAILED test_a_removal_and_a_registration_cannot_produce_an_unopenable_workspace
  Failed: two well-behaved concurrent commands produced a workspace that will not open, which no
  later command can recover from: DATA:workspace.open — 1 failure(s)
    [workspace.open.invalid] workspace YAML must contain valid physical sources and dataset
    declarations

FAILED test_the_reference_check_and_the_write_see_one_snapshot
  AssertionError: remove() read the workspace outside its own lock, which is the gap a competing
  writer commits into
```

The first reproduces the exact failure mode the issue describes. The second names the mechanism, so
a future reader knows *why* it failed rather than only that it did. After the fix, both pass.

**The interleaving is forced, not hoped for.** `_exclusive` is wrapped so the competing registration
runs at the instant the remover is about to take the lock — after the old code's unlocked pre-check,
before either version holds the lock. That hook point is deliberate: it is the one moment that
exists in *both* versions, so the same test is meaningful against each. The competitor takes the
lock properly through `register_strategy_config`, so this is a race between two well-behaved
callers, not a test that cheats by writing behind the lock's back.

**A harness bug worth recording**, because it nearly produced a false negative. The patch is applied
to the class, so the competitor's own `register_strategy_config` re-enters the same wrapper. The
first guard closed only once the registration *completed*, which recursed until the process ran out
of file descriptors (`OSError: [Errno 24] Too many open files`) — a failure that looks like a real
defect and is not. The guard now closes on entry.

The second test asserts the mechanism rather than the symptom: it counts `_read` calls made while
the lock is not held, and requires zero. A symptom test alone would pass again if someone later
"fixed" this by widening a retry.

## Relationship to the step after it

Step 14 of the plan transplants the catalog's compare-and-swap model into the workspace registry,
which subsumes this in-lock pre-check. This still lands first, and deliberately: it closes a live
defect months earlier than that step will arrive, and a project that will not open is not a defect
to schedule around. When Step 14 comes, it must not leave a vestigial pre-check inside the CAS
commit.

## Validation

| check | result |
|---|---|
| **fails on pre-fix `develop`** | **yes — both tests, verified with `src/` unmodified** |
| passes after the fix | yes |
| `tests/test_workspace*.py` incl. the new file | 48 passed |
| `pytest -m concurrency` | **9 passed** (was 7; +2 new) |
| fast suite | **1479 passed**, 14 deselected |
| `uv run ruff check src/` | All checks passed |
