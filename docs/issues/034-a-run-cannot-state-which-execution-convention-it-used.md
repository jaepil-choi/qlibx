# 034 — A run cannot state, and `show run` cannot report, which execution convention it used

**Status: STILL OPEN as of 2026-09-01, and the record that was supposed to close it did not.**
Step 10a of the structural plan carried this issue's acceptance verbatim — *"two runs at different
execution conventions produce records that **differ in `execution`**"* — and
`docs/implementations/115-the-run-record-knows-its-kind.md` closed Step 10a without it.
`_RUN_FIELDS` at `src/vqapr/flow/run_records.py:67` is `run_id`, `account`, `tables`, `contract`,
`source_digest`, `declared_digest`, `roster`, `period`. There is no `execution`, and `contract` is
the constraint report (`flow/records.py:100`), not a convention. Record 115 delivered the
kind discriminator and the reader-side schema check and does not mention 034 at all.

**What 10a did buy this issue:** the record is now kind-discriminated with a versioned schema and a
reader that refuses a major-version mismatch, so adding `execution` is now an additive field on a
declared field set rather than a shape change to a flat tuple. The remaining work is the field and
the ordering vocabulary behind it, not the plumbing. See the erratum in record 115.

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-009**
(`blocked` / `code`) and **F-016** (`papercut` / `code`); one issue, because F-016 is the same gap
observed from the read-back side. The reporter named F-009 *"the finding I would most want upstream
to see."*
**Touches:** the run record and `vqapr show run`; the ordering rule stated in
`vqapr new agendas` and `vqapr new execution-input`.

## The sentence the reporter wanted to say and could not

> *"Form the weight from this session's close and execute at this session's close — I know that is
> an idealisation, record the run as idealised."*

## The ordering rule, and why it is right

Two independent statements, each found on the surface, each individually correct:

- `vqapr new agendas`: a callback at `15:29` *"sees only data whose `available_at` is strictly
  before 15:29"*.
- `vqapr new execution-input`: `at:` — *"execution must be STRICTLY LATER than the strategy
  callback"*.

Compose them and **observe < decide < execute** is forced, with no way to collapse any two. A
callback that can see session t's 15:30 close must fire after 15:30, and its execution then falls
later still — the next session at the earliest.

The paper being replicated (Guijarro-Ordonez, Pelger, Zanotti 2025, s3.1: *"The arbitrage strategies
trade on a daily frequency at the close of each day"*) forms the weight from the close of t-1 and
executes at that same close. Implementation lag: zero. **vqapr forbids that, and vqapr is right** —
trading at a closing price you have already observed is only physically possible via a
market-on-close order submitted before the close is known, i.e. before the signal exists. A
point-in-time framework structurally forbidding a look-ahead the literature routinely assumes is a
defensible product position, arguably the whole point.

**Nothing in this issue asks for that to change.**

## The gap

The refusal is silent and total. There is no `idealised: true`, no acknowledged-look-ahead flag, and
**no run-record field that says which convention a run actually used.**

The choice offered is: reproduce the paper and be unable to, or produce a lagged variant and have
the run record claim, with no qualification anywhere in it, that this is the paper's design. The
reporter took the second, on the user's explicit ruling that the paper is the one getting it wrong.

The result: every number the run produced is a one-session-lagged variant, and a reader of
`vqapr show run` finds nothing distinguishing it from a zero-lag run. `period`, `contract`,
`roster`, `declared_digest`, `source_digest` and every table can be **identical** between the two;
only the numbers differ, and only if you have both.

## What that costs, concretely, in this run's own numbers

The reporter's K=0 arm returned **Sharpe -1.03** (annualised mean -8.13%, vol 7.87%, over 243
sessions). Their note:

> A short-horizon reversal strategy run one session late is expected to do this — you buy after the
> bounce — so the sign is information about the lag, not only about the strategy. A reader of this
> run record has no way to know that the lag is there.

## F-016: the read-back path is good, and this is the one thing missing from it

Recorded because it is evidence about what works. `vqapr show run <id>` gave the full record in one
call: `period` with 732 occurrences, `contract.accepted_intents: 244`, per-table row counts
(`vqapr.account` 31,502 rows over 244 formations; `vqapr.fill` 47,318; `vqapr.weight` 32,045), the
closing account, and both digests. `--table vqapr.account --limit 0` returned every row with all
five envelope fields present.

One detail worth crediting because the scaffold predicted it: the agendas template warns that
valuing at 15:29 would lag NAV by a session and says to value *after* the execution instant. Valuing
at 15:31 gave a first NAV of exactly `100000000000.0` — the initial cash, to the digit.

The record answers **what happened**. It does not answer **under what convention**.

## Relationship to 027

027 asks for a point-in-time convention to be *spoken aloud at declaration time*. This asks for the
convention a run actually executed under to be *recorded in the run's own artifact*. They compose:
027 catches an unexamined choice at `register`; this makes the choice legible afterwards to a reader
who was not there. The reporter's summary of the pairing —

> The framework's own stated reason for existing is that a convention which is wrong in meaning is
> still well-formed and it cannot detect one. Here it has done better than that — it has made an
> unachievable convention *unstateable*. Having gone that far, the missing half is a way to record
> which convention a run actually used.

## What to settle

Whether the run record carries the decide/execute relationship in words — a lag in sessions, or the
callback and execution instants side by side with the gap named — so that the difference between a
lagged replication and a published zero-lag number is legible in the artifact rather than only in a
findings file.
