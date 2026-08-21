# 037 — Selling what you own is not shorting

## Why this exists

`ListingRule.permitted_sides` was a set of order *directions*, and it got the common case wrong.
Measured on the code as it stood:

```text
permitted_sides={BUY}, account holds 100 shares, sell 60
  -> REFUSED: sell is not permitted for 'A005930'
```

Selling sixty of the hundred shares you already own is not short selling. No venue forbids it
while still letting you buy. The name said "which directions may I order" and the honest question
is **"how far may this position move"**, and those differ exactly where it matters.

The evidence that this was wrong rather than merely awkward: **the constraint it looked like it
expressed was not expressed by it.** KRX declares `permitted_sides={BUY, SELL}` and blocked
shorting with a separate hand-written check inside its own `execute`:

```python
held = account.positions.get(request.instrument_id, Decimal("0"))
if held + request.delta_quantity < 0:
    raise ValueError(f"KRX profile does not support short selling ...")
```

So the venue-level fact "this venue does not support shorts" lived in a profile's private code
rather than in the listing declaration, and the field that appeared to own it owned something else.

A second complaint landed at the same time and has the same root: **a per-instrument rule is the
wrong default unit.** KRX trades every share and every ETF in whole units, so a two-hundred-name
K200 venue was writing two hundred identical `ListingRule` objects. `CostRule` had already been
keyed by kind for exactly this reason; listings had not.

## What changed

**`permitted_sides` becomes `access: ListingAccess`**, a three-state enum, so the impossible
combinations cannot be written down:

```text
NONE       listed and quoted, never filled -- a benchmark the venue publishes
LONG_ONLY  may buy, may sell down to zero, never below it
SIGNED     may hold a negative position; the venue claims to model the short
```

`permits_position(held, delta)` replaces `permits(side)` and answers the real question. Closing or
reducing is always permitted on a tradable listing; only the **resulting** position being negative
requires `SIGNED`. KRX's private check is deleted — the listing declares `LONG_ONLY` and the shared
rule enforces it.

```text
access=long_only   own 100, sell 60  -> True
                   own 100, sell 100 -> True
                   own 0,   sell 60  -> False    <- the short, and only this
```

**`QuantityRule` + `listings_by_kind()`** let a venue declare one rule per category and expand it:

```text
declared: 2 QuantityRule  ->  200 listings     (198 stocks, 2 ETFs)
stock sell tax: 12000.000
etf   sell tax: 0
```

Per-instrument `ListingRule` remains the resolved form, because some venues genuinely need it —
HKEX board lots differ by instrument — so a per-kind default cannot be the only expression. This is
a declaration convenience, not a second source of truth. A category with no rule is simply not
listed, which is how KRX declines factors without naming any.

## Why the exchange may see the account

It already did, and it must. `Exchange.execute(orders, account, snapshot)` has always taken an
`AccountSnapshot`, and shorting cannot be judged without it: whether `-60` opens a short depends
entirely on what is held. The venue sees a **snapshot** — positions and cash — not the `Account`
itself, so it cannot mutate the book or read the account's own policy. Two different facts remain
separate, and both must permit a short for one to happen:

| fact | owner | example |
|---|---|---|
| may this *account* hold a negative position | `AccountMode` | a cash account may not |
| does this *venue* support the short | `ListingAccess` | KRX profile models no borrow |

## Delisting was already correct

The frozen listing is not what expresses a delisting, and freezing it is not a problem. Record 020
settled this: a delisting is a **market fact at an instant**, so it lives in the execution table,
where the row simply stops appearing. Verified on a real case:

```text
planned A005930: delta=-42  price=70000
planned A003410: delta=0    price=None
filled  A003410: dealt=0    reason=absent
A003410 still listed on the venue: True
```

The listing never changed; the table stopped carrying the row, the fill is typed `ABSENT`, and the
position is carried at its last mark. Making listings mutable to model this would put a
time-varying fact in a frozen declaration and, per canon, end a 3,000-name run in its first week.

## Trade-offs

**`ListingAccess.LONG_ONLY` is the default.** A venue that says nothing gets the safe answer rather
than silently permitting shorts. `AcademicExchange` subclasses that want signed books must now say
`SIGNED`, which is the point — the claim is visible.

**Fifteen call sites changed**, including all eight showcases. The fifth positional argument
changed type from `frozenset[Side]` to `ListingAccess`, and a frozenset is truthy, so a silent
mis-read was possible; the constructor type-checks `access` and every stale call site failed
loudly. Nothing in this repository was published, so no compatibility shim exists or should.

## Validation

- `uv run pytest -q` — **627 passed**; `uv run ruff check src tests` clean.
- The original defect, now passing: a `LONG_ONLY` KRX listing fills a 60-share disposal out of a
  100-share holding and charges the 20bp tax (`dealt=-60, tax=8400.000`), while the same listing
  refuses `own 0, sell 60`.
- Preflight's holding check was rewritten after the old test turned out to assert the wrong thing:
  closing a short on a `LONG_ONLY` listing **is** permitted (buying back to zero), so only `NONE`
  is genuinely unclosable, and the check is reachable for a held instrument outside the traded
  universe.
- `listings_by_kind` expands 2 rules into 200 listings with the ETF exemption intact, and lists
  nothing for a category the venue declares no rule for.
