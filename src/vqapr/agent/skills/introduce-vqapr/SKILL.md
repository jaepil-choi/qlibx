---
name: introduce-vqapr
description: Explains what vqapr is and what it does for a researcher — it registers data with the instant each value became knowable, holds the portfolios a model decides in a real account so their returns are what the book earned, and freezes every result with the data and code behind it — then routes to the skill that does the work and walks a sample run. Use when the user asks what vqapr is, what it can do, where to start, or whether a task needs vqapr or plain pandas; when a task ends in a portfolio return someone will quote — a backtest, a long-short spread, Fama-French or other factor-mimicking portfolios (SMB, HML, momentum), an enhanced index, a cost comparison; or when the user wants to install or initialize vqapr in a project.
---

# vqapr — what it is, what it does for you, where to start

## What vqapr is

A research framework for quantitative portfolios. You register your data once, saying when each
value became knowable. You write the idea — which names to hold, and how much. vqapr buys that
portfolio into an account, carries it day by day, and hands back the return it actually earned,
frozen together with the data and the code that produced it.

It runs backtests, and it is more than a backtester: the same machinery computes a reusable table
(a beta, a prediction), builds a factor portfolio, prices an idea with and without trading costs,
and checks a book against a limit — and every one of those answers can be traced and reused.

## What it takes off your hands

A script that computes a portfolio return makes a dozen decisions, one line each, and nothing
records them. vqapr makes each one once, where it can be seen.

| the question a script answers silently | what vqapr does instead |
|---|---|
| Was this number known yet? | Each dataset declares when its values became available — "financials are known three months after the fiscal year ends" is written once, at registration. Every read after that sees only what was available at that instant; there is no filter to forget. |
| What did the portfolio actually earn? | The weights a model decides are bought as shares and valued every session. Between two decisions they drift with prices, and a name that halts between the decision and the fill is recorded unfilled, with the reason — not dropped by a line you wrote. On the `academic` venue the fills cost nothing, but they are still real fills. |
| Could this weight have been used then? | A weight earns nothing before it is filled, and it is decided only from what was available, as declared, at the decision instant. A same-day close used as a weight for that same day — a look-ahead that passes every sanity check in a script — cannot happen. |
| What would trading have cost? | Run the same idea on `academic` (frictionless) and on `krx` (commission, tax, lot sizes, price limits). The gap is the cost of realism. |
| Are the standard sorts right? | Fama-French 2×3 breakpoints from a reference subset, bucket assignment, value / equal / signal weighting, neutralisation and bounded optimisation ship in `vqapr.public`, matched against a validated Korean replication. |
| Where did this number come from? | Every run freezes its declaration, the digests of the data it read and the fingerprint of the code. `vqapr show run` answers months later. |
| Can the next study reuse it? | A computed table registers as a dataset the next model reads; a strategy's result is an input to an ensemble. No export step in between. |
| What went wrong? | Every command prints one line of JSON. A refusal says who must act, where it stopped and how to fix it — before anything ran, and every problem at once. |

## What you can ask it for

| the user says | how vqapr does it | skill |
|---|---|---|
| "Register the files in data/ and tell me what's missing" | reads each column with you, asks what only you can know, writes a declaration that passes `vqapr register` | **register-dataset** |
| "Backtest 12-month momentum, top 30, equal weight, monthly" | a StrategyModel that returns target weights on a monthly agenda | **make-strategy**, then **run-backtest** |
| "Build daily Fama-French SMB and HML" | each of the six sorted portfolios is a value-weighted StrategyModel on `academic`, one run each; a factor's daily return is the spread of their NAV returns. Built this way on Korean data, SMB and HML tracked a published replication at 0.99 and 0.97 daily correlation | **make-strategy** |
| "Precompute a rolling beta or an ML prediction every strategy can use" | a DataModel: a per-instrument table computed session by session and registered as a dataset | **make-datamodel** |
| "How much do costs and taxes eat?" | the same strategy on two venues | **make-exchange** |
| "Cap any single name at 5%", "stay inside the mandate" | bounds the strategy builds inside, and a Compliance rule that watches the held book | **make-compliance** |
| "Ensemble these alphas into a long-only enhanced index" | a StrategyModel whose inputs are other strategies' results | **make-strategy** |
| "Sharpe, drawdown, turnover, attribution, a paper figure" | `strategy_report` and `run_report` read the frozen record | **analyze-result** |
| "What did this result use? Can I reuse it? Clean up" | `list`, `show` and `rm` over the workspace | **inspect-workspace** |
| "This looks like a vqapr bug" | a dated report back to the maintainers | **report-issue-dev** |

