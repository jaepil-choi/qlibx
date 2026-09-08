# 180 — The set is nine, and the body it came from is gone

**Closes:** PRD §11.2 (the whole set), §9.6, §2.8. **Branch:** `develop`, on top of record `179`.

## What was built

**`inspect-workspace/`** — SKILL.md (131 lines) and two references: `reuse-judgement.md`,
`deleting.md`. The last of the nine.

Its job is not teaching commands — the CLI already carries `--id`, `--kind`, `--reads`, `--run`,
`--strategy`, `--fingerprint`, `--failed-contract`, `--since`. It is **translating a question into
a filter**, and the SKILL.md leads with that table. `--reads` is singled out because it loads each
component and asks it which datasets its `inputs()` names, so a dependency question is answered
from the code rather than from a convention.

`deleting.md` reframes the refusals: `rm` refuses while a registered run still names the thing
**and names the run**, which makes a refused `rm` the dependency report you would otherwise have
to construct.

**`introduce-vqapr` rewritten** — 1,019 lines to 143, with four references:
`sample-journey.md`, `mental-model.md`, `install-and-environment.md`, `reading-the-envelope.md`.

It is now orientation and routing: what vqapr is, the sample journey as the first thing to run, the
three rungs and the four extension points in one screen each, a table pointing at the other eight
skills, and how to install them.

## What was deleted, and what was kept out of it

**219 lines of per-status recovery catalogue.** PRD §11.2 ruled that failure recovery is not a
skill: the envelope carries `status`, `stage` and `cause` beside `fix`, `requirement`, `observed`
and `source`, and prose restating them goes stale every release — which `docs/issues/025`, `030`
and `067` each were.

The four things the envelope genuinely cannot carry were moved before the deletion, and verified
mechanically afterwards:

| moved | to |
|---|---|
| why a naive timestamp is not localized for you | `register-dataset/references/point-in-time.md`, `timezone-proof.md` |
| a drifted declaration is regenerated, not repaired | all four `make-*/SKILL.md` |
| 500 / 502 is a vqapr defect — report it | every one of the nine SKILL.md footers |
| 423 / 503 — wait and retry unchanged | `run-backtest/references/check-before-run.md` |

**75 lines were kept, not deleted.** "Reading vqapr's output" describes the *shape* of the envelope
— the nine keys of a failure entry, reading `fix` first, branching on `status` before `code`, an
unrecognised `code` handled as its status. That is orientation and is not restating any single
refusal, so it became `introduce-vqapr/references/reading-the-envelope.md`. Its one sentence
pointing at the catalogue was rewritten to say why there is none.

## The exemption removed itself

`introduce-vqapr`'s body length was `xfail(strict=True)` from record `177`, with the reason that it
held the pre-split body. Cutting it made that test fail for **passing** — `XPASS(strict)` — and the
exemption came out with the marker. The contract now holds for all nine with no exceptions.

## Ten prose tests, decided one at a time

Deleting the body broke ten tests that pinned sentences in it. Each encodes a past defect
(`docs/issues/023`, `025`, `030`, `062`, `067`), so none was fixed by weakening an assertion.

**Four were claims I had genuinely dropped**, and the prose was restored:

- `run the same vqapr register <kind> <id> <file.py> again` — the **component** edit loop. My
  version had only the declaration flavour.
- `heartbeat window` and `never interrogated` — that a lock inside its heartbeat window means only
  that it was touched in the last 120 seconds, and **the pid in the message is copied out of the
  lock file, never interrogated**. A run killed by Ctrl-C, a CI timeout or an OOM kill leaves
  exactly that state, and inside the window nothing distinguishes it from a live run. That is
  domain knowledge the envelope cannot carry, and losing it would have been a real loss.

**Four were the same claim with different wording**, and my prose was reworded to the pinned form
rather than the pin loosened — `receipt rather than a gate`, `nothing re-checks it afterwards`,
`obtain approval for the destructive reset`, `give it its own id`. Three of those failed only on a
capital letter, which is brittle; loosening the pins would also have been a change to guards that
exist because sentences drifted before, and rewording costs nothing.

**One was a structural anchor.** `test_the_stop_condition_is_runnable` sliced its block between two
heading strings in the old body. It is re-anchored to the skill that now owns surveying a
workspace, with the reasoning recorded: slicing by heading text is exactly what broke, and the
guarantee was never about a section — it is that whatever tells a reader to survey names kinds the
CLI accepts.

**One was the deliberate gate.** `test_status_sections.py` required a `### Recovering from: NNN`
section per `Status` member. Record `175` left it standing on purpose, so the deletion would have
to be a decision rather than a diff that slipped through. Retired and **replaced by its mirror
image**: `tests/characterization/test_the_status_set_is_closed_and_uncatalogued.py` asserts no
shipped skill carries such a section, because the reasoning for deleting it lives in a PRD section
and a record and neither is consulted while someone is writing a helpful-looking paragraph.
`test_the_status_set_is_closed_against_free_strings` was never about the sections and is unchanged.

## Trade-offs

**The new guard is a prohibition, which is a weaker kind of test.** It cannot say the deleted
guidance was replaced by something better; it can only say the old shape has not returned. The
positive claim — that a refusal is readable without a catalogue — is carried by
`reading-the-envelope.md` and by `test_fix_is_not_a_restatement.py`, not here.

**`introduce-vqapr` now duplicates a little of every other skill** — the sample journey mentions
`check`'s four phases, the install section paraphrases the three verdicts. Orientation that names
nothing is not orientation, and each of these is a sentence pointing at a skill rather than a
second copy of it.

## Validation

- `uv run pytest tests/ -q` — 1,571 passed, 25 deselected, **no xfail**. The two `tests/extension/`
  failures are a parallel session's `43f59eb0` and predate this work.
- `uv run ruff check src/` — clean.
- `tests/agent/` + `tests/characterization/` — 194 passed, **no xfail**.
- Nine skills, SKILL.md bodies 124–173 lines each. The pre-split single skill was 1,019 lines and
  67KB, all of it loaded whenever it was relevant to anything.
