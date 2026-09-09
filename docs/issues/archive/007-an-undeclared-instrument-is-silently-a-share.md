# 007 — An undeclared instrument is silently a share

**Status: SUPERSEDED 2026-08-27 by `docs/issues/archive/008-an-instrument-is-not-the-venues-to-own.md`.**
The diagnosis below stands — an undeclared instrument silently gets share treatment — but the
prescription put the roster inside the venue, and the plan's entire cost followed from that. **Do
not answer the `WIDE`/`NARROW` question; it does not survive 008.** Read 008 first, then this file
for the diagnosis and for "What planning found", which remains accurate about the code at HEAD.

Found 2026-08-27 reviewing the agent-first surface after G009, by asking what a venue would do with
a price file holding stocks and ETFs mixed under one `instrument_field`. A consensus planning pass
ran 2026-08-27 and reached Architect `WATCH`/`COMMENT` with zero carryover plus Critic `OKAY`.
**See "What planning found" at the end of this file — it corrects four claims made above, two of
them load-bearing.**
**Touches:** `src/vqapr/exchange/venue.py`, `src/vqapr/exchange/venues/krx.py`,
`src/vqapr/exchange/listings.py`, `src/vqapr/cli/new.py`, `src/vqapr/agent/skill/SKILL.md`

> **The taxonomy is not missing.** `vqapr.domain.instruments` already splits an instrument's facts
> along the two axes this issue is about, `krx_rules()` already builds a roster from
> `instrument_id -> kind`, and `KrxExchange.__init__` already takes `instruments`. Nothing here
> proposes a new declaration kind, a new CLI verb, or a new workspace store. Every item below
> either closes a bypass around machinery that exists, or points the scaffold at it.

## The axes this issue does not move

Stated first, because everything below is easy to misread as attaching a rate to a ticker, and it
does not. `listings.py` already fixes the split:

```
what an instrument *is*        Instrument   -- category, venue-independent, carries no rate
what this venue does with it   TradeRule    -- unit, access, cost
```

**The join is by `instrument_id`.** A rate belongs to the pair `(instrument, venue)`, never to the
instrument. `Instrument` deliberately carries no `exchange_id`, because *"the same instrument may
list on several venues with different quantity units, and stamping a venue here would force it to
be declared once per venue, breaking the single fact that it is one instrument"*
(`domain/instruments.py`, canon 6.2).

So one instrument holds one category and as many rules as there are venues that list it:

```
Instrument("A005930", kind=STOCK)          one fact, no rate, no venue
        |
        +-- AcademicExchange.listings["A005930"]  buy=FREE,             sell=FREE
        +-- KrxExchange.listings["A005930"]       buy=SideCost(comm,0), sell=SideCost(comm,tax)
```

This is not aspirational. `showcases/show_005_enhanced_index` registers both profiles over the same
four tickers today, and the same name is free on one and taxed on the other.

The category's role is to let a venue declare its policy **per category instead of per ticker**:
`TradeTerms` is a venue-owned table (`KRX_TERMS`, `venues/krx.py:148-152`) that
`trade_rules_by_kind` expands into the venue's own per-instrument rules. The expanded form stays
per-instrument on purpose — *"because some venues genuinely do [have three thousand distinct
rules] (HKEX board lots differ by instrument)"* (`listings.py:20-22`).

Nothing in this issue shares a rule between venues, and nothing puts a rate on an `Instrument`.

## What happens

A venue may list an instrument without ever saying what that instrument is, and nothing refuses.

```python
# exchange/venue.py:48-50
listings: Mapping[str, TradeRule]
exchange_id: str = "academic"
instruments: Mapping[str, Instrument] = field(default_factory=dict)   # empty is legal
```

```python
# venues/krx.py:212-215 — the bare-sequence convenience
if isinstance(listings, Mapping):
    resolved = dict(listings)
else:
    resolved = {instrument: krx_listing(instrument) for instrument in listings}
```

`krx_listing` is `KRX_TERMS[InstrumentKind.STOCK].for_instrument(...)` (`krx.py:188-190`). So
handing `KrxExchange` a plain list of ids gives **every name stock terms**, and `instruments`
defaults to `None`, so no category is recorded for any of them.