Each of those skills is self-contained; this one does not repeat their details.

## When plain pandas is enough, and when it is not

**Pandas is enough** when the answer is a statistic over a panel that is already point-in-time and
no portfolio is held — a correlation, a descriptive table, a one-off chart. vqapr would add
registration steps and return nothing a DataFrame does not.

**Reach for vqapr when the answer is a return someone will quote.** Once a portfolio is held
between two decisions, its return depends on drift, halts, delistings and when each input was
known, and a script settles each of those in a line nobody reviews. A factor, a spread and a
backtest are all this kind of answer: a factor's return *is* the return of the portfolio that
mimics it.

The cost is real and worth saying: a first run takes more steps than a script — register, check,
run. It is paid once per dataset, not once per idea, and the steps are where the decisions a script
hides become visible.

## What it does not do

- **No month-end cadence.** A decision schedule picks trading days forward — `every: 1M` is the
  first trading day of each month, `every: 12M` once a year from the run's first month. "The last
  trading day of June" is decided on the first trading day of July instead, and the new book
  fills at that day's close.
- **A delisted holding is never sold.** It stays in the book at its last price until the run
  ends, and money held in a name that cannot be sold — halted or delisted — cannot pay for the
  next book, so the smallest new buys go unfilled. A leg held a year at a time carries a few
  percent of such dead capital; the record shows exactly how much.
- **A result is per instrument or per strategy.** A single number per day with no instrument —
  a factor series — is arithmetic on strategies' NAV returns after the run, not a DataModel output.
- **Not a broker.** No order routing, pacing, kill switches or confirmed fills from a venue;
  [references/mental-model.md](references/mental-model.md) draws that line.

## See one run happen first

```bash
vqapr new sample --out ./first-run
vqapr register ./first-run/sample.yaml
vqapr check sample-run
vqapr run sample-run
vqapr show run sample-run
```

That writes a complete journey the product runs as it stands: a five-day reversal strategy, a
venue, a small synthetic panel, and `sample.yaml` — the one declaration that registers all of it.
The panel is **deliberately unbalanced** — one name lists late, one stops trading early — so what
you see is the shape a real run has. It is synthetic: **draw no conclusion about a market from it**;
do copy its `sample.yaml` when writing your own declaration.
[references/sample-journey.md](references/sample-journey.md) walks what each step produced.

## The four things you write

| you write | it decides |
|---|---|
| **DataModel** | what a value is — a table per instrument, never executed |
| **StrategyModel** | how capital is divided — always executed, so its return is real |
| **Exchange** | where and by what rules an order fills |
| **Compliance** | whether what is held respects a limit |

Everything else — the account, valuation, the order of events, the record — is vqapr's, so two
projects' results mean the same thing. [references/mental-model.md](references/mental-model.md)
has what vqapr owns versus what the project owns, which is the question behind most "can vqapr do
X".

## Running the commands

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. **The CLI help is the authoritative usage reference**:
`vqapr <command> --help` for one command's arguments.

Every command returns exactly one line of JSON, success and failure in one shape. **When `ok` is
false, read `fix` first**; the refusal also carries `status` (who must act), `stage` (where it
stopped) and `cause` (what happened).
[references/reading-the-envelope.md](references/reading-the-envelope.md) explains the fields and the
order to branch on them.

## Installing the skills into a project

```bash
vqapr skill install                # both targets
vqapr skill install --dry-run      # what it would write, and each file's state
vqapr skill list                   # what is installed and whether it matches this package
```

Both targets receive identical bytes, and a copy holding someone's edits is never overwritten
without `--force`. [references/install-and-environment.md](references/install-and-environment.md).

## What this skill will not do

- bypass package validation
- guess missing semantics
- confirm a binding before the evidence exists

Where a choice changes the economic meaning of a result, the user makes it.

When something is harder than it should be, write it down **before** resolving it — once you know
the answer you can no longer see what was missing. **report-issue-dev** owns where that goes.

---

A refusal carries its own status, stage and cause. Status **423 or 503 means wait and retry the
same command unchanged**; **502 is your own component's code raising** (`cause.origin: "user"`,
`cause.where` names your line) — fix it; **500 is a vqapr defect**: do not work around it silently
— file it with **report-issue-dev**, envelope and all, and then carry on.
