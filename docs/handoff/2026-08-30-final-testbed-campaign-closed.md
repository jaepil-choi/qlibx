# Campaign closure — the final testbed's findings, 015-027

Companion to `2026-08-30-final-testbed-findings.md`, which filed them. This is what happened to each,
what is still open, and what the two deferred product questions need from a human.

Branch `develop`. **Nothing was pushed** — `origin/develop` is still at
`630b63a6 Release 0.2.0a1`, and `develop` is ahead of it by the whole campaign.

## What closed

| issue | closed by | record |
|---|---|---|
| **015** `run` did not make the judgments `check` makes | `fix/015a-extract-judgments`, `fix/015b-run-refuses` | 087 |
| 016 a callback failure dropped half the envelope | `fix/016-callback-envelope` | 088 |
| 017 template offered an account mode that does not exist | `fix/017-template-account-mode`, `fix/017-closed-set-refusal` | 091, 092 |
| 018 `invested` is gross with an undocumented ceiling | `fix/018-invested-bound` | 090 |
| 019 a diagnostic table must be declared, and only the refusal said so | `fix/019-declare-diagnostics` | 089 |
| 020 the costed venue could not hold a short | `fix/020-krx-is-long-only` | — (docs) |
| 021 a validated Fama-French sort shipped unadvertised | `fix/021-skill-names-public` | — (docs) |
| 022 `vqapr.fill` had no clock | `fix/022-fill-envelope` | 093 |
| 023 docs half — a digest describing a file that can change | `fix/023-narrow-the-provenance-promise` | — (docs) |
| 024 a run that declared a table reported none | `fix/024-tables-declared-and-counter` | 094 |
| 025 the stale-skill message named a flag that does not exist | `fix/025-stale-skill-message` | 095 |
| 026 four of nine kinds did not emit the promised key | `fix/026-declaration-key-on-every-kind` | 096 |
| **028** a module below the CLI reached up through the facade | *(off-branch, see below)* | 097 |
| **029** two doors into `_internal` | partly — the `flow/judgments.py` row only | 097 |

Records 087-097, no gaps, no reuse; 015a and 015b share 087. Docs-only changes correctly have none.

## What is held, and what it needs from you

**023p — a digest read-back in `show run`.** The proposal is a statement reporting whether the source
at a registered path still hashes to the digest a run recorded: `matches` / `differs` / `absent`.

*Why it is held:* it is a product decision, not an edit, and it sits directly against
`docs/issues/009`, which removed the fingerprint gates deliberately and whose "What not to do"
forbids replacing a removed gate with a warning that is really a gate. 023 itself does not propose a
gate — it proposes a receipt being read back — but the distance between those two is a judgement
call about the product, not about the code.

*What it needs:* a decision that a read-back is wanted, and a design that cannot drift into a
refusal. The docs half already shipped and is tested **not** to imply the read-back exists
(`tests/cli/test_the_skill_states_provenance_without_promising_a_gate.py`), so nothing is
foreclosed and nothing currently lies to a reader. That test is where the change lands if it is
taken up.

**027 — `register` restating point-in-time field meanings.** One sentence per PIT field in
`register`'s success envelope, so a convention has to be spoken aloud rather than inferred.

*Why it is held:* the reporter marked it **"Attributable to vqapr? No"** — it is their own agent's
process failure, filed upward only because the paragraph was worth reading. It is a proposal about
an envelope's purpose, and building it without deciding that purpose would add noise to a surface
whose economy is the point.

*What it needs:* a yes/no on whether the success envelope should teach, and if yes, a decision on
which fields and how briefly. Nothing in this campaign forecloses it.

## What is still open beyond the holds

- ~~**029's other two call sites.**~~ **Closed 2026-08-30** by
  `docs/implementations/098-one-door-into-internal.md` (branch `fix/029-one-door-into-internal`).
  `cli/show.py:79-80,106` and `public.py:75` now reach `_internal` through the `extension/`
  adapters, `extension/loading.py` re-exports `as_loaded_fingerprint` so the last bypass had a door,
  and the eight docstrings cite `docs/design/agent-first-surface.md` rather than the expired goal id.
  `tests/boundaries/test_internal_has_one_door.py` enforces it, including function-local imports -
  which is what the bypasses were. The adapters themselves still stand: their deletion is `G008` and
  both gates remain shut.
- **Five frozen modules whose no-new-callers rule is still prose.**
  `docs/design/agent-first-surface.md:322-341` names them under "What the tripwire does not watch".
  Re-measured during the boundary review: all five still hold. The invariant is true; only its
  automation is missing — which is the exact shape of the defect 028 turned out to be.
- **`check`/`run` parity for `output:`'s sub-key shape.** `_NESTED_REQUIRED` covers `strategy` and
  `valuation` but not `output`, so a materialization spec whose `output` is missing `value_fields`
  returns `ok:true` from `check` and `INCOMPLETE` from `run`. Found by the generation-2 architect
  lane, pre-dates this campaign, and is one entry in `_NESTED_REQUIRED`.
- Four low-severity notes from the boundary review: `project_root` passed positionally in
  `flow/judgments.py` while siblings read `workspace.project_root`; a `get_close_matches` near-pair
  in `cli/new.py` and `flow/judgments.py`; `registrable` present in the `new` envelope only when
  false; the pre-existing orphaned docstring at `cli/register.py:1047-1053`.

## Verification

| measurement | step zero (`develop@8d040b9e`) | final (`develop@ad38957d`) |
|---|---|---|
| full suite `-m ""` | 1350 passed, 0 failed | **1421 passed, 0 failed** |
| slow marks ran / skipped | 14 / 0 | **14 / 0** |
| `real_data` gate | provisioned | provisioned (8 passed) |

Run with `-rs`; no skip lines were emitted. The two measurements are of the same population, so the
+71 is real. Slow marks were located by the predicate that defines them (`pytest.mark.slow`, four
files) rather than by directory name — the campaign's first planning error was assuming
`tests/acceptance/` held them, and it holds none.

## The process deviation, stated plainly

The user's constraint was one issue, one branch cut fresh from `develop`, committed, merged back
`--no-ff` before the next. **That held for every branch-bearing story — fourteen branches, fourteen
`--no-ff` merges, no squash, no batching.** (The plan's sixteen steps include step zero, a decision
point and this closure, none of which carries a branch.) It was **not** followed for two commits:

- `c0a1c75d` — the 028 fix, its boundary test, record 097, and the regenerated baseline.
- `ad38957d` — the completion-gate fix: the materialization refusal tests and lint parity.

Both changed production source directly on `develop`, unbranched and unmerged. `c0a1c75d`'s parent
is `e816b18c`, the 023 merge commit, so a branch was available at zero cost and cutting one is what
the constraint required. Record 097's first version claimed these were swept in by `git add -A` and
could not be split out; git contradicts that, and the record has been corrected rather than left
standing. Both deviations were found by review, not self-reported.

## What this campaign says about itself

Two of the regressions this campaign introduced were caught by audit rather than by the suite:
`docs/issues/028` (a module below the CLI importing the facade — the tripwire lived in prose) and the
untested materialization refusal (deleting it left ~1,419 tests green). Both are now tests, and both
were proven to fail on the defect before being kept. The pattern is the campaign's own lesson:
**an invariant that lives in a document is an invariant nobody is checking.**
