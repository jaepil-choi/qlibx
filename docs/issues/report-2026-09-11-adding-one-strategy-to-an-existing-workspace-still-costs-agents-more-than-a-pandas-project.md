# Adding one strategy to an existing workspace still cost agents 1.3 to 3.8 times a pandas project, mostly in reading the authoring API

**Status: RECEIVED 2026-09-11 (접수).** A measurement rather than a defect in one place, beside the held 2026-09-11 smaller-model report. The ask — one runnable example the scaffold points to, or a `vqapr new strategy` option that emits it — is a product direction and waits for the owner. **Owner ruling 2026-09-11:** the scaffold becomes that example — no `--recipe` option; see the recipe request's Status. Campaign `redesign/one-reading`.

| | |
|---|---|
| vqapr version | `0.14.4` |
| installed from | `vqapr-0.14.4-py3-none-any.whl` built in `vqapr/dist/` from develop `b8b47e6c`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-incr-testbed`, runs `A-1`–`A-3` and `B-1`–`B-3`, agent sessions |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

The earlier testbeds (the 2026-09-11 reports in this directory) started every agent in an empty
folder. There, learning vqapr and registering the data was about half of condition B's cost. This
testbed removed that part. Condition B started from a workspace with the datasets, roster, KRX
venue, a compliance rule and a completed momentum run already registered. Condition A started from
the same project written in pandas. Both got one prompt: add a gap-reversal enhanced index on KRX.
There was one run per model.

## What I expected

Less agent work under B than under A, since the data, the venue and the execution rules were
already declared.

## What happened

B cost more than A for every model. Cost is at list price from token usage deduplicated by message
id.

| model | A (pandas) | B (vqapr) | B ÷ A | accuracy |
|---|---|---|---|---|
| opus 5 | $1.53, 15 turns | $2.77, 20 turns | 1.8x | both exact |
| sonnet 5 | $1.32, 20 turns | $5.07, 99 turns | 3.8x | B exact on NAV; A used the wrong day's index weights |
| haiku 4.5 | $0.70, 52 turns | $0.92, 88 turns | 1.3x | both wrong |

B's extra went to reading the API:

- **B-1 (opus) read 82 KB of API text in 5 calls.** These were `--help` for four subcommands,
  `dir()` of `vqapr.authoring` and `vqapr.public` (26 KB), and pydoc of three groups. The first was
  `StrategyModel`, `TableSpec`, `StrategyCall` and `PanelWindow` (15 KB). The second was
  `KrxExchange`, `KrxSettings`, `ZeroDealtReason` and `Budget` (20 KB). The third was
  `vqapr.authoring.records` (9 KB).
- **At least 44 KB more came from skill files.** A-1's entire session returned 40 KB of tool output.
- **B-2 (sonnet) made 11 `help()` calls returning 46 KB.** They covered `StrategyCall`,
  `Rebalance`, `KrxExchange`, `StrategyModel`, `TableSpec`, `InvocationRecorder` and
  `PanelWindow`. It read another 66 KB of skills, and 15% of its cost went to skills and help.
- **Tool output stays in context, so every later turn pays for it again.** B-1's median context was
  196k tokens, against A-1's 85k.
- **Both B agents ran the `vqapr new strategy` scaffold.** They still looked up by hand the classes
  behind reading panels (`PanelWindow`, `StrategyCall`), writing a table of their own (`TableSpec`
  and the records module), and the KRX venue (`KrxExchange`).

Full tables: `kwam-enhanced-index/vqapr-incr-testbed/analysis/RESULT.md`.

## Impact

The owner's stated use of vqapr is adding strategies to an existing project. In this test the
framework did not lower agent cost for that use, and every new session pays the API-learning cost
again. With one run per cell, the ratios are indicative rather than measured spreads.

## What would have prevented it

- **One complete, runnable example the scaffold points to.** It would be a daily weight strategy
  that reads a second dataset beside prices and writes its own log table, so an agent copies and
  edits rather than reading the API.
- **Or a `vqapr new strategy` option that emits that example.**
