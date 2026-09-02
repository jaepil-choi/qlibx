# 134 — one declaration document, one transaction

**Closes:** testbed finding A3 (`kwam-enhanced-index/vqapr-enhanced-index-3/VQAPR-ISSUES.md`;
`docs/issues/README.md` §unfiled). **Step:** 2 of
`docs/refactoring/2026-09-02-the-convergence-campaign.md` (M2).
**Authority:** the campaign doc's Step 2 acceptance; `_internal/filelock.exclusive` and
`_internal/atomic.write_atomically` (records `106`, `107`).

## Why this exists

`vqapr register <file>.yaml` walked the document's eight sections and, **per item**, called a
`Workspace.register_*` that took the lock, read the whole workspace, merged one entry, wrote the
whole workspace and released. A document of 27 datasets was 27 lock/read/write cycles, and a
document refused at its k-th item left items 1..k-1 registered. Registrations being immutable,
the corrected document then conflicted at item 1, and the only recovery the testbed found was
deleting `.vqapr/` — 28 minutes to rebuild, in a loop that repeated on every typo. The testbed
called it the most expensive thing in its session, and the campaign put it second because Steps
5 and 7 migrate workspace documents and had no recovery path for a partial failure either.

## What changed

### Merges are functions of state (step A, its own commit)

Every `register_*` was `lock → read → merge → write` with the merge inline. The merges are now
`_merge_<kind>(state, item) -> (state, changed)` — the same refusals, the same codes, the same
messages — and `register_*` wraps one with `_commit()`. A `_State` NamedTuple names the eight
mappings the file holds; it is still a tuple, so every `*state` unpacking and index in the module
is unchanged. No behaviour moved in that commit, and the suite said so.

### A transaction stages, then commits once

`Workspace.transaction(project_root)` returns a `Transaction` holding a snapshot of the workspace
— or the empty document, where none exists yet. Each `register_*` on it runs the same merge the
single-item method runs, against the staged state, so a conflict or a missing reference is refused
at staging time, where the author can still see which item it was; and `transaction.view` is a
`Workspace` over that staged state, so an agenda can follow a dataset declared earlier in the
same document and a config can name a component declared above it, exactly as they would resolve
one already on disk.

`commit()` is the only method that touches disk. It holds the lock for one read and one write:
the staged merges are **replayed against the state read under the lock**, so a registration that
landed from another process in the meantime is seen and, if it conflicts, refused — and then
nothing is written. The roster sidecar, when a document declares one, is written after the
document inside the same lock. A document with nothing to commit takes no lock at all.

### `_apply` builds, then commits

The section loop is the same loop; each item stages instead of writing. Component registration
was split for it: `prepare_component` (fingerprint + conformance) returns the reference and
writes nothing, and `register_component` is that plus one write, which the four public
`register_*` still call. The `registered` receipt is unchanged, so `cli/register.py` did not
move.

The old docstring's reason for opening the workspace lazily — a malformed agenda in a fresh
directory must not report `workspace.open.missing` — holds by construction now: the staging view
in a fresh directory is the empty document, and a lookup that fails there reports the missing
dataset, not a missing directory.

## Acceptance, asserted

`tests/test_a_declaration_is_one_transaction.py`:

- a document refused at its k-th item leaves `.vqapr/` **byte-identical** (fingerprinted before
  and after; the valid first item did not land);
- a valid document of two datasets and two agendas — one following a dataset declared in the same
  document — is **one** `write_atomically` call;
- the same document applied twice writes **nothing** the second time;
- a document refused before anything could be staged, in a directory with no workspace, creates
  nothing.

Every existing registration test is green, including the eight-process concurrency test, which
still exercises the single-item path.

## Trade-offs

**Two reads per document instead of one per item.** The snapshot for staging is read without the
lock; commit reads again under it. A document that stages nothing skips the second.

**Conflicts can now surface twice.** A conflict against the snapshot is refused at staging; a
conflict against what another process wrote between snapshot and commit is refused at commit. Both
are the same refusal, and both leave the workspace untouched. No test simulates the second; it is
the replay's reason for existing, stated here rather than proved.

**One slow test was rewritten, and it is not about this change.** The record-liveness test
slept six seconds and then probed; the sample run takes 5.0 s on an idle machine (measured on
`develop` and here alike), so the probe found a finished record and the test had passed only
while other suites loaded the machine. It now probes from inside the run, on the third heartbeat,
after letting the shrunk window elapse. Its own commit says the rest.

**The single-item API is unchanged.** `Workspace.register_*`, `public.register_dataset` and the
four `register_<kind>` functions behave exactly as before; only the document path moved.

## Validation

```
uv run ruff check src/                           All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs         1260 passed, 14 deselected
PYTHONUTF8=1 uv run pytest tests/ -q -m slow -rs  14 passed
```

Branch parent `develop @ b863fd1f` (record `133` merged), measured: **1256 passed / 14
deselected** fast; **14** slow. The four new tests are the difference.
