# `observe` — one member, one question

## The question

*Did what I actually hold exceed this limit?* Asked of the **committed, marked** account, at every
instant of the market clock, right after valuation. Not at decision time and not of the plan: a
book can be inside a limit at decision time and outside it after the fills, and rounding a weight
into whole shares can push a position over a limit the decision itself respected.

## What it receives

One `call`, and it is the whole of what the rule may reach: its own declared reads as of the
instant observed, the run's instruments, and `call.account` — an `EconomicAccountView`: `cash`,
`positions` (quantities), `values` (marked), `nav`, and the derivations every weight rule needs,
`weight(name)` and `weights()`, computed once in one place so two rules cannot disagree about what
a weight is. Nothing is handed beside the call; what is not on it, a rule cannot see.

## What it returns

A `ComplianceFinding`: `passed` (your strict comparison), `measured`, `bound`, `excess`,
`offenders` (the breaching names), `details` (portable scalars only). The rule's id is **not** on
the finding — the framework stamps it, so a finding cannot be filed under the wrong rule.

## What it must not do

Change the account. Decide. Gate. A rule observes; the run goes on. And it is not handed the box
the strategy built inside — measure against your own parameters, read your own data.

## Memory

A rule is a Component: `self.memory` is restored before `observe` and committed with the findings.
*"Third breach in a row"* is a rule that counts, and counting is memory. Strict JSON only.

## What lands in the record

`vqapr.monitoring`, one row per rule per market-clock instant: `rule`, `passed` (your own
comparison), `measured`, `bound`, `excess`, `verdict` (the framework's), `tolerance`, `offenders`,
`account_version`. `event_time` is the instant the book was marked and judged at.

The strategy record's `contract` block only carries counts. **Which name breached which limit by
how much is in the table**, so a compliance question goes there.

## An empty monitoring table

Means no rule was evaluated — not that none was breached. Say which when reporting. A rule that
failed to get its data, or that the run never named, is silent in exactly the same way as one that
held perfectly.
