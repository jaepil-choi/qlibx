# What counts as a defect, and what the status codes mean

The envelope carries the triage decision most of the time. Read `status` first, then `fix`.

## The status codes

`status` says **who must act**, and that is the whole triage question.

| status | who must act | file a report? |
|---|---|---|
| **400** usage rejected | you — the arguments are wrong | Only if `fix` is absent, wrong, or names something that does not exist |
| **404** not found | you — the name is not registered | Only if the thing *is* registered and the refusal cannot see it |
| **409** conflict | you — a name is taken, a lock is held by a real holder | Only if nothing actually conflicts |
| **422** declaration rejected | you — the declaration is unsound | Only if `fix` does not resolve it, or `run` accepts what `check` refused (or the reverse) |
| **423** locked | nobody — another process holds it | **No.** Retry unchanged. File only if it never clears and no other process is running |
| **500** unhandled | **vqapr** | **Always.** A 500 is by definition a defect: an exception nobody turned into a judgment |
| **502** your code raised | **you** — `cause.origin` is `"user"`, `cause.where` is your file and line | **No.** Fix the component and re-run. File only if `origin` is not `"user"`, or a package helper you called correctly raised inside your callback |
| **503** unavailable | nobody — the machine: a file that exists could not be read, a disk was full | **No.** Retry unchanged. File only if it never clears. (A path that is not there is a **404**, not a 503) |

A 500 that you can work around is still a 500. Work around it *and* file it — the workaround is
evidence of impact, not a reason to stay quiet.

## The four kinds worth filing

**1. The envelope was wrong about itself.** `fix` names a flag that does not exist, `observed`
shows a value you did not supply, `source` points at a file that has nothing to do with it, or
`requirement` restates the failure instead of stating the requirement. These are cheap to fix and
expensive to hit, because a wrong `fix` costs everyone who reads it the same time it cost you.

**2. Two parts of the package disagree.** `check` passes and `run` fails on the same declaration.
`list` shows something `show` cannot open. A skill or `--help` promises a command, flag, default
or column that is not there. Two commands report different values for the same fact. Say which
two, and quote both.

**3. A number is wrong.** The heaviest kind, and the hardest to notice: nothing refuses, the run
completes, and a value is not what the declaration should have produced. Give the value you got,
the value you expected, and how you computed the expectation. If your expectation came from an
external reference implementation or a paper, say which — that is what makes it checkable.

**4. Friction.** No refusal, nothing wrong, but the work cost far more than its shape justified:
a required step nothing documented, a concept you had to reconstruct from three docstrings, a
default you had to discover by experiment, an operation that took minutes where seconds were
plausible. **File this before you resolve it.** Once you know the answer you can no longer see
what was missing, and the friction report is the only artifact that captures it.

## The borderline cases

| situation | do this |
|---|---|
| It failed once and you cannot repeat it | File it, and say "1 of N, could not reproduce" in Reproduction. An unrepeatable 500 is still a 500 |
| You are not sure whether it is your mistake | File it, and say so in one line. A maintainer closing a report costs less than a defect nobody mentioned |
| You already found the workaround | File it anyway, with the workaround under Impact |
| It is slow but correct | File as friction, with a measurement — "6.2 s" not "slow" |
| The docs are unclear but the behaviour is right | File as friction against the docs, and name the file and line |
| You hit the same defect twice in one session | One report. Say it happened twice and in what two contexts |
| Two different defects in one command | Two reports. One file per problem, or triage cannot close either |

## What not to put in a report

- **A cause you did not verify.** You cannot see inside the package from here, and a confident
  wrong cause sends the fix to the wrong layer. State what you observed and stop.
- **A patch.** Suggesting a message is fine. Suggesting an implementation is not — you have not
  read the code, and the skill forbids reading it.
- **Prose restating the envelope.** Paste it and move on. The fields are already the summary.
- **Anything from the upstream repository.** If your report quotes upstream source or upstream
  documentation, the finding is contaminated: it is no longer evidence about the public surface.
