# 065 — An instrument is the project's to declare

Issue 008's ownership move, with issue 009's Decision 1. The roster leaves the venue: a project
declares what each id IS, once, and every venue reads it.

## What was wrong

`ExchangeRulesView` held `instruments`, so a venue *owned* the statement that A005930 is a common
share. But `kind` answers no to both axes canon 2.8 splits an instrument's facts along — a stock
does not become an ETF, and it is a stock on every venue — so the fact was never the venue's.

The consequences were not abstract. A venue could be handed a bare list of ids and every name
silently received STOCK terms, so on a KRX-shaped venue an ETF paid the securities transaction tax
the venue exempts. The category was consumed when the venue was built, and charging afterwards was
a dictionary lookup, so the wrong rate was frozen in with nothing downstream able to notice.

Underneath that sat a quieter one: `kind()` returned `None` for an id nobody described, and every
caller decided for itself what `None` meant.

## What changed

**Venues lost the parameter, not just the requirement.** `AcademicExchange.instruments`,
`KrxExchange(..., instruments=)` and its public `instruments` property are gone. A venue author now
has no channel through which to state a category — removing the argument removes the mistake,
rather than documenting against it.

**`ExchangeRulesView` holds a registry REFERENCE, injected at run assembly.** `with_registry()`
returns a bound copy; `SimulationFlow` binds it once and hands the SAME view to both consumers, so
a partial injection — one route bound, the other not — cannot happen. The bind reads
`exchange.rules` through the property, because a subclass may override it to attach cost bands
(`_CostedAcademic` does) and reading around it would drop those costs and fill at zero.

**Registration is a table, not a component.** A component is a thing Flow CALLS, which is what
`conformance`'s contract table encodes; a roster is a thing a run READS. `vqapr register` takes
kind-keyed parquet tables, validates them against `INSTRUMENT_TYPES`, checks each table's key
against its rows' own `kind` column, and stores a pointer plus a digest. `vqapr new instruments`
emits the script and the declaration together.

**The digest is stated, never compared.** A roster grows as a matter of course — a daily batch
lists new tickers, issuers delist, a name is reclassified — so a gate would refuse every morning,
including on runs that never touch the new name. `roster_digest` joins the run record beside
`source_digest`; what each fill was charged as is testified to per fill by `Fill.kind`.

## The judgement calls, and why

**Charging refuses; stamping does not.** `kind()` raises for an undescribed id, because there is no
honest rate for a thing nobody described — that is issue 007, closed. `stamped_kind()` returns
`None`, because when a fill merely RECORDS what it was, `None` is the truthful answer: the run
genuinely did not know, and recording that beats refusing to record anything. Keeping them apart is
what lets a flat-rate venue run without a roster while a category-dependent one still refuses.

**Sizing falls back, and the fallback has an expiry.** `notional`/`quantity_for` still use the base
conversion when no roster reached the view. Not laziness: all four shipped categories inherit those
methods unchanged, so for every category that exists today the fallback and the declared answer are
the same number, and refusing would stop a run to compute a value it would compute identically.

That is a statement about today, so `_sizing_is_uniform()` checks it on every call — it returns
False the moment any category overrides either method, which turns the fallback off automatically.
The first future with a contract multiplier makes this loud instead of silent, without anyone
having to remember the branch exists.

**A plain mapping is accepted as a registry.** The view only ever asks "what is this id", so
demanding the roster type would force every caller already holding instruments to wrap them for no
gain.

## Migration

19 sites across 6 files, plus `show_005`. Three were inside emitted-source strings that
`pytest tests/exchange` never sees — the class of site a grep for constructor calls misses.

Two tests changed meaning rather than being deleted. `test_a_bare_universe_gets_stock_terms` pinned
the bypass: it now asserts that the bare form still gets stock TERMS while the identity claim is
refused, which is exactly half the old behaviour removed. The `rules.instruments == {}` assertion
became `rules.registry is None`.

`show_005` now registers its roster through the CLI's own entry point rather than reaching past it,
so the showcase would fail if `vqapr register` were broken.

## Validation

- `uv run pytest tests/` — **1,306 passed**.
- All seven runnable showcases pass.
- End to end, through the real registration path: `A005930` (stock) pays `SELL tax = 2000.000`,
  `A069500` (etf) pays `0`, and an unregistered id is refused with *"no registered instrument
  describes 'A000660'; register it before trading it"*. The venue itself holds no roster —
  `venue.rules.registry is None` before binding.
- The migration was measured by running it: 65 failures at the first pass, 54 after separating
  stamping from charging, 19 after the sizing fallback, 0 after migrating the call sites. Each
  reduction was a decision about what the refusal should mean, not a suppression of it.

## Follow-ups

`docs/issues/010` (two writers share one account table) is unaffected and still open. The account
axis — margin, expiry settlement, cash flows that are not fills — remains deferred, and is what an
attribute-bearing category needs before it can arrive.
