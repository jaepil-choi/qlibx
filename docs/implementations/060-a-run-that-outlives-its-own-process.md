# A run that outlives its own process

## Why this exists

`recorder_rows` lived in memory for the whole run (`flow/run_state.py:65`). A run that crashed left
nothing; a run that finished left nothing anyone else could read. Two consequences, and neither is
a convenience:

- **Parallel execution was impossible.** Five processes running five factors each hold their
  results in their own memory, and nobody can read all five afterwards.
- **`show run <id>` had nothing to show.** The only way to answer a question about a finished run
  was to run it again — which is a different run, and answers a different question.

## The layout

Argued in full in `docs/design/run-record-layout.md`, written before the code because it constrains
Step 6's `store.root` and because a layout is expensive to change once records exist.

```
<store.root>/runs/<run-id>/
  record.json            account, table counts, contract report, source digest, derived period
  tables/<table>.jsonl   rows appended in chunks as the run proceeds
```

**A directory scan, not an index file.** The obvious `runs/index.json` is wrong here for a reason
the codebase already documents: `workspace.py:53-55` explains that atomic replacement stops a
reader seeing half a file but does *not* stop two processes each reading the state, each appending
their own entry, and the second write erasing the first. Nothing fails; an entry is simply gone. An
index would put all five concurrent writers on exactly that target and force every run to take the
workspace lock to record its own existence — serialising the one thing AC-R4 asks to be parallel.
Scanning has no shared mutable target, so two runs cannot collide by construction. Listing becomes
O(runs); at one directory per research run that is not worth buying a silent lost-update to avoid.

**The writer appends in chunks.** `append` takes a chunk at a time and never rewrites what it
already wrote, so a caller that streams rows as it produces them gets crash survival and bounded
memory for free.

What the product does with that today is narrower, and worth stating rather than implying:
`public.run` hands over `recorder_rows` once, after the run returns, so current records are written
in a single pass at the end. The chunked interface is what makes streaming possible later; it is
not a claim that the run streams now.

**`record.json` written last, atomically.** Its existence is what marks a record complete. A
writer killed between chunks leaves its rows and no record, and `run_ids` declines to list it — reporting it as a
finished run whose facts are missing would be worse than not reporting it.

**The claim is liveness, and it took three attempts to get right.**

First attempt: the directory's existence is the claim, via a `mkdir` that exactly one process wins.
Correct for concurrent runs, but it made a crashed run hold its id forever — the operator paid a
destructive `--force` to clear leftovers no reader would ever have returned.

Second attempt: treat a record-less directory as free and clear it. That made the claim two steps —
remove, then create — and two steps cannot be atomic. Five real processes racing one id all saw no
record, all removed, and **two then created**, in roughly one run in three.

Third attempt moved the clearing behind `--force`, which looked safe because a deliberate replace
is *expected* to be single-writer. An expectation is not a guarantee, and a reviewer found the case
that needs no race at all: run A holds an id and is appending; the operator forces the same id; B
removes A's directory and creates its own; A's next append re-resolves the path — `append` opens
and closes per chunk and holds nothing — and writes into B's. Both finish into one record. Measured
directly, the surviving record held `['B1', 'A2']`: two runs, listed as one.

The claim is now **liveness**, using the lock this repository already uses for the workspace
(`workspace.py:987`). `O_CREAT | O_EXCL` succeeds for exactly one process on Windows and POSIX
alike, the holder's pid rides inside the file, and a lock older than `LOCK_STALE_AFTER` belongs to
a run that died.

**That last sentence is only true because the run refreshes its lock, and getting this wrong
recreated the very defect it fixes.** `LOCK_STALE_AFTER` is a *heartbeat* threshold, not a
run-duration budget. Read as a duration budget it is catastrophic here: a factor run over this
testbed takes three to six minutes against a two-minute window, so every real run would age out
while still executing and any peer could take its id with no flag at all.

The first attempt at the refresh was worse than none, because it looked correct and tested green.
It heartbeated inside `append`, and a test drove `append` directly and passed — but in the product
path `append` runs only from `_freeze_record`, *after* `flow.run()` returns. The lock was stamped
once at `open` and never touched again for the entire run. The test proved a property the product
never exercised.

So the heartbeat is driven by the run itself: `SimulationFlow` takes an `on_progress` callback and
calls it once per occurrence, before the due/static branch, so it fires for every occurrence shape
including a run that records no rows at all. Verified through `public.run` with the window shrunk
to 0.5s and a peer probing six seconds into a real run: it sees `LIVE`. Mutation-proved — remove
the hook and the same peer sees `STOLEN`.

