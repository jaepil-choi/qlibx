# 129 — three debts that cost nothing to pay

**Closes:** `docs/issues/archive/047`, and OS-2 of `docs/diagnostics/archive/2026-08-18-vqapr-review.md`.
**Step:** 0 of `docs/refactoring/2026-09-02-the-convergence-campaign.md`.
**Branch:** `step-00-the-cheap-debts`.

## Why this exists

Three things were true of the tree that had nothing to do with each other except that all three
were cheap, none had been done, and each was visible to a user before they wrote a line of their
own code. The campaign puts them first for exactly that reason: they are the only items in it with
no dependency on any other item.

The fourth item on that step — closing two documents whose direction was inverted by records `104`
and `124` — is documentation-only and carries no record, per `AGENTS.md`.

## What changed

### 1. Two runtime dependencies removed, one moved, one kept for a reason grep cannot see

`pyproject.toml` declared seven runtime dependencies. Four of them had no `import` anywhere in
`src/vqapr`.

| package | disposition | why |
|---|---|---|
| `cvxpy` | **removed** | zero occurrences in the repository. It pulled `highspy`, `osqp`, `scs`, `qdldl`, `scipy`, `sparsediffpy`, `joblib`, `setuptools`, `jinja2` and `markupsafe` behind it |
| `pydantic` | **removed** | zero occurrences. Pulled `pydantic-core`, `typing-extensions`, `typing-inspection` |
| `pandas` | **moved to `[dependency-groups] dev`** | not a runtime dependency. Its only importers are `tests/acceptance/test_figure_03_neutralization.py:30` and `scripts/extract_report_figure_03_fixture.py:41`, both fixture-building. The package's own numeric work is `Decimal` and duckdb |
| `pytz` | **kept** | see below |

`uv sync` removed **17 distributions** from the environment.

**`pytz` is the interesting one, and it is why this item is not a `grep -L` script.** Nothing in
`src/vqapr` imports it, so every static check calls it unused. It was removed, and two existing
tests in `tests/data/test_scan.py` immediately failed with

```
_duckdb.InvalidInputException: Invalid Input Error: Required module 'pytz' failed to import,
due to the following Python exception: ModuleNotFoundError: No module named 'pytz'
```

**duckdb imports it at runtime, from inside its own extension code, and does not declare it.** The
failure surfaces on reading a `TIMESTAMP WITH TIME ZONE` column — which is every dataset this
package registers, because `available_at` must be tz-aware. So it is our dependency because our
dependency will not declare its own, and the comment in `pyproject.toml` says so where the next
person to run a static check will read it.

The campaign's acceptance condition for this item anticipated the case in these words: *"넷 중
하나라도 실제로 필요하면 그 import를 찾아 이 항목에서 빼고 이유를 적는다."* This is that.

### 2. duckdb's progress bar no longer lands in the JSON envelope (`docs/issues/archive/047`)

Both places in `data/scan.py` that open a duckdb handle now go through one `_configure`, which sets
`preserve_insertion_order=false` as before and `enable_progress_bar=false`, which is new.

The issue reported a *successful* command whose reply did not parse:

```
  95% |##################################  | (~2 seconds remaining)  {"ok": true, "registered": ...}
```

Carriage-returned progress frames and the envelope on one stream, because duckdb renders that bar
to stdout even when stdout is a pipe, and stdout is where the CLI writes its reply.

**What was measured while fixing it, because it changes what the fix has to be.** `enable_progress_bar`
is `LOCAL` scope in `duckdb_settings()`, and two consequences follow that a one-line patch would
have got wrong:

- **A cursor does not inherit its parent's value.** A database set to `true` hands out cursors
  reading `false`, and a database set to `false` would hand out cursors reading whatever the
  default is. So `ScanSession.connection` must configure each cursor, not the database it shares.
- **The default is the host's decision, not a constant.** duckdb 1.5.5 turns the bar **on** when
  `__main__` has no `__file__` — a REPL, a notebook, `python -c`, an embedding host — and off when
  it does. Measured directly: `python -c "...duckdb.connect()..."` reports `True`, the same code in
  a script file reports `False`.

That second fact is why the test cannot simply assert the bar is off on a factory's connection:
under pytest it is off anyway, so such a test would pass against a `_configure` that did nothing.
`test_configure_silences_a_connection_that_was_printing` turns the bar **on** first and asserts
`_configure` turns it back; `test_both_connection_factories_route_through_configure` is then the
regression guard on the two call sites.

### 3. A boundary test that a stale `__pycache__` could fail

`tests/boundaries/test_internal_holds_no_extension_authority.py` asserted
`not Path("src/vqapr/_internal/extensions").exists()`. Record `110` moved those modules to
`vqapr/extension/`, but the directory survives in any working copy that predates it, because
`__pycache__/` is untracked and `git` does not remove it.

**So the test failed on a tree that is correct.** It was found failing on this machine at
`develop @ 1ec2b8d7` with the rest of the suite green — a red suite that says nothing about the
rule it guards is worse than no test, because the next person learns to skip it.

It now globs `*.py` in that directory and reports the offending module names. The rule it enforces
is unchanged: an implementation must not live there. Bytecode left by one that used to is not an
implementation.

## Trade-offs

**Removing a declared dependency is a breaking change for anyone who was importing it through us.**
`cvxpy`, `pydantic` and `pandas` were reachable in an environment that installed `vqapr`, and code
that relied on that now needs its own declaration. That is the correct outcome — depending on a
package's transitive closure is depending on something it never promised — and it is why this is in
a step of its own rather than folded into a release.

**`_configure` is one function for two settings with different scopes.** `preserve_insertion_order`
is `GLOBAL` and would carry from the database; setting it per cursor is redundant. Keeping the pair
together is worth the redundancy: the alternative is two call sites that each remember a different
half, which is the shape the bug had.

## Validation

```
uv sync                                          17 distributions removed, then pytz restored
uv run ruff check src/                           All checks passed
PYTHONUTF8=1 uv run pytest tests/ -q -rs         1294 passed, 14 deselected
PYTHONUTF8=1 uv run pytest tests/ -q -m "" -rs   1308 passed (13 slow journeys included)
```

Baseline on `develop @ 1ec2b8d7`, measured on the commit this branched from rather than quoted from
a document: **1292 passed, 14 deselected**. The delta is exactly the two progress-bar tests; the
boundary test was rewritten in place and the dependency change adds none.

Directed checks:

- `pytz` removal reproduced the duckdb failure in `tests/data/test_scan.py`, and restoring it
  cleared both failures.
- The boundary test was run with `src/vqapr/_internal/extensions/__pycache__/stale.pyc` present
  (passes) and then with `src/vqapr/_internal/extensions/loading.py` present (fails, naming the
  file). Both artefacts removed afterwards.
- duckdb setting scope and default read out of `duckdb_settings()` and by direct comparison of a
  `-c` invocation against a script file.
