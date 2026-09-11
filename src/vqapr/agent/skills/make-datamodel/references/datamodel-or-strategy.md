# Which of the two is this?

## The test

| | answers | output | execution | account |
|---|---|---|---|---|
| **DataModel** | *how much is this value?* | a **value** | **never** | none |
| **StrategyModel** | *how is capital divided?* | an **allocation** | **always** | yes |

**The test is whether it passes through execution.**

An allocation **can be filled**, and a fill produces a return — so it must pass through execution.
That holds even on the zero-friction academic profile: the cost is zero, but the fill, the account
update and the feedback all still happen. **There is no path that produces an allocation and skips
execution.**

A value **has nothing to fill**. "Executing a market capitalisation" is not a sentence. So a
DataModel's work ends before execution, and is a complete workflow on its own.

## Do not use account access as the test

> Splitting the two roles by "does it look at the account" gives the wrong answer. Some
> allocations do not use the account — that does not mean the role **cannot** see one.

The account difference is a **consequence** of the test above, not the test:

- **The allocating role may see the account**, because fills come back to it. Turnover-aware
  rebalancing, stop losses and adaptive weighting all need that.
- **The value-producing role has no account**, because a market cap that changed depending on
  whose account was asking would not be a market cap.

An allocation that depends on the account is path-dependent, and saying so — recording which state
it saw — is what lets another study reuse it as a frozen input.

## Worked cases

| the thing | which | why |
|---|---|---|
| a beta, a market cap, a factor exposure | DataModel | a value; nothing to fill |
| a factor's return — SMB, HML, momentum, any long-short spread | StrategyModel | the return of the portfolio that mimics the factor; each sorted leg is a strategy, and the factor is arithmetic on their NAV returns after the run |
| an ML prediction table | DataModel | a value, computed per session |
| a rank or a bucket assignment | DataModel *or* inside `decide()` | a value — put it in a DataModel when several strategies share it |
| "top 100 by liquidity" as a stored universe | DataModel | a value; the *choice to use it* is the strategy's |
| the weights themselves | StrategyModel | an allocation |
| an ensemble over stored alphas | StrategyModel | still an allocation — it reads results and allocates |
| turning a signed alpha into a long-only book | StrategyModel | an allocation, and it must execute in its own right |

## A DataModel is optional

A direct StrategyModel that reads prices and decides is complete. A DataModel is what a
StrategyModel reaches for when it needs a **reusable** intermediate table — one several strategies
share, or one expensive enough to compute once.

Do not insert one because the pipeline looks tidier with it.

## Machine learning sits on this line naturally

Training does not go inside the backtest loop. A DataModel computes the prediction table session by
session, and the StrategyModel reads it — the same separation the reference implementations arrived
at.

Two consequences worth stating to a user who expects otherwise:

- **What prevents look-ahead is that each session only ever sees what was available then.** There
  is no path for a model trained on the whole period to leak in, so there is no extra detector.
- **"The 20-day forward return at *t*" is not needed.** It is the same value as "the 20-day return
  recorded at *t+20*", and the second does not read the future.

Computing a wide span at once to go faster is self-defeating rather than forbidden: the output's
`available_at` moves later, so the result becomes valid too late to use.
