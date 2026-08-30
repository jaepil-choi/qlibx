# 015 — `run` does not make the judgments `check` makes

**Status when filed:** open. Found 2026-08-30 by the final first-time-user journey in
`kwam-enhanced-index/vqapr-final-testbed/` — a Fama-French 3-factor replication over 2,251 KRX
instruments, 2019-07 to 2026-07, against the built wheel `vqapr-0.2.0a1`. Recorded there as
**F-010**, the only `blocked` entry in a fifteen-entry log.
**Touches:** `src/vqapr/cli/run.py`, `src/vqapr/cli/check.py`.

## What happened

The agent moved the fill to T+1 by putting the callback *after* the close it reads (15:31) with
`selector: next_eligible`, so the same session's 15:30 instant would already be in the past.
`check` refused it, and the journey calls this the best-formed failure of the entire run:

```json
{"code": "check.execution.not_after_decision",
 "explain": "run-precondition",
 "fix": "move the strategy cadence earlier than 15:30:00, or declare a fill convention whose
         instant is later than every decision",
 "observed": "fill at 15:30:00; 85 occurrence(s) at or after it",
 "requirement": "every decision must be strictly earlier than the instant it fills at",
 "source": {"file": "declarations\spec_t1.yaml", "key_path": "strategy.agenda_id", "line": null},
 "examples": ["ff3-t1-form-2019-07-01", "ff3-t1-form-2019-08-01", "..."], "example_total": 85}
```

`ok:false`, with `passed: ["spec","workspace","declaration","preflight"]`. The phase that failed is
`judgments`.

Then, on the same unmodified spec:

```
$ vqapr run declarations/spec_t1.yaml --run-id ff3-t1-2019-2026
{"ok": true, "stage": "run.complete", "account_version": 85, "occurrences": 255, ...}
```

24 seconds, 85 rebalances, a complete run record on disk.

## Why it is the most serious entry in that log

- **The defect is a look-ahead, by the package's own definition.** `check` names the topic
  `run-precondition` and the requirement is *every decision must be strictly earlier than the
  instant it fills at*. A decision that is not strictly earlier than its own fill is trading on
  information you do not have. This is the exact failure mode the skill's `available_at` section
  spends two pages on, the framework has a check for it, and `run` does not run that check.
- **The artifact is indistinguishable from a good one.** `vqapr list runs` shows
  `ff3-t1-2019-2026` beside two legitimate runs of the same shape; `vqapr show run` reports it
  without complaint. Nothing on the record says `check` had refused the spec that produced it.
  There is also no command that deletes a run, so the invalid record is permanent.
- **The documented framing points the wrong way.** `run`'s contract in the skill is "freeze a run
  spec, preflight it, and execute the simulation", and `run --help` says "Preflight refuses any
  drift". Preflight *passed* in `check` too — the refusal came from `judgments`, and nothing tells
  the reader that `run` skips it. The skill sells `check` as "prove it before spending a run",
  which reads as *check is the cheap way to learn what run will tell you*. It is instead a strictly
  stronger gate, and a user who never types `check` — which the CLI permits — gets no protection at
  all.

The reporter's own summary: *"The sentence I most wanted to say and could not: `check` and `run`
enforce the same rules, so a green `run` means what a green `check` means."*

## Confirmed in this repository

`_Phase("judgments", ...)` and `_judgments` live in `src/vqapr/cli/check.py` only
(`check.py:123`, `:137`, `:211`, `:225`, `:455`). `grep -n judgments src/vqapr/cli/run.py` returns
nothing. The eight judgments are a `check`-verb concern, not a run-assembly concern, which is why
the gap is structural rather than a missed call site.

## The decision this needs

Not "add the check to `run`" as a mechanical edit — the shape of the answer is a product decision:

1. **`run` performs `judgments` and refuses.** The strongest guarantee and the one the
   documentation already implies. Cost: a run can now fail after freezing a spec, and every
   existing spec that `run` accepts today but `judgments` would refuse becomes unrunnable.
2. **`run` performs `judgments` and records the verdict on the artifact**, refusing unless a flag
   says otherwise. Keeps the escape hatch this journey actually used — it left the invalid run in
   the store deliberately, as the evidence for this file — while making the record self-describing.
3. **`run` states plainly that it does not judge.** The docs-only answer: `run --help` stops saying
   "Preflight refuses any drift" without naming what preflight is not. This does not close the
   hole; it only stops the surface from claiming the hole is closed.

Option 2 preserves both properties the journey demonstrated it needs: a green `run` must mean
something, and a deliberately-invalid run must still be producible as evidence.

**Whichever is chosen, the run record must carry the verdict.** A permanent artifact with nothing on
it recording that `check` said no is the part that costs a reader a wrong answer they cannot see.

## Not the same as 012

`docs/issues/012` was `check` refusing a spec that `run` completes, and the answer there was that
the **judgment** was wrong — a lookback measured at `start` rather than at the first decision. Here
the judgment is right and `run` never asks it. Same observable shape, opposite cause.
