# 176 — The first skill of the set: `register-dataset` interviews before it registers

**Closes:** PRD §11.2 (the first of the nine), §11.1 (`UC-AGENT-002` — read the data and propose a
registration), §4.2–4.5. **Branch:** `develop`, on top of record `175`. **Owner decisions,
2026-09-08:** the nine skills each get their own `references/`; `analyze-result` and
`register-dataset` also get scripts; `register-dataset` runs first because it is the heaviest and
proves the shape.

## Why

Record `175` built the machinery for a skill set and shipped a set of one — the old 1,019-line
body, moved wholesale. This is the first skill actually cut out of it, and it was chosen first
because it is the only one whose job the old skill barely did.

The old body spent 364 lines on "Rung 1" and most of them were about something else: authoring
components, choosing lookbacks, reading run records. What PRD §11.1 actually asks of this stage —
**read the user's own source, propose a registration from it, and separate what the data proves
from what only a column name suggests** — appeared as two short subsections near the end, with no
tooling behind them.

## What was built

`agent/skills/register-dataset/` — `SKILL.md` (167 lines), seven references, one script.

**`scripts/profile_source.py`** is the part that did not exist before. It reads the user's csv,
tsv, parquet or parquet directory through duckdb (already a vqapr dependency) and reports **only**
the falsifiable half of PRD §11.1's table:

- column combinations that are unique over every row, narrowest first
- inequalities that hold on every row of a numeric pair
- timezone-awareness, and the wall clocks a timestamp column actually lands on
- low-cardinality labels with their values, and null shares
- first and last observation per name, with late starters and early enders

Then it prints what it will **not** answer, and the questions are derived from what it found rather
than fixed. A table with no ordered numbers is not asked about an opening price.

**The float-key finding.** The first run against the shipped sample reported `open`, `high` and
`low` as unique keys. True — and an accident: continuous measurements rarely collide, so
uniqueness there is a property of the values, not of the table. An agent reading it would declare
`key_fields: [open]`, which registers and then loses a row the day two names open at the same
price. Floating-point columns are now excluded from key candidates; integers stay, because the
data cannot tell an identifier from a count. With them gone, `available_at, instrument` is the
first candidate, which is the answer.

**Why the script stops where it does.** It never proposes which column is the open. The
inequalities it reports hold whichever way the two inner columns are assigned — swap them and every
one is still true, on every row. The same asymmetry runs through the rest: a daily bar shifted nine
hours has a valid timezone-aware schema, and a boolean means whatever the vendor decided. So the
script fills one column of the table and the interview fills the other.

**The references** carry what the envelope cannot: `point-in-time.md` (the three questions and the
worked cases), `timezone-proof.md` (the `assume_timezone` versus `cast` footgun and the round-trip
assertion), `price-axis.md`, `universe-and-tradability.md` (PRD §4.5's derivation rules with their
risks, including the highest-risk one, offered rather than forbidden), `discouraged-preparation.md`,
`grain-and-cost.md` (both measured costs and the 614× pair), `correcting-a-registration.md`.

**What the SKILL.md deliberately does not carry.** The dataset declaration's key list: `vqapr new
dataset` emits a template generated from the contract the package enforces, and a second copy in
prose is a copy that goes stale. The refusal catalogue: status, stage and cause carry themselves
(PRD §11.2). The skill says to read the template and read the refusal.

## What did not change

`introduce-vqapr/SKILL.md` still holds all 1,019 lines, including the registration prose this skill
supersedes. Nothing is deleted until every skill has been cut, so there is no window where content
exists in neither place. The duplication is visible and temporary; the deletion pass reconciles it.

## Trade-offs

**The profiler's coverage report guesses a pairing.** It needs a name axis and an instant axis to
report per-name spans, and choosing them is a role guess — the one kind of guess this script
otherwise refuses. It is emitted under an explicit `IF <column> is the name axis` heading rather
than as a finding, which keeps the label honest, but it is the one place the output mixes the two
columns.

**Key candidates stop at three columns wide.** Beyond that the search is combinatorial, and a
logical key needing four columns is a question for the user rather than an answer to find.

**Spreadsheets are refused rather than read.** Converting one involves decisions about merged
cells, header rows and formatting that change what a column means; doing that silently inside a
profiler would hide them.

## Validation

- `uv run pytest tests/ -q` — 1,493 passed, 25 deselected. Two failures stand and are not this
  record's: a parallel session's `43f59eb0` changed the datamodel scaffold to return `float` and
  updated one test rather than three, so `test_scaffold_runs_on_real_dtypes` and
  `test_the_scaffold_offers_both_lookbacks` still expect `Decimal`. They fail in isolation and at
  that commit, before this branch of work existed.
- `uv run ruff check src/` — clean.
- `tests/agent/test_the_profiler_reports_only_what_the_data_proves.py` — new, 7 tests: no float
  column is ever offered as a key, the logical key is found, the bar ordering is reported while the
  roles are not claimed anywhere in the output, a naive timestamp is called out, an unbalanced
  panel names its late starter, the questions vary with the file, and a spreadsheet is refused with
  its reason.
- `vqapr skill install` into a scratch project writes all ten files of the two skills, nested
  directories included — the first exercise of the multi-file installer built in record `175`
  against a skill that actually has subdirectories.
- Profiler run against the shipped sample panel: finds `available_at, instrument`, the four bar
  inequalities, `wall_clocks ['15:30:00']`, the ten synthetic names, and both the late lister and
  the early ender the sample was built to have.

`tests/cli/test_the_skill_matches_the_code_it_ships_with.py::test_the_skill_does_not_promise_a_register_force_flag`
caught a sentence in `correcting-a-registration.md` that **denied** the flag but capitalised "There
is no", which its lowercase exclusion did not match. The sentence was rewritten rather than the
guard loosened: a case-insensitive exclusion would still have been correct, but a prose fix costs
nothing and leaves the guard exactly as strict as it was.
