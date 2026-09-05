# 103 — The audit's two correctness findings, before the release

**Closes:** `docs/issues/042-a-damaged-roster-pointer-reads-as-no-roster.md` (C1), and the C3 defect
the same audit found in code written earlier in this batch.
**Branch:** `fix/post-campaign-audit-029-043`.
**Source of both:** `docs/diagnostics/2026-08-31-vqapr-structural-refactoring.md` §6 — a structural
audit run by a second agent against this batch's working tree.

## C1 — a damaged roster pointer read as "no roster"

`Workspace.registered_instruments()` raises a typed refusal for a damaged pointer and its docstring
says why: *"'no roster' and 'a roster whose record is damaged' are different states, and only the
first is ordinary."* Both run-path callers caught `Exception` around it and returned `None`, which
is the value reserved for **no roster registered**.

A truncated `.vqapr/instruments.json` therefore produced a complete run with `roster: null`, every
fill recording `kind: None`, and a KRX-shaped venue charging the ETF sleeve the sale tax it is
exempt from — `docs/issues/007` returning silently through a guard written for a different case.

**The fix is a split, not a removal.** `Workspace.open` stays guarded, because a run assembled
outside a workspace genuinely has no roster to find. The `registered_instruments()` call moves out
from under it:

- `_registered_roster` runs at run START and refuses, which is what the comment three lines below
  the old swallow already claimed happened.
- `roster_report` runs AFTER the run, and `cli/run.py`'s `_roster_envelope` already had a
  `VqaprError` handler reporting `known: true, stale: true` — the honest answer for a run that read
  its roster and then lost the record of it. The swallow was making that handler unreachable and
  reporting `known: false` instead, which is the envelope a genuinely rosterless run gets.

## C3 — a conflict refusal that only fired away from the default

`_lookback_arguments` (written earlier in this batch, record `101`) promises in its own docstring
that giving both `--lookback` and `--calendar-lookback` is refused *"rather than resolved by
precedence: a reader should not have to know which flag wins"*. The check was
`if args.lookback != _LOOKBACK_DEFAULT`.

So `vqapr new datamodel m --dataset d --lookback 6 --calendar-lookback 30` — both flags, one of them
typed at its default value — was **not** refused, and `--lookback` was silently ignored. The exact
outcome the docstring exists to prevent.

`--lookback` now defaults to `None` and presence answers the question instead of value. The rows
default moves into `_lookback_arguments`, which is the one place that already decides what "no flag
given" means.

## Validation

| check | result |
|---|---|
| `tests/flow/test_a_damaged_roster_pointer_is_not_no_roster.py` (new) | 7 passed |
| `tests/extension/test_the_scaffold_offers_both_lookbacks.py` | 9 passed |
| fast suite | **1455 passed**, 14 deselected |
| `-m slow` | **14 of 14 passed** |
| `ruff check src tests` | 14 findings, all pre-existing |

The roster test damages the pointer three ways — truncated, empty, and valid JSON of the wrong shape
— and asserts the typed code reaches the caller in each. Two companion tests hold the line the fix
must not cross: an absent workspace is still `None`, and a healthy roster still loads with its
histogram intact.

## What is not fixed here

`C2` — `Workspace.remove()` checking references outside its lock, which can leave a workspace that
`Workspace.open()` refuses — is filed as `docs/issues/043` and left for a pass of its own. The
reason is recorded there: `run_records.py` documents two prior attempts to fix a neighbouring race
by reordering around a lock, both of which made it measurably worse and were reverted. A lock-scope
change here needs a concurrency test that fails on the current code first.

`C4` — the third lock implementation raising a bare `TimeoutError` — is subsumed by the audit's own
§1.2 and is not reachable from a shipped command today.
