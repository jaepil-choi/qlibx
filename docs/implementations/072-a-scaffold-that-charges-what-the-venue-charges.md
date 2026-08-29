# 072 — A scaffold that charges what the venue charges

The most expensive finding in the evidence base, and it was not a missing capability.

## What happened

A first-time-user journey was asked *"do ETFs cost less to trade than stocks?"* and could not
answer it. It spent the largest single block of its mission probing for the rate — 26 candidate
keywords against `KrxExchange(...)`, 16 against `TradeRule(...)`, rate columns added to the roster
parquets and accepted silently — and reported the question unanswerable. After a complete, passing,
reproducible run, all 64 fills carried `commission: 0.00` and `tax: 0.00` on buys and sells alike.

Nothing refused, because nothing was wrong. A zero-cost venue is a legal, complete, reproducible
run. What was wrong was the scaffold:

```python
return TradeRule(
    instrument_id=instrument_id,
    quantity_step=Decimal(1),
    minimum_quantity=Decimal(1),
    fractional_allowed=False,
)
```

Four arguments. No `buy`, no `sell`, no `SideCost` in the import line, no comment that either field
exists — and `TradeRule` defaults both to `FREE`. The agent copied that shape onto a `KrxExchange`
subclass, which is precisely what the scaffold teaches, and produced a Korean venue that charged
nothing.

**The capability was there all along.** `krx_rules` is exported from `public.py` and appears zero
times in the shipped skill. `exchange/costs.py`, the `SideCost`/`FillCost` arithmetic, `krx_rules`,
`krx_etf_terms` and `FillBatch.cost_by_kind` consumed no data at all in a mission written to
measure cost by security kind. Not dead code — live code the documented path routed around.

## Where the cost actually comes from, measured

`ExchangeRulesView.listing(id)` returns the `TradeRule` the venue was **constructed** with, and
`listings.py:207` picks `buy` or `sell` off it. The bound roster supplies `stamped_kind` for
recording and `_declared` for sizing; it does **not** supply cost. So three constructions give
three different answers:

| how the venue was built | stock sale tax | ETF sale tax |
|---|---|---|
| the old scaffold's 4-arg `TradeRule` | `0` | `0` |
| `KrxExchange([ids])` — a bare list, the obvious guess | `0.002` | `0.002` ← wrong |
| `krx_rules({id: kind})` | `0.002` | `0` |

The bare list is the sharper trap of the two, because it looks right: every name gets stock terms,
so an ETF pays a sale tax it is exempt from, silently, on every sale, for the life of the project.
`krx_rules` is the one call that gets it right, and it needs the category.

## The change

`vqapr new exchange <id> --profile {academic,krx}`, defaulting to `academic` so the existing
scaffold is unchanged but for its docstring.

**The academic scaffold now names what it leaves out.** Its `_rule()` docstring states that this
venue charges nothing, that `buy`/`sell` are the channel and are the two fields omitted below,
shows the `SideCost` lines to uncomment, and points at `--profile krx` for real terms rather than
inviting anyone to hand-write rates.

**The KRX scaffold builds from `krx_rules`** over a `UNIVERSE` mapping of id to category, with
every id scaffolded as `stock` — the same default `new instruments` uses, because the CLI knows the
ids and not what they are. Its docstring says what a wrong category costs, which is the part a
default cannot decide, and says the categories must agree with the registered roster.

## The band ships off, deliberately

`krx_rules(..., price_limits=True)` models KRX's daily limit band and **requires** the execution
input to carry the session base price; `execution_requirements()` declares it and preflight refuses
by name without it.

The execution-input template `vqapr new execution-input` emits carries a trade price only. So a
scaffold defaulting to `True` would refuse on first use for anyone following the documented path —
`new execution-input` then `new exchange --profile krx` then `run` — which is the same defect this
record exists to close, one door further along. Found by running the emitted pair, not by reading
it.

It ships `False`, and the comment states what turning it on requires and that the choice is
recorded in every rule's declaration identity, so a run states which of the two it measured.

## Validation

```
uv run pytest tests/ -q         # 1310 passed, 14 deselected
uv run pytest tests/cli/test_krx_cost_journey.py -q -m ""   # the new slow journey
```

`tests/cli/test_krx_cost_journey.py::test_the_krx_scaffold_charges_a_stock_and_exempts_an_etf` is
a `slow` end-to-end journey and asserts on **fill values, never on registration returning `ok`** —
pre-mortem scenario 1 for this task was that the template could emit `krx_rules` and still charge
zero if the roster never reached the venue's view. The venue under test is the scaffold's own
output, edited only where its docstring says to edit: the ETF's category. A scaffold is judged by
what happens when a user copies it.

Prices force a rotation, because a journey that only ever buys cannot answer the question — the
sale tax is charged on the sell side and the exemption is an exemption from exactly that. Observed:

```
kind        qty   commission        tax
stock      9997    299.91000        0.0
stock     -9997    299.91000     1999.4000
etf        8309    299.12400        0.0
etf       -8309    299.12400        0.0
```

Commission on both sides of every trade, the sale tax on the stock sale, and zero on the ETF sale.
That is the mission question, answered from the scaffold.

The academic profile was checked to be unchanged in substance: still `class Venue(AcademicExchange)`
with the same four-argument `TradeRule`, differing only by the added docstring. `--profile` appears
in `vqapr new --help`, checked through the parser.
