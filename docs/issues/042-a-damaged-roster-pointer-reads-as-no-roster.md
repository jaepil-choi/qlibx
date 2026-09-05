# 042 — A damaged roster pointer reads as "no roster", and the run charges every name as a share

**Status:** **CLOSED 2026-08-31** by
`docs/implementations/103-the-audits-two-correctness-findings.md`. Both call sites now let the typed
refusal through; only `Workspace.open` itself is guarded.
**That remaining guard is [050](050-a-damaged-workspace-reads-as-no-roster-and-the-report-reads-the-pointer-twice.md)**,
closed 2026-09-01 by `docs/implementations/122-the-roster-is-read-once-and-a-damaged-workspace-is-a-refusal.md`:
it now admits `workspace.open.missing` only, and there is one call site left because the report no
longer reads.

**Status when filed:** open. Found 2026-08-31 by the structural audit recorded in
`docs/diagnostics/2026-08-31-vqapr-structural-refactoring.md` (§6, C1). Not a journey finding — it
was found by reading the two call sites against the docstring of the function they call.
**Touches:** `src/vqapr/public.py` (`_registered_roster`, `roster_report`);
`Workspace.registered_instruments`; `docs/issues/007`.

## The two states this collapsed

`Workspace.registered_instruments()` raises a typed `workspace.instruments.unreadable` when the
pointer JSON is damaged, and its docstring states the reason:

> *"Reported, never repaired and never treated as absent: 'no roster' and 'a roster whose record is
> damaged' are different states, and only the first is ordinary."*

Both callers on the run path caught it:

```python
try:
    pointer = Workspace.open(root_path).registered_instruments()
except Exception:
    return None
```

`None` means **no roster is registered**, which is a legal, ordinary state. So a truncated
`.vqapr/instruments.json` — a crash mid-write, a hand edit — made a project that HAS a roster
indistinguishable from one that never had one.

The comment three lines below the swallow reads *"A REGISTERED roster that cannot be read is
refused, not degraded."* That was true of the roster **tables** and false of the **pointer** that
names them, and the guard written for an absent workspace had quietly grown to cover both.

## What it costs

`vqapr run` completes with `ok: true` and `roster: null`. Every fill records `kind: None`.
`cost_by_kind()` collapses to one unlabelled bucket. On a KRX-shaped venue the ETF sleeve is charged
the share sale tax it is exempt from — which is precisely the defect `docs/issues/007` closed,
returning through a `try/except` written for a different case.

Nothing in the envelope distinguishes it from a rosterless run, and the frozen record says the same.

## What closes it

Guard `Workspace.open` alone, and let `registered_instruments()`'s typed refusal out:

* `_registered_roster` runs at run START, where refusing is right — nothing has been computed and
  the run must not proceed without categories.
* `roster_report` runs AFTER the run, where `cli/run.py`'s `_roster_envelope` already catches that
  refusal and reports `known: true, stale: true`. That is the honest answer for a run that read its
  roster and then lost the record of it; swallowing produced `known: false`, the same envelope a
  genuinely rosterless run gets, and the opposite of the truth.

An absent workspace stays `None`, because that is the case the guard exists for.