**The category is consumed at construction, not at charge time.** `trade_rules_by_kind`
(`listings.py:290-308`) expands one `TradeTerms` per category into per-instrument `TradeRule`s, and
the rate rides on the rule as its `buy`/`sell` `SideCost` (`listings.py:88-89`). Charging is then a
dictionary lookup on `instrument_id` (`listings.py:381-387`), with no category involved at all —
the band matcher that used to select on `(kind, side, effective window)` was removed deliberately,
and `costs.py` records why. (That removal post-dates issue 003, whose closure note still describes
`CostRule` carrying `kinds`. 003 remains correctly closed — a venue *does* charge by category — but
it now does so by expansion rather than by matching, and its note reads as stale.)

That makes this defect worse than a mis-selection, not better: **a wrong rate is frozen into the
venue when it is built, and nothing downstream can notice.** No later step consults the category to
charge, so there is no point at which a stock rate on an ETF could be caught.

Downstream, an absent category is not an error. It is a fallback:

```python
# exchange/listings.py:350, 362, 374
def kind(self, instrument_id):          return None if declared is None else declared.kind
def notional(self, instrument_id, q, p):  ... if declared is None: return base_notional(q, p)
def quantity_for(self, instrument_id, v, p): ... if declared is None: return base_quantity_for(v, p)
```

Nothing raises. The numbers are simply wrong:

| Case | Undeclared behaviour | Consequence |
| --- | --- | --- |
| KRX ETF | built with stock terms | the securities transaction tax the venue exempts, applied anyway |
| any contract whose unit is not one unit of the quoted price | one unit = one unit | notional off by the multiplier |
| every fill | `Fill.kind` is `None` (`venue.py:145`, `krx.py:341`) | `FillBatch.cost_by_kind()` collapses to one unlabelled bucket, so the report that would have shown the error is the one the error erases |

`krx_rules` names itself the remedy — *"The one call that gets the ETF exemption right: a stock pays
the sale tax, an ETF does not, and neither is named individually"* (`krx.py:160-163`). **A shorter
path that silently gets it wrong runs alongside it.** That is the defect: not a missing capability,
a bypass around the correct one.

## Why it has been invisible

**Silence is indistinguishable from a claim.** An author who declared nothing and an author who
declared `stock` produce the same object. The workspace cannot tell them apart afterwards, and
neither can a reader of the run record.

**Every gate this repository runs would pass.** The zero-stall agent journey (`docs/implementations/
063`) completed against a **twelve-name, single-kind** universe on an academic venue, where the
fallback is correct by accident. A universe too small and too homogeneous to exhibit the defect
cannot measure it. This is the same shape as the Step 5 heartbeat: a test that passed while the
product path never reached the code under test.

**The scaffold teaches the wide door.** `vqapr new exchange` (`cli/new.py:430-462`) emits a
`class Venue(AcademicExchange)` subclass and unrolls `listings` as a dict literal, one line per
name (`new.py:447-450`), all with the identical rule. It never mentions `instruments`, never
mentions `krx_rules`, and does not scale: a two-thousand-name universe becomes a two-thousand-line
literal. The package's own academic showcase writes a comprehension instead
(`showcases/show_005_enhanced_index/run.py:454-466`).

That scaffold was an emergency repair for a journey that stalled at `exchange:` with no template at
all. It removed the stall, which was its scope. Teaching the maintainable form was not.

**The shortest path is the one taken, including inside this repository.** The same showcase's KRX
venue is `super().__init__(UNIVERSE, "show005-krx")` over a bare tuple of ids
(`run.py:481-486`) — the bypass, not `krx_rules`. Its four names are all stocks, so the stock
fallback is correct there and nothing is wrong today. That is precisely why this has stayed
invisible: the convenience is only wrong for a universe nobody in-tree has yet run through it.

## Shape of the fix

**1. Remove the bare-sequence `listings` form.** `krx.py:200,212-215`. A list of ids that silently
becomes stock terms is the whole bypass. `krx_rules(universe)` takes `instrument_id -> kind` and
returns both halves; make it the only way in.

**2. Require `instruments`, and require `listings` to be a subset of it.** Both profiles
(`venue.py:50`, `krx.py:202`). A venue must be able to say what everything it trades is. The check
is inside one venue, over that venue's own two mappings; no venue learns anything about another.

**Subset, not equality.** `trade_rules_by_kind` drops an instrument whose category the venue
declares no terms for (`listings.py:307`) — *"which is how a venue declines a whole category — KRX
lists no factors — without naming every instrument in it."* So `krx_rules` legitimately returns
more instruments than listings, and an equality check would refuse the very helper this issue
points authors at.

