# `vqapr check` — four phases, eight judgments

## What it does

Runs every independent judgment it can and reports **all** of them in one call. A run with four
defects costs one command, not four rounds of fix-and-retry.

It writes nothing. Note that judging a component means importing it, and an imported module is
user code that can do as it pleases — the guarantee is about this package, not about a sandbox.

A judgment that could not run because an earlier one failed is reported as **blocked**, naming what
blocked it, so a partial report never reads as a complete one.

## The counting trap

The envelope's `checked` list has **four** entries — `workspace`, `run`, `judgments`, `preflight`.
The eight judgments all happen inside the one named `judgments`.

Counting the envelope's list and expecting eight is the obvious mistake. It is four, and nothing
is missing. Do not report a shortfall.

## `run` makes the same judgments

`vqapr run` re-makes every judgment `check` makes before it freezes anything. A run that would fail
`check` is refused rather than executed.

So `check` is not a required step — it is the cheap one. Its value is that it costs no execution
and reports everything at once.

## When check passes and run still refuses

Preflight happens at run time against state that can move: a lock another process holds, a
materialized dataset that was withdrawn between the two commands, an exchange listing that a
registered roster no longer covers.

Read the refusal's `stage` — it says which of the four phases closed.

## Waiting rather than fixing

Two statuses mean the command was fine and the moment was not:

- **423** — something is locked. Another process holds the run, or a record is being written.
- **503** — a resource is temporarily unavailable.

**Retry the same command unchanged.** Nothing in the declaration needs to change, and changing it
is how a transient becomes a permanent edit.

### A lock inside its heartbeat window does not mean the holder is alive

`vqapr run` claims each strategy's record with a lock it refreshes as it writes. So a refusal
saying the id is *held by a lock inside its heartbeat window* means only that **the lock was
touched in the last 120 seconds** — not that anything is still running.

**The pid in that message is copied out of the lock file, never interrogated.** A run killed by
Ctrl-C, a CI timeout or an OOM kill leaves exactly this state, and inside the window nothing can
tell it from a run that is executing.

That lock **releases itself 120 seconds after its last refresh**, and the refusal states how many
seconds are left. Re-running the same command after that reclaims the record with no flag and no
cleanup.

**Waiting is the answer that is safe under both readings.** Once the lock has aged out,
`vqapr rm strategy <run-id>/<strategy-id>@<fp8>` clears an abandoned record. `--force` is safe
under neither: against a run that really is live it destroys rows that run is still writing.

If the same status returns after a wait, say so and stop rather than escalating to a destructive
verb.
