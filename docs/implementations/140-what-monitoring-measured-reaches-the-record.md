# 140 — what monitoring measured reaches the record

**Closes:** the recording gap named in `docs/design/constraints-a-third-reader-and-a-wider-contract.md`
§4 (step 1 of its §8). **Authority:** PRD §2 (monitoring finding is a first-class result), PRD §7.1
(a breach leaves behind which rule, the bound, the value measured); architecture §5.7, §17.3.
**Touches:** `flow/simulation.py`, `flow/run_state.py`, `flow/reporting.py`, `cli/show.py`,
`agent/skill/SKILL.md`; the two tests that pin the default table set; one new test.

## Why this exists

A monitoring occurrence projected the declared constraints, measured the committed account against
them, built a `ConstraintReport`, and put it on the occurrence trace. From there exactly one thing
read it: `contract_report`, which folded every finding into `held` and `checked` per constraint id
for the strategy record's `contract` block. The values themselves -- `measured`, `bound`, `excess`,
`offenders` -- lived on the in-memory `SimulationResult` and were gone when the process was.

So a run whose book breached a limit could say *that* it did, in a count, and never *which name*
crossed *what bound* by *how much*. Those three are exactly what PRD §7.1 says a breach must leave
behind, and the framework was producing them and dropping them at the door. `docs/issues/051` fixed
the count being always empty; this fixes the count being all there was.

The owner's ruling that opened the constraint redesign -- *constraints are user-pluggable modules
whose findings the strategy should also be able to see* -- makes the gap sharper: the same numbers
are about to be handed to the strategy at decision time, and it would be odd for the strategy to
see what the record does not.

## What changed

### A fourth package table

`vqapr.monitoring`, beside `vqapr.account`, `vqapr.fill` and `vqapr.weight`. One row per declared
constraint per monitoring occurrence:

| column | what |
|---|---|
| `constraint` | the rule's registered id |
| `passed` | bool |
| `measured` · `bound` · `excess` | the finding's three Decimals, typed on the way back through the sidecar |
| `offenders` | the breaching instrument ids joined by one space (no id may contain one); empty when none |
| `account_version` | the committed account version that was judged |

The envelope's `event_time` is the monitoring cutoff and `stage` is `MONITORING`. The producer is
the strategy the run judged, as it is for a valuation's rows.

**Keyed by rule, not by instrument.** Every other default table is keyed by `instrument`, and two
tests asserted that of all of them. A finding is one constraint's verdict over the whole account;
its offenders are a field, not its key. Keying it by instrument would have meant either a synthetic
identity or the same worst-case measurement repeated under each offender's name. The tests now say
*keyed by its subject*.

### A publish path for an occurrence that changes nothing

`RunStateRepository.prepare_monitoring` / `publish_monitoring`, and `LifecycleKind.MONITORED`.
A monitoring occurrence has no fill, no mark and no decision, and it leaves the pending slot exactly
as it finds it -- `prepare_standalone_valuation`'s reasoning applies unchanged. What it adds is rows,
staged the way every package table's are: into the root without a sink, out to the sink at publish
with one. So a run with a store streams findings to disk as it goes (record `135`), and a run killed
midway keeps every finding it made.

A run that declared no constraint publishes nothing here. There is no finding to record, and a
`MONITORED` entry on every monitoring day of an unconstrained run would be noise.

### Everything that lists the tables says four

`FRAMEWORK_TABLES`, the `show --table` help, the skill's table guide (with the note that this is the
table compliance questions are asked of), architecture §17's tree, and the layout design.

## What did not change

- `contract_report` still counts from the occurrence traces and still reports `held`/`checked`.
  It is the summary; the table is the detail. They come from the same findings.
- The `Constraint` contract. This record writes what the contract already produces. The redesign
  in the design document (measure ∈ range, `check`, readings on the strategy call) is a later,
  breaking step and waits on the 0.3.0 testbed reports.
- No verdict is added anywhere. Monitoring still judges only the committed account, on its own
  cadence.

## Validation

- `tests/flow/test_monitoring_findings_reach_the_record.py` (new): a streamed run writes one typed
  row per constraint per occurrence and keeps none on its roots; without a sink the rows sit on the
  roots; a run with no constraint writes no such table and no `MONITORED` entry.
- `tests/flow/test_account_table_is_measurement_only.py`, `tests/flow/test_publish_run_record.py`:
  the default set is four, keyed by subject.
- `uv run pytest tests/flow tests/constraints tests/cli tests/characterization tests/acceptance/test_time_002.py -q`:
  532 passed before the two pinning tests were updated, 35 passed after (the affected files).
- `uv run ruff check src/`: clean.
- `uv run pytest tests/ -q -m ""`: the record shape changed, so the full suite is the gate.
  **1330 passed** in 17m29s on 2026-09-03, slow journeys included.
