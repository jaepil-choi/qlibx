# 008 — An instrument is not the venue's to own

**Status: CLOSED 2026-08-28** by
`docs/implementations/065-an-instrument-is-the-projects-to-declare.md`, with the roster-injection
defect it exposed closed by
`docs/implementations/067-a-fill-records-what-it-was-charged-as.md`.
The roster left the venue: venues lost the `instruments` parameter entirely, so a venue author has
no channel to declare a category, and the Flow binds the project's roster in at run assembly. Record
`065`'s claim that *"a partial injection — one route bound, the other not — cannot happen"* was
false, which is what `067` had to fix; that correction is part of this issue's closure, not a
separate defect.

**Planning was halted 2026-08-27 by the owner and corrected by
`docs/issues/009-a-fingerprint-is-a-receipt-not-a-gate.md`.** Read 009 first if you are reading this
file for its history. The planning pass that was running on it was deliberating FREEZE vs IMPORT for
the registry; that comparison is void — both options rest on a premise 009 refutes — and this file's
section on it has been rewritten. 009 also adds the `--force` and `remove` commands this issue
depended on.

Written 2026-08-27 after owner review of 007's plan.
**Supersedes:** `docs/issues/007-an-undeclared-instrument-is-silently-a-share.md`. 007's diagnosis
holds — an undeclared instrument silently gets share treatment — but its prescription put the roster
in the wrong place, and its plan's whole complexity followed from that. **Read this file instead of
answering 007's WIDE/NARROW question; that question does not survive.**
**Touches:** `src/vqapr/exchange/venue.py`, `src/vqapr/exchange/venues/krx.py`,
`src/vqapr/exchange/listings.py`, `src/vqapr/flow/preflight.py`, `src/vqapr/cli/`,
`src/vqapr/agent/skill/SKILL.md`

## The mistake 007 made

`ExchangeRulesView` holds `instruments` (`listings.py:312-338`), so today a venue *owns* the
statement that A005930 is a common share. 007 accepted that and tried to make the ownership
mandatory. Everything expensive in its plan followed:

- a reverse check to delete or satisfy, and a `WIDE`/`NARROW` argument about which
- `venues.Listing` growing a `kind` field so the bridge could keep up
- 61 construction sites migrated to pass a parameter
- fingerprint contamination, because `declaration_identity` folds the roster in
  (`listings.py:389-403`), so adding one never-traded instrument to a universe invalidates a venue
  whose behaviour did not change

**None of that is about instruments. All of it is about a venue holding a fact that is not its.**
`domain/instruments.py` says so in its opening paragraph: `kind` answers *no* to both the time axis
and the venue axis, which is why it lives in `domain` and not in `exchange`. A venue reading that
fact is right. A venue *declaring* it is the defect.

## The move

**The project registers its instruments once. Every venue reads them.**

```
instruments.py            author writes it: a mapping, or a comprehension, or a generated chain
      |
      |  vqapr register instruments instruments.py
      |  the workspace records WHERE it is. It stores no copy of what is in it.
      v
run start                 read the current file, once
      v
in-memory mapping         what a fill consults; O(1), no I/O per fill
      v
run record                which roster this run used, stated as a fact and compared to nothing
```

A new listing appearing tomorrow changes nothing about a run that does not trade it, and refuses
nothing about a run that does. See "How the registry is read" below and 009.

A venue then declares only what is genuinely its own:

```python
listings   {"A005930", "069500", ...}          the ids this venue trades
TERMS      {stock: ..., etf: ...}              this venue's policy, one entry per category
OVERRIDE   {"00001": ...}                      optional, per-ticker, for venues that need it
```

Charging resolves as `OVERRIDE.get(id)` first, else `TERMS[roster.kind(id)]`. `KRX_TERMS` already
exists in exactly this shape (`venues/krx.py:148-152`); today it is expanded into per-instrument
rules at construction and the category is thrown away. It stops being expanded.

Per-ticker rules stay possible because some venues genuinely need them — *"HKEX board lots differ
by instrument"* (`listings.py:20-22`) — but they become the exception a venue declares, not the
form every venue is forced into.

### Why this is smaller than 007, not larger

`AcademicExchange.instruments` (`venue.py:50`) and `KrxExchange`'s `instruments` parameter
(`krx.py:202`) are **deleted**, not made required. 007 counted 61 construction sites because it
needed all of them to start passing something. Deletion touches only sites that pass it today:

