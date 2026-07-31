# The skill offers the repair choice the core refused to make

Specifies PRD 5.3. Completes the half of PRD 5.6 that `stage-based-errors.md` left to the agent
layer.

## Why this change exists

The previous pass made the core report a journey stage and stop. That decision is only half a
design: it is worth making because *someone else* owns the repair, and until that someone exists
the agent receiving `STRATEGY_CONTRACT: Strategy must declare at least one Strategy-specific
pandas input` has a stage name and nothing to do with it.

PRD 5.3 says who: the skill, and it sets the bar in the negative — a skill that presents one
repair path "이 요구사항을 충족하지 않는다", because a single path is the core's prescription
rebuilt one layer up. The generated skill stated the principle and worked one example. The
principle was not the deliverable.

## What changed

`stage_recovery.py` holds a structured table: eleven stages, 24 failures, 61 repair paths. Each
path carries what to do, `choose_when` — the fact that selects it over its siblings — and
whether to ask the user first. Each failure names the command to rerun afterwards.

```
### `Universe membership is missing for N registered date/ticker cells` -- the rectangle has holes.

1. Fill the missing cells as False during preprocessing.
   - Choose this when: The user confirms that absence means non-membership. qlibx refuses this
     reading on its own, which is why the failure exists.
   - Confirmation: ask the user before taking this path.
2. Narrow the registered date or ticker range to what the universe covers.
...
```

`choose_when` is the load-bearing field. A list of paths without criteria does not end the guess,
it moves it from the core to the agent.

The renderer emits `references/stage-recovery.md` into the generated skill package, taking each
stage's contract line from `errors.STAGES` rather than restating it, so the skill cannot describe
a stage the core has redefined. SKILL.md's error section now sends the agent there before it
repairs anything.

## The module boundary is the ownership rule

The content is in its own module, not in `documentation.py`. `documentation` backs `qlibx docs`
and `qlibx errors <stage>` — core surfaces that PRD 5.6 forbids from prescribing a repair. A
repair path reachable from there would be the core prescribing again, through an import instead
of through an `expected` string, where the existing wording test cannot see it.

`test_the_core_cannot_reach_a_repair_path` walks the import graph transitively from
`documentation` and `errors`. Reachability rather than the direct import is the property: one hop
of indirection would otherwise be enough to lose it.

## Two stages describe a product that does not exist yet

`PORTFOLIO` and `REPORTING` are declared in `errors.STAGES` and raised nowhere.
`portfolio.py` has 13 bare `ValueError`s and `reporting.py` 6, so an agent told to expect
`stage: "PORTFOLIO"` would wait for a field that never arrives.

Both stages get their contract summary, the failures that actually occur, and an explicit note
that these arrive unclassified and must be matched by message. Writing them as though they were
in the vocabulary would have been the more comfortable option and the false one.

## Invariants

- `test_every_stage_offers_a_choice_of_repairs` — parametrized over `errors.STAGES`, so a stage
  is named in the failure. At least one failure per stage, **two or more paths per failure**, a
  non-empty criterion per path, a rerun per failure.
- `test_the_recovery_table_covers_the_declared_stages_and_nothing_else` — set equality with
  `errors.STAGES`, so a dropped stage cannot keep a section and a new one cannot skip it.
- `test_every_rerun_command_is_one_the_cli_accepts` — parses `qlibx ...` out of each rerun line
  and checks it against the live `argparse` command tree. A renamed command breaks here instead
  of rotting inside a generated skill.
- `test_the_generated_skill_ships_the_stage_reference` — the plan contains the file, SKILL.md
  points at it, every stage appears, and the content is ASCII.
- `test_the_core_cannot_reach_a_repair_path` — described above.

## Trade-offs

- **Structured data, not markdown prose.** Prose can only be grepped for keywords, which is how a
  requirement like "two or more paths" rots. The cost is that adding a failure means editing a
  dataclass literal rather than typing a paragraph.
- **ASCII only.** The first draft used em-dashes and could not be printed on this machine's cp949
  console — the same class of failure `0e0bb41` fixed for the CLI, in content the CLI does not
  encode. `test_the_generated_skill_ships_the_stage_reference` asserts `isascii()` rather than
  relying on remembering.
- **`_public_commands` reads `argparse._SubParsersAction`.** Private, but there is no public way
  to enumerate a parser's command tree, and the alternative is a hand-maintained list of command
  names — which is exactly the thing the test exists to catch drifting.

## Validation

- `uv run pytest`: `161 passed` under PowerShell and under bash. Baseline at `0e0bb41` was 145;
  the 16 new tests are 11 parametrized stages plus 5 others.
- `uv run ruff check .` — clean.
- Mutation checks:

| Mutation | Fails |
|---|---|
| remove one `RepairPath` from a failure | `test_every_stage_offers_a_choice_of_repairs` |
| `documentation` imports `STAGE_RECOVERY` | `test_the_core_cannot_reach_a_repair_path`, run alone to confirm it is not the layering test catching it |
| a rerun line names a command the CLI lacks | caught during development: `alpha plan <name>` was flagged until the extractor learned to stop at placeholders |

## Still open

`portfolio.py` and `reporting.py` bare `ValueError`s, and the 22 in `optimization.py`. Promoting
them is what would let the two stages above drop their "unclassified" note. The question at each
site is the one `stage-based-errors.md` set: which stage is the caller in, and could they have
caused it?
