# The journey that could not finish

## What was measured

The spec's primary judgment criterion is not a test. It is whether a newly spawned agent, given
only the installed package, can get from raw parquet to a completed backtest.

The setup: a `testbed/` directory with a prices parquet, the skill installed, and rules forbidding
any look at the package's source, tests or docs. The only permitted inputs are `--help`, the
templates `vqapr new` emits, the refusals the CLI returns, and the skill. A **stall** is needing to
read package source, guessing an undocumented key, or running the same command more than twice
without the refusal telling you anything new. **Threshold: zero stalls.**

## The result: FAILED, 2 stalls, steps 5 and 6 never reached

The agent registered the dataset on the first attempt, scaffolded and registered a strategy, built
the execution input and agendas, and wrote a run spec. Then it hit `exchange:`.

**There was no `vqapr new exchange`.** Five of the six declarations a run needs had a scaffold. The
sixth did not — and the run-spec template names `exchange:` as required, so every journey reaches
it. `vqapr new exchange` was rejected as an invalid choice.

From there the agent reverse-engineered the component YAML by analogy, and the refusals carried it
a long way: `key_missing` named `path`, then `object_name`; `wrong_type` named the only two
permitted profiles, `AcademicExchange` and `KrxExchange` — a fact no template or help text states
anywhere, and the single most useful message in the session.

Then it stopped being useful. The constructor wanted `listings`, and the refusal said:

```
each listing key must match its TradeRule instrument_id
```

`TradeRule` appears in no template, no help text and no skill section. The agent guessed the
mapping's value shape six times — `{instrument: X}`, `{instrument_id: X}`, `{id: X}`, a nested
rule, a bare string — and got the **byte-identical error every time**. Six commands, zero new
information.

It then found that `listings: {}` registers successfully, which is worse than refusing: an Exchange
listing nothing passes registration and fails preflight later. The failure is milder than it first
looks and worth stating accurately: preflight collects every missing instrument into ONE
`preflight.universe.unlisted_instrument` refusal that names them all and gives both remedies, not
one refusal per name.

The agent stopped and reported honestly rather than continuing to guess. That is the right call,
and the report is the deliverable.

## The repair

`vqapr new exchange <id> --instruments A005930 A000660 --out venue.py` emits a runnable Exchange
plus the declaration that registers it. It is a Python file rather than YAML because a `TradeRule`
is a typed value with a `Decimal` quantity step — expressing it in YAML would invent a second
spelling for something the package already spells one way.

The same step now costs three commands with no guesses:

```
vqapr new exchange venue --instruments A000001 ... A000012   ->  venue.py + venue.yaml
vqapr register venue.yaml                                    ->  ok
vqapr list components                                        ->  ['venue']
```

The skill now also states that **a run needs five declarations** and that each has a scaffold, so
the reader checks for a template before hand-writing one. A parametrized test asserts every one of
the five has a `vqapr new` kind, so a future required declaration cannot ship without a scaffold
and be discovered by somebody's first journey.

## A second thing the journey found

The emitted strategy did not pass `ruff`. The scaffold split its imports across two lines from the
same module, which ruff's isort rule reorganises — so a user's very first file failed their linter
unedited. Fixed by importing the module once as `va`, which is shorter, sorts trivially, and makes
it unambiguous which contract the file is written against. 37 lines, ruff-clean.

## The re-measurement: PASSED, zero stalls, all six steps

After the repair and the skill reinstall, a **freshly spawned agent** — no history of this session
— ran the journey again under the same constraint. It completed all six steps with **zero stalls**.

It registered the dataset after round-trip-proving the timezone the template warned it about,
scaffolded and registered a strategy it did not edit, built the exchange, execution input and
agendas, and hit exactly one refusal: `check.lookback.uncovered`, whose `fix` named the literal
instant to start from. It moved the date and ran.

```
occurrences     240
account_version  80
tables           vqapr.account (1148 rows), vqapr.fill (599), vqapr.weight (509)
```

Verified independently rather than taken on report: `vqapr show run spec` from a cold process
returns the same numbers, and the strategy file on disk is byte-identical to what the scaffold
emits — 37 lines, unmodified.

The agent named the `new exchange` scaffold's docstring as one of the places the surface helped,
calling out the two facts it would otherwise have had to guess: that every traded instrument needs
a listing, and that only two profiles are permitted. That is the repaired gap, working.

Naivete is single-use, which is why this needed a fresh agent rather than a reset of the one that
failed. The first measurement is not invalidated by the second — it is what produced it.

## The repair was invisible where it mattered

A terminal critic caught something the repair itself hid. The fix landed in
`src/vqapr/agent/skill/SKILL.md`; the testbed reads `testbed/.agents/skills/vqapr/SKILL.md`, an
**installed copy** written before the fix. Its numbered list ran 7 to 8 with no exchange step, and
its manifest recorded `0.1.0a11` against a package at `0.1.0a16`.

So the gap was closed in source and still open in the only surface the criterion measures. A
re-run would have stalled in exactly the original place, and the report would have said the repair
did not work.

Worse, nothing could have told me. `vqapr skill list` reported `installed: true` and the package
version, and never compared the installed file against the one the package ships — so a skill that
describes a surface which no longer exists looked identical to a current one. That is worse than
no skill at all: an agent reads it and is confidently taught the wrong thing.

`skill list` now reports `current`, and names the command that fixes it when the answer is false.
Proved in both directions — a just-installed skill reports current, a drifted one does not.

## What is still thin

Two findings from the report are recorded rather than fixed, because both are behaviour changes
larger than the gap they close:

- `listings: {}` still registers. An Exchange that lists nothing cannot satisfy any non-empty
  universe, so registration could refuse it — but "an Exchange with no listings is always wrong" is
  a claim about intent, and the scaffold now makes the empty case something a user has to go out of
  their way to produce.
- The skill describes the unlisted-instrument failure without showing the fix, unlike every other
  declaration kind. The new template is that worked example; the prose has not been rewritten
  around it.

## Validation

```
uv run --no-sync pytest -q                                   # 1,282 passed
uv run --no-sync ruff check .                                # clean
python ../kwam-enhanced-index/vqapr-testbed-2/parity_probe.py --factors HML
```

Count gate MATCH 2096 / 97 / 110919; value gate exact, digests byte-identical to Step 0.

The FF5 reimplementation on the authoring path reproduces its committed baseline exactly:
`materialization.rows.jsonl` 710,620 rows, `publication.rows.jsonl` 646,804 rows,
`simulation.trace.jsonl` 10,480 rows, every stream matching its recorded sha256.