| | 007 | 008 |
| --- | --- | --- |
| exchange construction sites to edit | 61 | **3** (`test_instrument_cost_bands.py:90,263`, `test_price_limits.py:41`) |
| `krx_rules` call sites | untouched | 6 real calls, plus 3 inside emitted-source strings |
| `venues.Listing` public surface | grows a required `kind` | untouched |
| `listings.py` reverse check | deleted or satisfied | **moot** — no roster in the view to check |

`krx_rules` has **zero callers inside `src/`**. It is public API exercised only by tests, which is
worth knowing before deciding how much of its shape to preserve.

### The bypass 007 existed to close fixes itself

```python
KrxExchange(["A005930", "069500"])
```

Today this is the defect: a bare id list silently receives stock terms (`krx.py:212-215`), so the
ETF pays a tax the venue exempts. Under this design the same call is **exactly correct** — a list of
ids is precisely "what I trade", and the category comes from the registry. There is no shorter
wrong path to close, because the short path becomes the right one.

## How the registry is read — corrected by 009

**This section originally argued that the registry should be FROZEN at registration rather than
imported at run time. That recommendation is withdrawn.** So is the IMPORT-with-a-fingerprint-gate
alternative that a planning pass moved to after verifying two of FREEZE's three premises were false.
Both options assumed that a roster changing between runs is a dangerous event. It is not: a daily
batch lists new tickers, issuers delist, names get reclassified. **A roster grows as a matter of
course**, and a gate on ordinary growth refuses runs that never touch the new name.

See `docs/issues/009-a-fingerprint-is-a-receipt-not-a-gate.md`, "Stop the 008 comparison". The
settled shape:

```
read the current roster at run start        no copy, no gate
record which roster the run used            run record, as a stated fact
record what each fill was charged as        Fill.kind, already implemented
```

**Do not re-open FREEZE vs IMPORT.**

What survives from the original section, because it is about the author's file and not about how it
is read:

- **The author's file is Python.** A category is a typed value and a real universe is generated
  rather than typed — an option chain is a comprehension over expiries and strikes. YAML would
  invent a second spelling and could not generate.
- **Whatever `instruments.py` names must be callable.** `_load` calls the registered object
  unconditionally — `candidate(**dict(ref.config))` at `loading.py:107-109`, with no `isclass`
  branch. 007 proposed registering a module-level *instance*, which could never have loaded. A
  zero-argument function returning the mapping is the obvious shape.
- **Registration can still report what it found** — `{"stock": 2022, "etf": 121}` — which is the
  receipt line that makes an undeclared universe visible on the success path rather than in a later
  failure. That needs no frozen copy; it is computed when the file is read.

## Re-registering a roster must be ordinary

"069500 is an ETF" is a correction about the world, not a new experiment. Re-registering it must not
be ceremony — unlike a dataset registration, which is immutable because changing it would rewrite
provenance.

That is safe **because provenance already lives somewhere better**: every fill records the category
it was charged under (`Fill.kind`, stamped at `venue.py:145` and `krx.py:341`, aggregated by
`FillBatch.cost_by_kind()` at `fills.py:124`). What a past run treated as a share is testified to by
that run's own fills. The roster therefore belongs in **no** fingerprint, and 007's contamination
problem cannot arise.

**Prerequisite:** there is no command today that re-registers anything. `register` has no `--force`
and the package has no removal verb at all. 009, Decision 5 adds both, and this issue depends on it.

## Three refusals, and they are different refusals

`preflight.py:293-313` already separates two of them and explains why conflating them is wrong —
*"Reporting both as 'unlisted' would invite someone to register a listing that already exists."*
This design adds a third in front:

| Situation | When | Meaning |
| --- | --- | --- |
| the id is in no registry | strategy output / preflight | nobody said what this is; **the order cannot be formed** |
| registered, but this venue does not trade it | preflight, and again at fill | the venue's judgement; unfilled, and say which venue |
| traded here, but no price at that instant | fill | the data does not cover it; unfilled |

The first is the gate the owner asked for: a strategy returns weights over instrument ids, and an id
nobody has described must not become an order. The other two are unfilled outcomes with distinct
causes, which is the point — an unfilled order whose reason is unknown teaches nothing.

## What survives from 007

