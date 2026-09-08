# When the fill happens, and which price it uses

## The declaration vqapr will not make for you

Which observation is used as the execution price is an **explicit declaration**. vqapr does not
choose one, and when the declared one is missing or invalid it **fails rather than falling back**
to another.

A column's name is not that declaration. That a column looks like an opening price is not a
statement that orders should fill at it.

## The look-ahead the package cannot see

**vqapr knows the fill time. It does not know when the fill price was observed** — that fact is not
in the data.

So this passes every check the package can make:

> fill at the session close, using the session's close price

and it is a look-ahead. The close is knowable only *at* the close, so a decision taken at that
instant using that value could not have been acted on. The same shape appears as: fill at the open
using the open price, when the decision was taken at the open.

**This is settled and will not be reopened**: trading at the close on close data is forward-looking.
Do not implement a venue that does it and do not offer it as an option.

## What to do instead

The safe shapes all put a gap between "knowable" and "traded":

- decide on session *t*'s close, fill at session *t+1*'s open
- decide on *t*'s close, fill at *t+1*'s close
- decide intraday on a value knowable before the fill instant

Say which one the venue implements, and say it in the result's limitations too.

## The warning is a limitation, not a validation

When you see a decision time and price source that cannot both be true, tell the user plainly:
the price could not have been traded at that time, and here is the alternative.

**The output of that warning is a limitation on the result, not a new check in the package.**
Widening the package's judgment here would create a guarantee that is only half true, and a half
guarantee invites more trust than none.

## Order conversion, and why the fill can differ from the intent

Four quantities, and they are not the same number:

| | what it is |
|---|---|
| **intended** | the target the strategy asked for, as weights |
| **requested** | converted to an order at execution time, in the venue's quantity units |
| **dealt** | what actually filled — zero is a real outcome, with a reason |
| **committed** | what the account holds afterwards |

Conversion happens **at execution time**, not at decision time, and it is the venue's quantity
rules that shape it: lot size, rounding, fractional permission, price limits.

A name that halted between the decision and the fill is not a defect. It is why decision and
execution are separate, and the gap is recorded as unfilled quantity with a reason rather than
smoothed over.

Never report a requested quantity as a holding, and never report an intended weight as a realised
one. `intent.gap` in a `StrategyReport` is the measured distance between the first and the last.