```
requirement: every listing must say what its instrument is
observed:    venue lists 069500, which the roster does not describe
fix:         build listings and instruments together with krx_rules({...: "etf", ...})
```

This is the invariant stated positively: *registering an instrument you never execute is fine;
executing one you never described is not, because the venue does not know how to treat it.* The
run-time guard stays as defence in depth, for the same reason the namespace guard did — a venue can
still be constructed programmatically.

**3. Rewrite the exchange scaffold as composition over one `{id: kind}` mapping.**

```python
UNIVERSE = {"A005930": "stock", "005935": "stock", "069500": "etf"}

listings, instruments = va.krx_rules(UNIVERSE)
VENUE = va.KrxExchange(listings, instruments=instruments)
```

Registered by `object_name: VENUE`. This passes all three `load_exchange` gates today
(`_internal/extensions/loading.py:329-363`) — an instance of a shipped profile is an instance of it,
and its `execute` *is* the profile's — so it needs no framework change. It also drops the subclass,
which is the widest door the extension point has: `execute()` is bolted (`loading.py:343`) but
`rules` and `execution_requirements()` are not, so a subclass can return a view that disagrees with
what it declared.

`UNIVERSE` becomes the single place an author states a category, and the file cannot be completed
without stating one.

It also stays one mapping when a project compares venues, which is the shape `show_005` needs:

```python
from vqapr.public import (AcademicExchange, KrxExchange, instruments,
                          krx_rules, trade_rules_by_kind)

UNIVERSE = {"A005930": "stock", "069500": "etf"}   # one fact per name
DECLARED = instruments(UNIVERSE)                   # id -> Instrument: no venue, no rate

krx_listings, _ = krx_rules(UNIVERSE)              # KRX expands its own KRX_TERMS
KRX = KrxExchange(krx_listings, instruments=DECLARED)

ACADEMIC = AcademicExchange(                       # the author expands their own terms
    listings=trade_rules_by_kind(DECLARED, ACADEMIC_TERMS),
    instruments=DECLARED,
)
```

`DECLARED` is shared because a category is one fact. The two `listings` are not shared, because a
rate belongs to `(instrument, venue)` — A005930 is free on one of these and taxed on the other.

**4. Give the skill a data-preparation section that makes the agent ask.** A price series is valid
without knowing what its instruments are; the question only bites when a venue is built, because
that is where a category becomes a rate. The agent should inspect the prepared data, say what it
observed **and what it would cost**, and let the user choose:

> Observed: 2,143 names; ticker bands split; a `sec_type` column with 보통주/우선주/ETF/스팩.
> Consequence: on a KRX-shaped venue, 121 ETFs would pay a tax the venue exempts. On an academic
> venue this does not matter.
> Choose: map the column, or declare every name a stock knowing the above.

Declaring every name a stock is a legitimate answer. The framework never infers the category and
never supplies a default; it only makes the choice impossible to skip. This is the same contract
`available_at` already states — *localize it while preparing the data; registration does not convert
it for you.*

## What not to do

**Do not have the framework read the user's raw file.** A `vqapr new dataset --from <file>` that
inspects a source and pre-fills a template was considered and rejected. vqapr does not know the
schema, format, or encoding of what a user was handed, so it would have to guess, and guessing
moves responsibility for data validity from the user to the package. The agent opens the file with
whatever tool it has, understands it, asks, produces a clean parquet, and writes the YAML that
declares it. `register` begins at the clean file. This boundary is not incidental — it is the
policy the package already enforces for timezone-aware `available_at`.

**Do not "fix" the execution-input template by generating data.** The agent journey report records
as thin that `execution-input` ships no runnable code while dataset/strategy/exchange do. That
reading is mistaken and acting on it would break the boundary above: the dataset template does not
produce data either, it produces a *declaration*. The two are already symmetric. Building the venue
table is the agent's work, by design.

**Do not attach `kind` to a dataset or to the execution table.** Both are per-`(instrument, time)`
series; a category is per-`instrument` and does not vary with time or venue
(`domain/instruments.py`, canon 2.8). Putting it there repeats one fact on every row, invites two
files to disagree about one instrument, and cannot express a category that carries its own fields.

**Do not open `InstrumentKind`.** It stays a closed, package-owned enum. Asset classes differ too
much in what they require for a user-supplied category to be safe, and the expansion is a
membership test — `if declared.kind in terms` (`listings.py:307`) — so a category the venue has no
terms for is **silently not listed** rather than refused. A user-invented kind would therefore
remove its instruments from the venue with no error at all. Adding a category remains additive and
remains the framework's job:
enum member, class, one line in `INSTRUMENT_TYPES`, and no declaration surface changes at all.

