# 122 — The roster is read once, and a damaged workspace is a refusal

**Closes:**
[`050`](../issues/050-a-damaged-workspace-reads-as-no-roster-and-the-report-reads-the-pointer-twice.md)
— both halves, in one commit, because they are one read.
**Branch:** `fix-050-roster-reads-once` (from `develop@602e1b3c`).
**Sibling:** [`103`](103-the-audits-two-correctness-findings.md), which closed the same defect at the
pointer door ([`042`](../issues/042-a-damaged-roster-pointer-reads-as-no-roster.md)) and whose own
closing text named this one: *"only `Workspace.open` itself is guarded."*

## Why this change exists

### Half one — the guard was wider than its reason

`flow/roster.py` opened the workspace behind `except Exception: return None`, twice. The guard was
written for one state — a run assembled **outside** a workspace, which has no roster to find — and
covered every state in which a workspace cannot be **read**. `Workspace.open` decodes
`.vqapr/workspace.yaml` and raises a typed `workspace.open.invalid` for a file that is corrupt or
half-written; the guard turned that into `None`.

`None` is not a refusal. It means *no roster is registered*, which is legal, so the run continued
and every fill recorded `kind: None`. On a KRX-shaped venue that charges the ETF sleeve at the
share rate and collapses `cost_by_kind()` to one unlabelled bucket — the report that would expose it
is the one the gap erases. That is [`007`](../issues/007-an-undeclared-instrument-is-silently-a-share.md)
returning through a `try/except` written for a different case, exactly as `042` was.

Four lines below the swallow the module already stated the principle it was breaking: *"'no roster'
and 'a roster whose record is damaged' are different states, and only the first is ordinary."*

### Half two — the report read the pointer again

`roster_report`'s docstring claimed its answer came *"from the roster already loaded for this run
rather than from a second read"*. True of `by_kind`; false of `digest` and `tables`, which came from
a second `space.registered_instruments()` — the file as it stood minutes later, after
`registered_roster` had bound the categories.

A `vqapr register` landing during a long run therefore made the frozen record carry the **new**
roster's digest beside fills classified by the **old** one, and report the pair as one consistent
fact. The `source_digest` / `declared_digest` pair exists precisely to make that drift visible.

## How it works

### The read is an object now

`registered_roster` returns a `RegisteredRoster` — `registry`, `digest`, `tables` — instead of the
registry alone, and `roster_report` takes that object instead of a project root. **The second read
is not narrowed, it is gone**: there is no path from `roster_report` to the filesystem, which is
what turns the docstring's claim from a promise into a property. The digest and the table list are
taken from the same `pointer` dict the registry was built from, in the same statement.

### The guard is the size of its reason

```python
except VqaprError as unopened:
    if not _absent_workspace(unopened):
        raise
    return None
```

`_absent_workspace` is true only for `workspace.open.missing`, the refusal `Workspace.open` raises
on `FileNotFoundError`. Its two siblings — `workspace.open.unreadable` (permissions) and
`workspace.open.invalid` (does not decode) — describe a workspace that is **there and damaged**, and
they now travel. So does anything that is not a `VqaprError` at all, which the old guard also ate.

The refusal lands where 042 put the pointer's: at run **start**, before anything is computed, and on
the envelope side `cli/run.py`'s `_roster_envelope` catches it and reports `known: true, stale: true`
— the honest answer for a run that read its roster and then lost the record of it, and the opposite
of the `known: false` a swallow produced.

## What changed

| file | change |
|---|---|
| `src/vqapr/flow/roster.py` | **added** `RegisteredRoster` and `WORKSPACE_ABSENT`/`_absent_workspace`. `registered_roster` returns the bundle; its `except Exception` is now `except VqaprError` re-raised unless the workspace is absent. `roster_report(read)` takes the bundle, opens nothing, and its second `Workspace.open`/`registered_instruments()` pair is deleted |
| `src/vqapr/flow/orchestration.py` | `roster = registered_roster(root_path)` once; `registry` is unwrapped from it for `SimulationFlow`, and the same object is handed to `_roster_report_or_stale(roster)` |
| `src/vqapr/cli/run.py` | `roster_report(_registered_roster_for_report(project_root))`. `_roster_envelope`'s docstring and stale note now name the workspace beside the tables, since the refusal it absorbs can now come from either |

