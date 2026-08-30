# 037 — The run lock heals itself after two minutes, and no message says so; inside that window a killed run is reported as live and the only remedy is argued against

**Status:** **CLOSED 2026-08-31** by `docs/implementations/099-the-run-lock-says-what-it-knows.md`
(branch `fix/037-run-lock-states-what-it-knows`). The refusal states the lock's age, says the pid was
not interrogated, names the automatic release with the seconds remaining, and puts the wait ahead of
both flags; `--force` is hedged on the premise it depends on. The skill's `workspace-state` section
gained the run-lock paragraph the workspace lock already had.

**No pid liveness check**, which this file's correction section already argued against: the
heartbeat is the evidence the design chose, and what was missing was saying so. One extra defect
surfaced while testing — a lock read microseconds after it was written could report a negative age,
which would have reached an operator as `-0s ago`; the age is now clamped at zero.

**Status when filed:** open. Found 2026-08-30 by the first-time-user journey in
`kaist-thesis/vqapr-final-testbed/`, against `vqapr-0.2.0a1`. Recorded there as **F-014**,
`slowed` / `message`.
**Touches:** `src/vqapr/cli/run.py:590-601` (the `RunRecordLive` refusal);
`src/vqapr/flow/run_records.py:143-170` (`LOCK_FILENAME`, `LOCK_STALE_AFTER`, `_lock_holder`);
`SKILL.md`'s `workspace-state` section.

## What happened

A `vqapr run` was killed by the reporter's own two-minute tool timeout, 216 of ~246 callbacks in.
The identical command, re-run immediately, was refused in 2 seconds:

```json
{"ok": false, "stage": "cli.input", "error": "InputError: a run id must not already be executing",
 "code": "cli.input.value_invalid",
 "observed": "'run_ou_k0_2024' is running now at .vqapr/runs/run_ou_k0_2024 (pid 64004)",
 "fix": "wait for that run to finish, or run with --run-id <new-id>. Do NOT use --force: it would
         destroy the rows that run is still writing"}
```

`Get-Process -Id 64004` returned nothing. **The named process did not exist.**

## Correcting the report, because the mechanism is better than the reporter could see

The reporter concluded *"it never checked"* and proposed a pid liveness check. That reading is
wrong, and the truth is more interesting.

`run_records.py` already handles a dead holder, by heartbeat rather than by pid:

- `LOCK_STALE_AFTER = 120.0` — *"a HEARTBEAT threshold, not a run-duration budget"*.
- `append` touches the lock as it goes, so a run doing anything keeps its claim.
- `_lock_holder` returns `None` for a lock unrefreshed for more than 120 seconds: *"its process
  died without releasing, and refusing forever on a dead holder would make a crash unrecoverable."*

The design is deliberate and the docstring argues for it convincingly, including against the
duration-budget reading that would break real runs. It landed 2026-08-27, so it **is** in the
0.2.0a1 wheel this journey used.

**So what actually happened is that the lock was less than 120 seconds old.** The kill and the
re-run were seconds apart. Inside that window a killed run and a live one are indistinguishable by
construction, and that is the intended trade.

## The finding, restated

The mechanism is sound. **Three of its consequences reach the user as wrong information.**

1. **The message asserts liveness in the present tense** — *"is running now ... (pid 64004)"* — for
   a state the code only knows as *"this lock was touched recently"*. It prints a pid it did not
   interrogate. A reader who checks that pid, as this one did, concludes the package is lying.
2. **The one remedy that works is argued against, in bold, on a premise that may be false.**
   *"Do NOT use --force: it would destroy the rows that run is still writing"* is exactly right for
   a live run and actively harmful for a dead one, and the message cannot tell the two apart.
3. **The actual remedy is nowhere.** Waiting ~120 seconds clears the lock automatically. That is the
   correct, safe, zero-cost answer to this exact situation, it is implemented, and it appears in no
   message and nowhere in `SKILL.md`. What the message says instead is *"wait for that run to
   finish"* — which for a dead holder reads as **wait forever**, and is the first thing a reader
   will try.

The remaining suggestion, `--run-id <new-id>`, works and is what the reporter used. It is recovery
by abandonment: the dead run directory stays in the workspace forever, and every future re-run of
that spec must remember a fresh id.

## The package already has the right paragraph, one lock over

`SKILL.md`'s `workspace-state` section says, of the **workspace** lock:

> *"If nothing else is running, a lock file was left behind by a process that died, and removing it
> is safe once you have confirmed no vqapr command is live."*

The **run** lock has no equivalent sentence, and its refusal — unlike the workspace one — never
raises the possibility that the holder is dead. The concept and the remedy are both already written
down; they are attached to the other lock.

**Cost:** ~6 minutes — reading the message, disbelieving it, checking the pid, searching the skill
for a run-lock analogue of the workspace-lock paragraph, finding none, taking the `--run-id` escape.

## What would close it

One sentence in the refusal naming the self-healing behaviour and its threshold, and hedging the
liveness claim to what is actually known:

> *"`'run_ou_k0_2024'` holds a lock last refreshed Ns ago at `<dir>` (pid 64004). A live run
> refreshes it continuously; if that process is gone the lock is released automatically after 120s.
> Wait, or run with `--run-id <new-id>`. Do not use `--force` while the holder may be live."*

Killed runs are not exotic — CI timeouts, Ctrl-C and OOM kills all produce exactly this state, and
all of them produce it seconds before the operator retries, which is precisely inside the window
where the message is at its most confident and least correct.