The lesson generalises past this file: a test that drives the machinery directly can pass while the
product path never reaches it. The fix is not a better assertion, it is driving the entry point the
product uses.

- A **live** id is refused even under `--force`, with its own `RunRecordLive` naming the pid and a
  remedy that is explicitly not `--force`.
- A **dead** id is reclaimed by an ordinary retry, no flag — the cost the first design accepted is
  gone. The operator is not charged for someone else's crash.
- A **complete** record still needs `--force`, because replacing a finished result should stay
  deliberate.

One more thing had to change with it. Contending for an id is not one error: it is `FileExistsError`
from a directory, `PermissionError` from a file another process holds open, `FileNotFoundError`
from a peer removing something mid-scan. Handling them individually is what kept this failing — each
fix moved the error to the next call in the sequence — so `open` now has **one** boundary that
turns every filesystem outcome into a typed refusal. Every one that escapes would otherwise surface
as `stage: "unhandled"`, telling an agent the framework broke when two runs simply collided.

## `list runs` and `show run`

`show run` reads the frozen record and recomputes nothing. It could not: the process that ran the
simulation is gone.

AC-R5 also asks that the output and the record carry the same field set. That is guaranteed
structurally rather than by comparison — one serializer (`cli/show.py:record_view`) produces both,
so a field cannot be added to one and forgotten in the other. The test compares the two *sets*
rather than a hardcoded list of names, so a record that grows a field nobody surfaces fails.

## Two shapes, one name

Ruling 2. `CompletedRun` named two different things: `_internal/run_bridge.py:124` is the readable
projection that `run_completed` returns and that every real consumer reads as `completed.tables`,
while `project.py:353` was a publication transaction handle carrying a root, access tokens and a
`publish()`.

Two shapes under one name in one package is a coin-flip for the reader, and the readable projection
is overwhelmingly the one they meet. The handle is now `StrategyReplay`. Its capability is
untouched — `publish()` still stages, verifies and makes outputs visible through a single
catalog-root CAS, which `test_publication_atomicity.py` proves directly and which Step 6 needs for
`store.tables`.

Verified before renaming: the handle had **zero consumers** anywhere outside its own module. The
rename was safe precisely because the name was the only thing being shared.

## Contract report: what it does not claim

AC-R6 asks for `held`/`checked` per declaration, with `ok:false` plus `cause` and `fix` on
violation. Two decisions worth recording.

`held` and `checked` are reported as two numbers because conflating them hides the case that
matters most: **a declaration checked zero times is not a declaration that held.** It is one nobody
asked about, and reporting that as `ok` would be the strongest false assurance this record could
carry. So `checked == 0` reports `ok: false` with a cause saying exactly that.

And the block reports the run's **constraints** only. AC-R6 also names `weights`/`forms`/`records`,
which belong to the authoring contract that does not exist yet — Step 7 lands it. Inventing entries
for them here would report a promise nobody made, which is the same false assurance in a different
place. The scope is stated in the function's own docstring rather than implied by silence.

## Validation

```
uv run --no-sync pytest -q                                   # 1,163 passed
uv run --no-sync ruff check .                                # clean
python ../kwam-enhanced-index/vqapr-testbed-2/parity_probe.py --factors HML
```

Count gate MATCH: 2096 / 97 / 110919. This step is **not** parity-inert — the rename touches the
type `parity_probe.py` consumes — so the gate re-proves the harness itself, not only the numbers.
Value gate exact, weight digests byte-identical to the Step 0 capture.

The concurrency work is verified by repetition rather than a single green run, because the defects
it fixes are probabilistic: **14 consecutive clean runs** of the five-process suite, after each
earlier design was reproduced failing (2-winner at 1-in-3; the live-run blend deterministically in
two terminals). The five-process test spawns real OS processes and releases them through a barrier
file — without the barrier, interpreter startup dominates and the writers arrive seconds apart,
which is not a race at all and passes against implementations that are plainly wrong.

AC-R4 and AC-R5 are proved with real processes rather than in-process fakes: five
`multiprocessing.spawn` writers (never `fork` — this is Windows) each leave an intact record, and a
cold sixth process reads all five. A same-process test would pass on an implementation that never
wrote anything at all.

End to end, a real 2,940-occurrence run written by one process and read by a cold CLI:

```
$ vqapr list runs  --store-root <store>   ->  runs: ['e2e']
$ vqapr show run e2e --store-root <store> ->  account version: 729
                                              tables: vqapr.account, vqapr.fill, vqapr.weight
                                              period occurrences: 2940
```