`vqapr.public` is untouched: it re-exports `registered_roster` and `roster_report` by name and both
names still exist. `RegisteredRoster` is deliberately **not** added to `public.__all__` — it is the
shape of a value the two functions pass between themselves, not a thing a user constructs.

## The trade this record should be judged on

**`_roster_report_or_stale`'s absorber is now unreachable through its own call.** It exists because
R1 discarded a completed multi-hour run when the post-run report raised, and the thing that raised
was the second read. With the second read gone, `roster_report` touches no file and cannot produce
that refusal.

It is kept, and its docstring says why: the property being defended is structural, not incidental —
*nothing computed after `flow.run()` returns may cost the record*. Deleting the absorber would leave
that guarantee resting on the current implementation of one function. Its four tests still hold,
because they monkeypatch `roster_report` and assert the absorber's behaviour rather than the read's.

## What was deliberately not done

- **The roster is still not a gate.** It is read fresh, its digest stated and compared against
  nothing. A roster grows as a matter of course, so a gate here refuses every morning
  ([`009`](../issues/009-a-fingerprint-is-a-receipt-not-a-gate.md)).
- **`Workspace.open`'s own guards are untouched.** The three refusals it raises were already
  correctly distinguished; the defect was entirely on the reading side.
- **No end-to-end run test was added for half two.** The mid-run re-registration is exercised at the
  `registered_roster` / `roster_report` seam, which is where both reads lived. A `@pytest.mark.slow`
  journey that re-registers from inside a strategy callback would exercise the same two calls
  through several minutes of unrelated machinery. **Flagged so it is a decision rather than an
  oversight.**

## Validation

| gate | result |
|---|---|
| `uv run --no-sync ruff check src/` | **clean** |
| `PYTHONUTF8=1 uv run --no-sync pytest tests/ -q` | **1518 passed, 5 skipped, 14 deselected** (baseline at the branch point, measured on this worktree before any edit: **1510 passed, 5 skipped, 14 deselected**) |
| `PYTHONUTF8=1 uv run --no-sync pytest tests/ -q -m ""` | **1532 passed, 5 skipped** — run because this change touches run assembly |

The count moves by exactly the 8 test functions added. `ruff check tests/` reports findings, all
pre-existing at the branch point and none in a file this lane touched; `src/` is the declared gate.

### Each half failed on the pre-fix tree first, and was watched failing

`tests/flow/test_a_damaged_workspace_is_not_no_roster.py` was written before the source changed and
run against the unmodified tree — as a byte-identical copy except that its three `roster_report`
calls used the pre-fix two-argument signature, so the failures below are the assertions failing, not
an arity error. **6 failed, 2 passed:**

| test | pre-fix | post-fix |
|---|---|---|
| `test_a_damaged_workspace_refuses_rather_than_reading_as_no_roster[truncated/empty/wrong-shape]` | `Failed: DID NOT RAISE VqaprError` — the run would have continued with `kind: None` | raises `workspace.open.invalid` |
| `test_the_envelope_says_known_and_stale_rather_than_no_roster` | `known: false` — the envelope of a rosterless run | `known: true, stale: true` |
| `test_the_report_describes_the_roster_the_run_read_not_the_file_now` | digest is the roster registered **after** the read, beside the counts from before it | digest and tables and counts all describe the read |
| `test_the_report_does_not_read_the_pointer_a_second_time` | `assert not ['space.registered_instruments']` | no call to either read in the parse tree |
| `test_an_absent_workspace_is_still_no_roster` | passes | passes |
| `test_a_project_that_registered_no_roster_is_still_no_roster` | passes | passes |

The last two are the controls: they are the states `None` is reserved for, and they must pass on
both trees. The digest test is the one that matters for half two — it asserts the frozen record's
digest against the roster the fills were classified by, with a real `register_instruments` landing
between the read and the report.

The structural test reads the parse tree rather than the source text, so a comment naming either
call is free and only an actual call fails it.

### Tests changed rather than added

- `tests/flow/test_a_damaged_roster_pointer_is_not_no_roster.py` — 042's file, moved onto the new
  signatures. Its envelope leg asserted `roster_report(project, None)` raises; since `roster_report`
  no longer reads, the same guarantee is now asserted where it actually lives, on
  `_roster_envelope(project)` returning `known: true, stale: true`. **Strictly more of the real path
  than it covered before.**
- `tests/flow/test_a_completed_run_survives_a_broken_roster.py` — `_roster_report_or_stale` takes one
  argument, and the source pin that guards R1 now reads `_roster_report_or_stale(roster)`.
