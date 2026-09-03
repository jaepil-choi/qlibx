# 064 -- "decide on the close, trade at that close" cannot be stated, and the template's example lags the decision by one session without saying so

**Status:** open. Found 2026-09-03 by the scenario testbed run 2
(`kaist-thesis/vqapr-scenario-testbed/`, FINDINGS **F-010**, `Unsure`; the evaluator reads it as
`Yes`), against `vqapr-0.3.0`. This is the entry the testbed exists to produce: a decision the user
had made that the package could not express. It composes with `027` (nothing makes a convention
be spoken aloud) and reopens the axis `033` was closed on -- a steering bug, not a semantics bug.

**Touches:** `src/vqapr/cli/new.py:172-181` (the agendas template: callback `15:29`, execution
`15:30`, and the comment that a strategy *"firing at 15:29 on session N decides on session N-1's
data -- which is correct, and is the point"*); `src/vqapr/agent/skill/SKILL.md` (no sentence on
the same-close convention); the execution input's `fill.at`.

## What happens

The paper, like every daily-frequency paper, rebalances at close t using information through
close t. The package's rule -- fill strictly later than the callback, callback sees only
strictly-earlier data -- is sound and is documented. What is not documented is how to say the
standard convention under that rule. The agent worked it out alone: close data stamped 15:30,
materialization 15:31, callback 15:32, fill 15:35 at the same session's close, valuation 15:40.
Five fictitious instants that nothing in the surface suggests or blesses, proved right only by an
independent residual recomputation.

The template's example is the *other* convention, and its comment presents it as the correct one.
For a 30-day mean-reversion signal the two are different strategies: the run's own lag diagnostic
puts one session of misalignment at 0.6 of Sharpe ratio. A user who takes the scaffold's timing
as given runs a strategy the paper did not describe, and no message says so.

## What to do

- One paragraph in the skill and in the agendas template: *to trade at the close on the close's
  own data, stamp the data at the close and put the callback and the fill a few minutes after it,
  in that order; to trade the next open or the next close on it, put the callback before the close
  as this example does.* Both conventions named, side by side, with what each means.
- Ideally a fill selector that says it in one word (`same_close`), so the convention is a
  declaration `034`'s run record can carry rather than five clock values a reader must decode.
- Rewrite the `:175-178` comment so it names its convention as a choice rather than as
  correctness.