## Deferred, deliberately

**Closing the extension point to exact type.** Replacing `isinstance` with
`type(exchange) in SHIPPED_EXECUTION_PROFILES` would end subclassing outright and remove the
`rules`/`execution_requirements` override surface. It cannot land alone: `AcademicExchange.rules`
documents subclassing as the way to add a cost band, so the profile needs a `costs=` constructor
argument first. Item 3 above already moves the *default* path to composition, which is most of the
value; this is a separate decision and does not block this issue.

**The account axis.** Options and perpetuals were used as scale tests for this design and are out of
scope. Their identity registers under item 2 with no new mechanism — an option is a category with
more fields, its multiplier is the `notional`/`quantity_for` override pair the base class declares
for exactly that purpose, and an expiring chain needs no time machinery because the roster is the
union over the period while the execution table carries tradability. What is missing for both is
margin, expiry settlement, and cash flows that are not fills, which `domain/instruments.py` already
declares unimplemented and which belong to the account, not to this issue.

## To measure when this is picked up

**Migration inventory, counted 2026-08-27.** Item 2 changes a constructor every venue in the tree
calls: **61 construction sites across 36 files**, of which **3 already pass `instruments`**
(`tests/exchange/test_instrument_cost_bands.py:90,263`, `tests/exchange/test_price_limits.py:41` —
these are the sites that already exercise the correct path, and they are the model for the rest).

Roughly half of the files are **generated, not authored**: everything under
`showcases/show_*/outputs/**/components/*.py` is written by its showcase's `run.py`, so editing the
template string in five `run.py` files regenerates sixteen. What is hand-written is 5 showcase
runners, 13 test modules, and 2-3 files in the two testbeds. Counting them as 36 hand edits
overstates the work by about half; counting them as 5 understates it by the tests.

The FF5 testbed trades factors. Under this change its venue declares `factor` explicitly where it
declares nothing today, and today's fallback happens to be right for a factor. The count and value
gates should therefore be **unchanged**, and that is a prediction to verify rather than assume: a
gate that moves here means the fallback was load-bearing somewhere it was not expected to be.

---

# What planning found

A consensus planning pass ran 2026-08-27 (ralplan, deliberate mode, two review passes). It reached
**Architect `WATCH` / `COMMENT` with zero carryover blockers, and Critic `OKAY`**. Both lanes
verified each other's findings against code rather than concurring on assertion.

The plan artifacts live under
`.gjc/_session-01a03bd1-70a1-71ba-bd91-98aee8d3b3c6/plans/ralplan/01a03bd1-70a1-71ba-bd91-98aee8d3b3c6/`,
ending in `pending-approval.md`. **Nothing was executed.** This section is written so a fresh
session can pick the work up from this file alone.

## Four claims above did not survive verification

This issue was treated as the requirements source, which is exactly why it matters that four of its
own claims were wrong. Two are load-bearing.

**1. The subset rule is unreachable as written above (CRITICAL).** `ExchangeRulesView.__post_init__`
at `listings.py:332-336` already refuses an instrument declared *without* a listing -- the exact
inverse of this issue's own stated invariant. Adding the check proposed in item 2 on top of it
yields set **equality**, which is precisely what "subset, not equality" exists to prevent.
Reproduced before accepting:

```
listings, instruments = krx_rules({"A005930": "stock", "HML": "factor"})
KrxExchange(listings, instruments=instruments)
# ValueError: instrument 'HML' is declared on 'krx' without a listing
```

So the design in item 2 cannot be built without editing `listings.py`. The in-tree tell was already
there: `tests/exchange/test_instrument_cost_bands.py:287-288` exercises exactly this mixed roster
via `trade_rules_by_kind` and pointedly never builds a venue from it.

**2. Item 3's scaffold cannot load (CRITICAL).** `_load` constructs by *calling* the registered
object -- `candidate(**dict(ref.config))` at `loading.py:107-109`, unconditional, with no `isclass`
branch. A module-level `VENUE` **instance** is not callable, so it raises `TypeError` and surfaces
as `component.load.construction_failed` **before** `load_exchange`'s three gates ever run. The
claim that those three gates admit a bare instance is true -- they are simply never reached.
`conformance` loads through the same path, so `vqapr check` fails identically.

