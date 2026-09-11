# The KRX settlement order is not written anywhere an agent reads, so an agent reported that vqapr does not apply two rules it does apply

**Status: RECEIVED 2026-09-11 (접수) — confirmed against `develop` `ee2e2711`.** Sells settle before buys (`exchange/venues/krx.py::_settlement_order`), buys are funded largest money delta first (`exchange/planning.py::_buy_order`), and the fill batch is sorted back into instrument order before it is recorded (`krx.py`, "Back into identity order"); no shipped skill states either rule. The skill half is fixed directly; a trim marker in the record changes the record's shape and waits for the owner.

| | |
|---|---|
| vqapr version | `0.14.4` |
| installed from | `vqapr-0.14.4-py3-none-any.whl` built in `vqapr/dist/` from develop `b8b47e6c`, copied into each run directory |
| reported | 2026-09-11 |
| reporter | `kwam-enhanced-index/vqapr-incr-testbed`, run `B-1` (opus 5), agent session |
| python / OS | 3.12.13 / Windows 11 |

## What I was doing

An A/B experiment on adding one strategy to an existing workspace. The task specified KRX
execution rules, including "매도를 먼저, 매수를 나중에" (sells first) and, when cash runs short,
"매수 금액이 큰 종목부터" (the largest buys first, the rest get what is left). The testbed's answer
key copied those rules from `KrxExchange` and `exchange/planning.py`.

## What I expected

An agent building on vqapr to be able to confirm, from the skills or from the record, that the
venue applies these rules.

## What happened

B-1 reproduced the answer key exactly: NAV, and all 8,834 entries and exits. Yet its deliverable
says the opposite about the rules. Its `enhanced_summary.md` item 16 says vqapr does not document the
order and that the record's `sequence` is in ticker order. It says that on the momentum record,
vqapr's trimming of buys "looked different" from largest-first. Its final report says vqapr
"doesn't enforce" either rule.

Both rules are in the code:

- **Sells first.** `KrxExchange._settlement_order` settles sells, then buys.
- **Largest buy first.** `planning._buy_order` funds buys largest money delta first. The later buys
  get what the remaining cash affords.

I checked the momentum record B-1 looked at. On all 10 days where a buy's `requested_quantity` fell
below `trunc(w × base / price − held)`, the trimmed buys were exactly the smallest money deltas of
that day. On 2018-06-29, for example, 3 of 11 buys were trimmed, and they ranked 9th, 10th and 11th
by money delta.

Why the agent could not see it:

- **No skill states either rule.** The only related word in the shipped skills is `unfunded`, in the
  analyze-result column reference (`panels-from-tables.md`). The docstring that states "sells
  first" is on the private `_settlement_order`, which `pydoc` hides.
- **The record hides the settlement order.** `vqapr.fill` is re-sorted into instrument order after
  settlement (`krx.py`: "Back into identity order"), so its `sequence` cannot show that sells
  settled first.
- **The record hides the trim.** `requested_quantity` is recorded after the planner's cash trim,
  and nothing marks a request as trimmed. An agent comparing it with its own formula sees smaller
  numbers and no reason.

## Impact

No number was wrong, because cash never ran short in this task. But the deliverable told the user
that the framework ignores two rules it applies. A user checking vqapr against a written execution
spec cannot confirm them from the record either.

## What would have prevented it

- **One statement of the KRX execution rules in a skill reference.** It would cover the sizing base,
  the floor toward zero, sells before buys, largest money delta funded first, and what the later
  buys get.
- **A marker in the record when the planner trims a buy for cash.** For example, the untrimmed
  target beside `requested_quantity`, or a reason on the trimmed row.
