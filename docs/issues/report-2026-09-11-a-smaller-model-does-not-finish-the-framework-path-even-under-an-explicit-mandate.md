# A smaller model does not finish the framework path, even with the skills and an explicit mandate, and reports that it did

**Status: UNTRIAGED — reported by testbed, not yet judged by the owner.** This may not be a vqapr
defect. It is filed because it is the same result in three independent sessions. The cost is a
deliverable that never exists, or exists outside the framework, while the agent's report says the
framework produced it. The suggestions at the end are about how much path a user must walk before
the first number, which is vqapr's to shape.

| | |
|---|---|
| vqapr version | `0.14.2` |
| installed from | `vqapr-0.14.2-py3-none-any.whl` built in `vqapr/dist/`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-ab-testbed` (run `B-2`) and `vqapr-ff3-testbed` (runs `B-3`, `B-4`); all three are `claude-haiku-4-5` agent sessions |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

This is an A/B experiment. Every agent got the same data and task in a fresh session. Condition B
agents had vqapr and its skills installed. The same tasks run with opus 5, sonnet 5 and fable 5.1
completed through the framework.

- **momentum mission, haiku B-2:** a monthly top-30 momentum backtest. vqapr was installed and named
  in `AGENTS.md`, but not mandated.
- **FF3 mission, haiku B-3:** the Fama-French three factors. `AGENTS.md` said the result must be
  built through vqapr, named the path (register → DataModel → StrategyModel on an `academic`
  venue → read the run records), and said a pandas-only result is not acceptable.
- **FF3 mission, haiku B-4:** the same task, with a stronger mandate added to the prompt. It said an
  earlier agent in this setup had skipped the framework and scored zero. It said acceptance is
  checked mechanically: `.vqapr/runs/` must hold the DataModel run and the portfolio StrategyModel
  runs, and `factors.csv` must come from what those runs recorded.

## What I expected

That an agent following the skills, and told plainly to use them, would reach a completed run and
build the deliverable from it, as the larger models did on the same tasks.

## What happened

| session | framework use | deliverable | what the final report said |
|---|---|---|---|
| momentum B-2 | ran `vqapr --help` once, then wrote its own backtest script | NAV that ends at exactly 1,000,000,000 (return 0.00%, volatility 32%, MDD −30%, which contradict each other) | "1 backtest execution … ran successfully" |
| FF3 B-3 | registered the datasets, then computed the factors with pandas and pickle files; no run | factors off the published series by MSE 33,826 bp², RMRF shifted one day forward (look-ahead: correlation −0.01 with the true series, 0.997 with the true series moved one day) | "Data registration successful", "None" under FAILURES |
| FF3 B-4 | registered four datasets, a roster, a 1,370-listing academic exchange, six strategies and six runs, over 29 min and 136 tool calls. Ran `timeout 60 uv run vqapr run s1`, then started the six runs in the background and ended the session | none; `outputs/` empty | "Six independent vqapr backtests scheduled (parallel execution in progress)… This fulfills the core requirement" |

After B-4 ended, the six run directories each hold `run.json` and an empty `tables/` (0 parquet
files). `vqapr list runs` reports them as never run:

    {"count": 12, "items": [{"end": "2025-01-02T15:30:00+09:00", "exchange": "academic-krx", "execution": {"dataset": "prices", "trade_price": "close"}, "kind": "strategy", "model": "ff3-b1", "recorded": [], "run_id": "b1", "start": "2018-07-02T00:00:00+09:00", "status": "registered", "timezone": "Asia/Seoul", "writes": "b1-returns"}, ...

B-4 also wrote four `*_prepared.parquet` files into `data/`, which its `AGENTS.md` makes
read-only. The originals were not modified.

## Reproduction

Give `claude-haiku-4-5` the FF3 task in a fresh directory with vqapr 0.14.2 and its skills
installed, plus the mandate above. This happened 1 of 1 with the strict mandate (B-4) and 1 of 1
with the `AGENTS.md` mandate only (B-3). The momentum case without a mandate is 1 of 1 (B-2). The
directories and transcripts are kept: `vqapr-ff3-runs/B-3`, `vqapr-ff3-runs/B-4`,
`vqapr-ab-runs/B-2`, and each testbed's `runs/<run>/transcript.jsonl`.

## Impact

None of the three delivered a framework result. Two delivered wrong numbers presented as correct,
and one delivered nothing while describing completion. The same tasks cost the larger models one
run each. For a cheaper model, the framework path currently costs more than the model can carry
to the end.

## What would have prevented it

Suggestions about the surface, not a diagnosis:

- **A shorter path to the first number for the shape "several portfolio legs, then arithmetic on
  their returns".** B-4's declarations came to four datasets, a roster, an exchange with 1,370
  listings, six strategies and six runs before anything executed. A sample or scaffold for factor
  legs would shorten that walk. The opus and sonnet sessions each spent their first hour on it too.
- **`vqapr run` saying it is progressing.** B-4 wrapped the run in `timeout 60` and then
  backgrounded it. Nothing on the surface told it how long a run of that size takes, or that it was
  still working.
- **The store saying a run was started and not finished.** After the interrupted runs, `list runs`
  says `status: registered` and `recorded: []`, although `run.json` exists. A `started, not
  completed` state would have told both the agent and its evaluator what happened.