- **The skill's data-preparation section.** An agent must inspect the prepared data, suspect that a
  price file holds more than one category, state the consequence (*on a KRX-shaped venue, ETFs would
  pay a tax the venue exempts*), and let the user choose. Declaring every name a stock remains a
  legitimate answer. The framework never infers a category; it only makes the choice impossible to
  skip.
- **The scaffold rewrite**, now against this shape rather than 007's. It is rewritten either way, so
  it should be written once, here.
- **The price-limit default must not stall the journey.** 007's plan found that `price_limits=True`
  makes `execution_requirements()` demand a base price column the journey's `ei.yaml` does not
  declare. Verified here:
  `test_preflight.py:589 test_a_venue_regime_without_its_execution_price_is_refused_before_the_run`
  pins exactly that refusal — *"the run would produce numbers that look limit-aware and are not."*
  Whatever the helper becomes, the emitted template must switch the regime off, with a comment
  naming the switch.
- **The two-axis doctrine**, which this issue does not move so much as finally honour.

## What not to do

**Do not have the framework read the user's raw file.** vqapr does not know the schema, format or
encoding of what a user was handed. The agent opens it with whatever tool it has, understands it,
asks the user, produces a clean parquet, and writes the declaration. `register` begins at the clean
file. This is the same contract `available_at` already states — *localize it while preparing the
data; registration does not convert it for you.*

**Do not read 007's note that `execution-input` ships no runnable code as a gap.** The dataset
template does not produce data either; it produces a declaration. Building the venue table is the
agent's work by design, and "fixing" it would break the boundary above.

**Do not open `InstrumentKind`.** It stays closed and package-owned. Adding a category is additive —
enum member, class, one line in `INSTRUMENT_TYPES` — and changes no declaration surface. A
user-invented kind would be a category the venue has no terms for, which under this design is an
order the venue declines rather than an error anyone sees.

**Do not default an unknown id to `stock`.** 007's plan says this better than this file can:
defaulting *"is the defect itself, written down rather than inferred — worse than the status quo,
because it looks like a declaration."* An id with no registry entry is an id nobody described, and
that must remain distinguishable from an id someone described as a share.

## Open items

1. **Where the frozen file lives.** Recommended: its own `.vqapr/instruments.json`, with
   `workspace.yaml` holding a pointer and digest. `register_dataset` rewrites the workspace document
   wholesale, so a three-thousand-entry roster inside it is rewritten on every unrelated
   registration and makes the diff unreadable. Not settled.
2. **One roster per project, or several.** Recommended: one, while instrument ids do not collide.
   Several requires asking *which roster knows this id*, and that is a matcher — the thing this
   package removed from the charge path on purpose.
3. **What `krx_rules` becomes.** With terms resolved from the registry it no longer needs to return a
   roster, and possibly no longer needs to exist. Its six real call sites are all tests.
4. **Where the strategy-output gate sits.** `Rebalance.of` is pure authoring code with no workspace
   access, so the check belongs at intent acceptance in the Flow, not in the authoring type. Worth
   settling before it is built in two places.
5. **Whether `ExchangeRulesView` keeps a roster reference at all.** It needs `kind(id)` to charge and
   `notional(id, ...)` to size, so it needs *access*, not *ownership*. Passing the registry in at
   run assembly is the obvious shape; making it a constructor field would quietly recreate what this
   issue removes.

## To measure when this is picked up

**The ETF path has no coverage outside unit tests.** `InstrumentKind.ETF` appears only in
`tests/exchange/` and `tests/boundaries/`. No showcase and neither testbed exercises a mixed-category
universe, so the exemption that issue 003 was closed to deliver, and that this issue exists to
protect, is never executed where the count and value gates run. A migration that leaves this true has
not been measured.

`show_005_enhanced_index` is the natural home — issue 003 records that this defect was found *"reproducing
an enhanced-index fund that holds an index ETF alongside its direct stock book"* — but its universe
is four common shares (`A000660`, `A005380`, `A005930`, `A105560`) drawn from real benchmark data.
Whether an ETF can be added depends on that data, so this is a question for whoever picks the work
up, not an instruction.

**The migration risk 007's plan named still applies, in a smaller form.** Assigning `stock`
everywhere to make things compile would pass every test in the tree and would write the defect down
as an author's declaration. The rule it adopted is worth keeping: **if a site can be migrated
without knowing what its instruments are, it is being migrated wrongly.** A rule alone gets skimmed,
so record the source of each category in the implementation note — a column saying where the kind
came from makes a column of identical `stock` visible in a way the code never will.