**3. The template inventory is wrong.** Not 5 templates producing 16 files: **8 template strings
across 5 `run.py` files, producing 15 files.** `show_007` emits an academic venue only, no KRX,
which is why the count is odd rather than a clean 8x2. `show_004` generates no exchange component
at all and is correctly out of scope.

**4. `venue_bridge` is refused by this issue's own predicate, and is absent from the inventory
above.** `venue_bridge.py:178,215` pass non-empty listings with no roster, so the proposed check
fires unconditionally on live product surface -- six-plus passing tests. And `venues.Listing`
carries only `instrument_id` and `access`, so there is no field to migrate with.

## Two scope decisions, taken by the owner

Both were needed because the four items as written could not be built. Both were put to the owner
explicitly and approved.

**Amendment 1 -- `src/vqapr/exchange/listings.py` comes in scope.** APPROVED, with a binding
condition: **the `listings.py` edit lands as its own commit**, so the contradiction removal is
attributable on its own. Delete the reverse check at `listings.py:332-336`; put the forward check
-- every listing must appear in `instruments` -- there in its place. This is not scope creep; that
check contradicts this issue's stated invariant, so removing it is removing a contradiction.

**Amendment 2 -- `kind` is added to the public `venues.Listing`.** APPROVED, option (a). The
alternatives were rejected with reasons worth keeping: exempting the bridge reopens the hole at the
one path guaranteed to be live, and defaulting the bridge to stock **is the defect itself**,
written down rather than inferred -- worse than the status quo, because it looks like a
declaration. Option (a) opens no new declaration kind, no CLI verb, no workspace store, and
`InstrumentKind` stays closed; but it is a real growth of public surface this issue did not
sanction, which is why it is recorded here rather than buried in a file table.

## Five open items the next session inherits

All non-blocking, all verified independently by both review lanes.

1. **The blast-radius analysis for Amendment 1 is wrong by 7x.** It asked "would the *deletion*
   change this site?", which is trivially "no" everywhere -- a deletion only removes a raise. The
   **insertion** is what refuses. Eight sites change status, not one:
   `test_trade_rule_contract.py:140,141` and `test_planning.py:262,274,308,435,509`. Note that
   `tests/orders/test_planning.py` appears in no inventory in this file.

2. **The rewritten scaffold stalls the journey it exists to unblock.** `krx_rules` defaults
   `price_limits=True` (`krx.py:167`), so `execution_requirements()` demands `BASE_PRICE = "base"`,
   while `testbed/ei.yaml` declares only `close`. Already pinned by a passing test at
   `test_preflight.py:589`. Fix: `krx_rules(UNIVERSE, price_limits=False)` in the template with a
   comment naming the switch -- that switch's documented purpose (`krx.py:163-166`).

3. **Amendment 2's blast radius is understated about 4x.** 20 `Listing(...)` construction sites
   across 6 files, not one. Semantic collision worth care:
   `test_agent_first_run_values.py:209-210` is named for pinning that **`access`** has no default;
   after a required `kind` it still raises, for the wrong reason, and can never fail again.

4. **`rules_view`'s optional roster becomes a door that only slams** (`listings.py:406-411`). Under
   the forward check its `None` default is reachable only when `listings` is also empty. One-line
   fix, and those sites are already being touched under item 1 above.

5. **A census of construction sites passes vacuously in a clean checkout.** The 15 generated
   components are not merely gitignored, they are **untracked** -- a fresh clone walks an empty
   tree, enumerates zero sites, and passes. It needs a non-vacuity floor, the way
   `tests/characterization/test_fix_is_not_a_restatement.py:108-111` already does.

## The execution order consensus settled on

Not this file's 1-2-3-4. Item 1 removes the bypass that makes item 2's check enforceable, and
item 2 is 61 sites whose predicate is both the thing that matters and the thing that gets skimmed.
So: item 1, then item 2's predicate **alone**, then a review gate, then the 61 sites, then the
generated files, then items 3 and 4. Reviewing the predicate before 61 sites encode it is the point
of the split.

The largest risk named in planning is worth repeating here, because it is the one a mechanical
migration walks straight into: assigning `stock` to every name to make 61 sites compile would pass
every test in the tree, and would write the defect down as an author's declaration rather than
leaving it inferred. That is strictly worse than today. The rule adopted was: **if a site can be
migrated without knowing what its instruments are, it is being migrated wrongly.**
