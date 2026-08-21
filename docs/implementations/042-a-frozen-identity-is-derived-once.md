# 042 — A frozen identity is derived once

## Why this exists

Round one of the hot-path work (records 021–023) closed on the conclusion that "almost all
remaining vqapr time is in `observation_rows` itself". A fresh end-to-end scaling harness says
that was not true. Driving the sample panel through `register → preflight → run` at increasing
session counts:

```text
     K    occ   register  preflight        run    ms/occ
   100    400      0.99s      0.12s      2.31s     5.79
   200    800      1.89s      0.19s      5.77s     7.21
   400   1600      3.59s      0.35s     19.44s    12.15
   735   2940      6.44s      0.63s     64.23s    21.85
```

Per-occurrence cost nearly doubles every time K doubles. **The run was still quadratic in its own
length**, and the term was not in the scan layer.

`FrozenRun.identity` was an uncached `@property`. Deriving it walks the three agendas and
json-encodes and sha256s **every occurrence** of each. A run reads that identity about sixteen
times per callback — `simulation.py` alone has fourteen call sites — so a run of N occurrences did
O(N) hashes per callback and O(N²) in total. On show_005, twelve occurrences per agenda produced
55,944 `OperationOccurrence.content_identity` calls.

The second term was the workspace file. It stores every agenda occurrence, so it grows with run
length rather than with the number of declarations, and it was parsed with PyYAML's pure-Python
loader even though this environment ships libyaml. At 2,500 occurrences the file is 767 KB: 1.1 s
to load, 0.5 s to emit. Every registration paid two loads — `Workspace.create` reads the file, and
the `register_*` it is called for reads it again inside the exclusive lock, discarding the first.

## What changed

Eleven items, all of them result-invariant. The ones that changed a cost shape:

**Identity memoization.** `FrozenRun._identity`, `OperationAgenda._content_identity` /
`_provenance_identity`, and `OperationOccurrence._content_identity` are
`field(init=False, compare=False, repr=False)` memos filled on first read. Every one is derived
from fields of a `frozen=True` dataclass whose `__post_init__` has already normalized them, so
the value cannot change. Lazy rather than eager because decoding a workspace builds every
occurrence and asks none of them for an identity.

**Workspace persistence.** `yaml.CSafeLoader`/`CSafeDumper` when the installed PyYAML has them,
the pure-Python classes otherwise. The emitted bytes are identical between the two dumpers for
every document this module writes. `_decode` is memoized on the sha256 of the exact text, which
collapses the double read without weakening the lock: a hit is only possible for bytes that were
already decoded, so no writer in any process can be served a stale workspace.

**`RowsLookback` gets a lower bound.** A `RowsLookback` declares a count, not a span, so there was
nothing to push into SQL and the ranking window ran over the source's whole history on every
callback. It now estimates one from a session-cached grid of the source's distinct availability
instants, then **checks the estimate**: an instrument with `rows` non-null values of every
declared field inside the bound is provably unaffected by it, and every other instrument —
including a halted name that published nothing in the window — is read with no bound at all, in
the same statement. Gated on source size, because on a small source the check costs more than the
scan it avoids.

**Smaller repeated work.** `store.query` hands its already-normalized rows to
`ObservationBatch._trusted` instead of having them validated a second time; `InvocationRecorder`
detaches its staged rows instead of re-normalizing them, and compares row shape against a set
`TableSpec` builds once; `AcceptedRunState.__post_init__` compares key views instead of building
sets and re-checks only refs no earlier root proved; `ScanSession` opens one duckdb database and
one cursor per source instead of one whole in-memory database per source; `_execution_horizon`
borrows the run's session instead of opening a connection.

## Trade-offs

- The estimated lower bound never reaches `AccessRecord`. Evidence records the lookback the run
  *declared*; the bound is a query plan, not a fact about the data, and putting it in the record
  would make identical runs produce different evidence.
- `ROWS_BOUND_MIN_BYTES` is a threshold, and a threshold is a guess about hardware. It is set
  where measurement put the crossover, and being wrong in either direction costs speed, never
  correctness.
- The decode cache holds at most eight workspaces and clears wholesale when full. A workspace with
  a long agenda is not small, and this is a hot-path cache, not a store.

## Declined, with the reason

**`AccountState` incremental mark validation.** The finding assumed `mark_history` grows with run
length. It does not: `Account` keeps `[-retained_marks:]`, and `retained_marks` is the largest
declared `RowsLookback` (one when nothing is declared). `__post_init__` is already bounded.

## Measured

Same harness, same panel, same final NAV at every K:

```text
     K    occ   register  preflight        run    ms/occ    (before -> after)
   100    400   0.99->0.32  0.12->0.06   2.31->1.15    5.79->2.88
   200    800   1.89->0.54  0.19->0.06   5.77->1.22    7.21->1.52
   400   1600   3.59->0.84  0.35->0.07  19.44->2.45   12.15->1.53
   735   2940   6.44->1.55  0.63->0.09  64.23->5.16   21.85->1.76
```

At K=735 that is 71.30 s → 6.80 s, **10.5x**, and per-occurrence cost is flat instead of doubling
with K. show_005 wall time 4.97 s → 3.54 s.

The lower bound measured on a real warehouse (`data/vqapr-dev/price_daily`, 8.7M rows, 210 MB, 200
instruments, `RowsLookback(60)`, nine evaluation times): **165 ms → 90 ms per query, 1.83x**, rows
identical, against a one-time 41 ms grid read.

## Validation

```text
uv run pytest -q                          646 passed  (639 + 7 new guards)
uv run ruff check src tests               All checks passed
.agent/tmp/g4r2_check.py                  G-4 PASS: 64 fields identical to baseline
```

G-4 compares two show_005 replicates against a frozen snapshot: both artifact digests, final NAV,
committed cash, replayed positions, fill counts — 64 flattened fields, identical throughout.

`tests/flow/test_hot_path_costs.py` gains G-1: a panel whose third name stopped publishing 340
sessions before the evaluation time, asserting that the bounded query returns the sessionless
unbounded result exactly, that the halted name still carries its five newest closes, that the
instant grid is read once per source, and that a small source is never probed. **The guards were
proved sensitive**: reverting the fallback in process — keeping the estimated bound, dropping the
list of instruments it is unsafe for — turns five of them red, and the halted name comes back with
zero rows instead of five.
