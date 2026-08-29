# 085 — What a fresh agent could not find

Four agents with no implementation knowledge were given the installed public surface and a
scenario each, in isolated directories under `testbed/run2/`. Three closed clean. The fourth
finding is this record.

## First, the harness was wrong

`testbed/.agents/skills/vqapr/SKILL.md` was 17,592 bytes and contained **none** of
`krx_rules`, `terms_by_kind`, `vqapr new constraint`, `list instruments`, `--table`, or the
phases-versus-judgments correction. The installed skill does not track the source; running the
measurement against it would have re-measured a document from before this work started.

Worth stating on its own: a real user installing the package gets whatever the distribution
carries, and nothing in this repository proves that is the current file.

## What the surface answered

**The mission question is answered from the documentation.** Scenario 2 asked whether ETFs cost
less to trade than stocks — the question the original journey burned its largest block on and
reported unanswerable, after 26 candidate keywords against `KrxExchange` and 16 against
`TradeRule`. The fresh agent's verdict:

> The skill's 'Costs' and 'Writing your own costed venue' sections directly named the mechanism, so
> no exploratory guessing was needed to even know the feature existed.

```
stock sells (46 fills): commission 3588.78 + tax 23925.18
ETF   sells (46 fills): commission 3254.80 + tax     0.00
```

Every friction point in that scenario resolved from the surface. So did the basic run scenario, and
`check.lookback.uncovered` fired there **legitimately** — a six-row lookback with too little
history before the first decision — and was fixed in two attempts from its own `fix` text.

## What it could not

**A DataModel could be scaffolded and registered and never described or run.**

- `show model` called `load_strategy_model` unconditionally and refused a DataModel with a message
  about the wrong kind.
- The skill mentioned `datamodel` exactly once, in the scaffold line. Record `076` had made
  DataModels runnable through `vqapr run` a day earlier and documented the spec shape **nowhere**.

So the agent computed its moving average in pandas and registered the result as an ordinary
dataset — doing by hand what the package does, because the door was not written down. That is
issue `011`'s exact pattern, reproduced by the work that closed it: *the capability is real and the
documented path routes around it.*

Both are fixed. `show model` describes either authored kind, and the skill carries the
materialization spec in full, with `check`/`run`, the `list datasets` readback, and why `--run-id`
and `--force` are refused.

**Verified by a different agent**, because the one that found it now knows. It read the skill,
concluded *"Derived data IS first-class"*, hand-wrote the spec from the literal example, and got
`ok:true` from both verbs. `blockers: []`.

## And what that retest found next

> There is no direct CLI verb to read a registered dataset's row contents.

To see what its materialization had computed, it built a **second complete run** — execution input,
exchange, strategy, agendas, spec — purely to observe the values through `show run --table`, and
then opened the parquet anyway.

That is `T9`'s defect one artifact over. `show run` reported per-table row counts and nothing could
read a row; `list datasets` reported that a dataset exists and nothing could read a row.

`vqapr show dataset <id> [--limit N]` closes it. It reports the registration's own facts — source,
path, declared fields, span — beside the rows, and `rows_total` separately from `returned` so a
truncated page never reads as a short dataset. `--limit 0` returns everything. Works for any
registered dataset, not only a materialized one.

`scan.head` is a scan primitive and says so: no point-in-time cutoff, no lookback, no dataset
semantics. It answers *what is in this file*, not *what would a model have seen* — conflating the
two would make an inspection command quietly disagree with the windows a run reads.

## Findings recorded and not acted on

- **`vqapr new` takes `datamodel`; `list` and `show` report `data_model`.** One spelling on the way
  in, another on the way out.
- **No `vqapr new` scaffold for a materialization spec.** The skill's literal example was enough —
  the retest agent hand-wrote the file from it on the first attempt — but every other declaration
  kind has a scaffold.
- **`check` passing gives no signal that a constraint will refuse the run.** Correct as designed:
  `check` cannot know what weights a strategy will propose. Worth documenting rather than changing.
- **`show run` reports table row counts but not ending NAV or cash**, so reporting them means
  filtering `vqapr.account` client-side.

## Validation

```
uv run pytest tests/ -q -m ""    # 1350 passed, clean
uv run pytest tests/ -q          # 1336 passed, 14 deselected
uv run ruff check src/vqapr/ tests/ showcases/   # 15, compared entry by entry: none introduced
```

Two new tests: `show model` describing a DataModel with its kind and what it reads, and
`show dataset` returning rows, both counts, the registration's facts, `--limit 0`, and a refusal
naming what is registered.

The refusal-code baseline moved by line numbers only.
