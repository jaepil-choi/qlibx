# 049 — A model that follows the package's own data guidance runs 614x slower than the identical model on a reshaped source, and the package offers nothing that closes the gap

**Status: owner-decided 2026-09-01, not yet implemented. This file is the campaign anchor** — the
one issue the read-path work hangs off, because it is the only one that measures the whole gap.
`038`, `044` and `045` are scheduled under it and point here; `035` and `046` are narrowed by it.
The ruling is below, before the measurement that motivated it.

---

## The ruling — a field is an expression, declared where the data is registered

**The shape of a dataset is declared once, at registration. What a model asks for is a field id and
a lookback. Nothing else.** Three layers, and each says only what it owns:

```yaml
datasets:
  krx-flows:
    source_id: krx-flows-source
    path: data/flows.parquet
    available_at: date                                   # the only mandatory column
    instrument_field: ticker                             # OPTIONAL — see 038
    fields:
      close: close                                       # today's syntax, unchanged
      buy_amount:  sum(amount) FILTER (WHERE side = 'buy')
      sell_amount: sum(amount) FILTER (WHERE side = 'sell')
```

```python
DataRequirement.of("buy_amount", lookback=CalendarLookback(days=60, timezone=TZ))
```

`fields` is **id → value expression**. It was already `id → physical column`; a bare column is the
degenerate expression, so every registration that exists today keeps working with no edit. The
framework writes everything around it, from what the dataset already declared:

```sql
SELECT <instrument_field> AS instrument, <available_at> AS available_at, <expression> AS <field-id>
FROM source GROUP BY 1, 2
```

**Four things follow, and they are the reason this shape was chosen over the alternatives.**

1. **The author cannot write a look-ahead.** There is no `FROM` and no `GROUP BY` to reach — an
   expression is evaluated within one instant's group by construction. The boundary that says
   *reshaping within an instant is a field; computing across instants is a DataModel* stops being a
   rule anyone has to check and becomes a property of the grammar. An earlier draft of this ruling
   proposed a registration-time look-ahead test (cut the source at T, compare against the full run
   filtered to T); it was dropped because this shape makes it unnecessary rather than because the
   risk was accepted.
2. **A requirement names one field and a lookback.** No `dataset_id` — a field id is an id, unique
   in the workspace, and the registration already knows which dataset it belongs to; naming both was
   saying one fact twice. No `consumer_id` either: the component declaring the requirement *is* the
   consumer, so the framework stamps it. It still reaches `AccessRecord` exactly as today.
3. **The universe filter follows the data's own shape.** `instrument_field` is optional. A dataset
   without one has no instrument axis, so the declared instrument list is not applied to it — which
   is `038`'s "better fix", moved from the requirement to the dataset, where it belongs: whether a
   table is keyed by instrument is a fact about the table, not about who reads it.
4. **One scan serves many fields.** Requirements are all declared before any read, so expressions
   over the same dataset fuse into one `SELECT`. Declaring one field per requirement therefore does
   not multiply scans — see `046`.

### What was rejected, and why it is recorded

- **A `where=` argument on `DataRequirement`** — this file's sibling `045` proposes exactly that, as
  a closed typed vocabulary. Rejected: the predicate is a property of how the dataset is read, not
  of one consumer's request, and putting it on the requirement puts it in the one place that must
  stay small. `045`'s reasoning about the PIT line is not overturned — it is honoured more strictly,
  since the author never touches the window at all.
- **A separate registrable kind for readings**, with its own id and its own `list`/`show`. Rejected:
  a field-set is not a peer of a dataset, it is part of one. It nests under `datasets:` in the
  workspace document and adds **zero** new kinds.
- **Free-form SQL per field.** Rejected for now. It buys joins and subqueries and loses both
  properties in (1). A model that needs a join is a DataModel. Revisit only when a real case is
  blocked, and record what is being given up.

### What stays open after this ruling

Whether `ObservationBatch.rows` should stop being a tuple of dicts and become columns (`035`'s
columnar accessor). Wide delivery removes most of the cells that made row-major boxing expensive, so
**this is re-measured after the ruling lands rather than decided now.**

---

**Status when filed:** open, and filed as the **severity** of what
[044](044-the-read-path-revalidates-eight-column-names-once-per-row.md),
[045](045-a-requirement-cannot-say-which-rows-so-a-long-table-delivers-a-hundred-and-fifty-times-what-is-kept.md)
and [035](035-the-only-data-accessor-is-ninety-times-slower-than-the-file.md) each describe one
surface of. Measured 2026-08-31/09-01 in `kwam-enhanced-index/vqapr-performance-testbed/` against
`vqapr-0.2.0a2` (built wheel).
**Touches:** the read path as a whole — `data/requirements.py`, `data/scan.py`, `data/store.py`,
`domain/rows.py`, `data/windows.py` — and, more than any single module, **`SKILL.md`'s data
guidance**, which is what a user follows into this.

## A blocked case, raised before anything is widened — workspace-global field ids

**Found 2026-09-01 while implementing lane C, verified against the live research workspace, and not
decided here.** The campaign's §6 says a case the ruling blocks in practice goes into this file and
up to the owner rather than being resolved by whoever hits it. This is one.

The ruling below says a requirement names a field and nothing else, **because a field id is an id,
unique in the workspace**. Lane C implemented that: registration refuses an id another dataset
already exposes, naming that dataset. `qlibx-b8` raised that this breaks
`vqapr-enhanced-index-3`, this package's principal consumer, and it does — more widely than the
report suggested.

That workspace holds 27 datasets. **21 field ids are exposed by more than one of them**, and they
are two different things:

| kind | examples |
|---|---|
| **parallel series, deliberately schema-identical** | `rmrf` `smb` `hml` `rmw` `cma` `mom` on `ff5-factors-broad` / `-k200`; `residual` `realised` `beta_*` on `residual-returns-broad` / `-k200` |
| **ordinary domain vocabulary that recurs** | `fiscal_yyyymm` on **six** datasets; `settlement_type` on three; `fiscal_year` on three; `market_cap` on two; `account_code`, `numeric_value`, `statement_scope` on the statement pair |

**The first kind is the design.** That environment's README states it: there is no right answer
between the two universes, the comparison is the point, and the two series share a component and an
agenda so that the only difference between them is the universe. Schema parity is what makes the
comparison possible; renaming to `residual_broad` / `residual_k200` ends it.

**The second kind is harder to argue with.** `fiscal_yyyymm` is on six datasets because that is what
the column is called wherever it appears. Nobody chose a colliding name; the word simply recurs, and
a rule that makes it an error asks a researcher to invent twenty-one names whose only purpose is to
differ from each other.

**What is actually at stake.** The workspace still *opens* — uniqueness is checked at registration
and decode does not re-litigate it — so nothing already built stops working. What breaks is the
**rebuild**: `build_specs.py` emits both members of each pair into one declaration, `_apply`
registers them in order, and the second is refused naming the first. Twelve factor books, about
19 GB, sit downstream of that path.

**This is not a defect in the implementation, and not something a rename fixes.** It is the ruling's
premise meeting a workspace built before it. Options visible from here, none of them chosen:

1. **Keep uniqueness; the consumer prefixes its field ids.** Costs the rebuild, and costs the
   property the parallel series exist for unless the reading component takes its field ids from
   config.
2. **Scope uniqueness to a dataset, and let a requirement name `(dataset_id, field_id)`.** That is
   the `dataset_id` the ruling removed, so it is a change to the ruling rather than to the code.
3. **Unique by default, qualified when ambiguous** — a requirement may name `dataset.field`, and a
   bare field id is refused only when two datasets answer to it. Keeps the common case as the ruling
   describes it, and lets a deliberate parallel series say which one it means.
4. **Move the question from registration to resolution** — let ids collide in the workspace and
   refuse only when a run's own requirements cannot be resolved unambiguously. Nothing scopes a run
   to a subset of datasets today, so this needs a way to say which series a run reads.

Lane C is gated and ready but **is not merged**, because items 4 and 5 of its list are one question:
a requirement can name a field alone only if a field id resolves to one dataset.


## The claim

Registering a dataset at the vendor's grain is what the package tells an author to do, and it is
good advice: which of a name's many rows on one date a research question means is a research
decision, and collapsing it upstream hides that decision in an ETL step nobody reviews.

**An author who takes that advice pays 614x.** Not 614x on a microbenchmark — 614x on a real
materialization, publishing byte-identical output, with the model's own arithmetic unchanged.

## The measurement

`annual-fundamentals` reduces a Korean statement warehouse to the annual quantities a Fama-French
sort needs. It was run twice: once against `statement-facts` registered long at the vendor's grain,
and once against the same facts with the account axis pivoted into columns and the scope/settlement
tests pre-applied. Same evaluation instants, same instruments, same output fields, same workspace,
**back to back in one process**:

```
1,600 instruments x 4 evaluations

              wall     per eval    emitted    where the time went
long        806.61s     201.65s      5,098    normalize=428.06s  sql=319.65s  query=43.10s
wide          1.31s       0.33s      5,098    compute=0.36s  normalize=0.30s  sql=0.22s
                                                                             614x

source parquet      84.0 MB  ->  0.79 MB
registration         5.88 s  ->  0.10 s
```

**The output is identical.** All eight published value fields, both directions, full anti-join:
zero rows only in long, zero only in wide. That was checked before the timing was read, because a
materialization that is 600x faster and slightly different is a different model rather than a
faster one. The wide model does not reimplement the reduction — it calls the long model's own
`_derive`, its account-code fallback ordering and its prior-year asset guard.

**The pivot is an exact reduction, and that was checked rather than assumed.** It holds only if no
`(instrument, fiscal_period, account_code)` and no `(instrument, fiscal_period)` appears at more
than one `available_at`. Both are zero on this warehouse, and the experiment re-checks them on
every run and refuses to proceed otherwise. That is a property of the data, not of the code.

## What the model's own time is

1.9%. At the widest ladder point the boundary probes attribute 48.6% of a long materialization to
`normalize_rows`, 44.7% to the SQL, 4.7% to the store's own bookkeeping, and **1.9% to
`DataModel.compute`** — the part the author wrote and the only part that is about finance.

## Why it is 614x and not 153x — the two halves

|  | rows | cells |
|---|---|---|
| long, as the package's guidance produces it | 553,560 | 4,428,480 |
| a predicate pushed down, still long (issue 045) | 3,617 | 28,936 |
| pivoted as well | 225 | 3,375 |

* **A predicate removes rows the model discards** — 153x here.
* **The shape removes the key columns that ride beside every value.** A long row carries five
  identifying columns to deliver one number, so even the 3,617 rows a predicate would keep still
  carry 28,936 cells to deliver ~3,600 values. A further 8.6x that no predicate can reach.
* **And the file itself became 100x smaller**, so the scan got cheap too — which is why the wall
  gain exceeds both cell counts.

This is the reason to file it as one issue rather than leave it as three. 045 alone is worth
"several times". 044 alone is worth ~40% of a window read. 035's columnar accessor addresses the
boxing. **None of them alone is 614x, and a reader triaging them separately would rank each as a
moderate optimisation.** Together they are the difference between a 20-minute rebuild and a
two-hour one for this research environment, and between `annual-fundamentals` costing 1,193s and
costing about 5.

## The part that makes it a package problem rather than a user problem

The remedy exists and the user can reach it — pivot in preparation, register the wide form. It
works, it is 0.3 seconds to build, and this issue's own measurement is that remedy.

**But taking it means overriding the package's data guidance.** Concretely, the pivot had to decide
three things the long registration deliberately left open:

1. consolidated vs separate statements — fixed to consolidated;
2. annual vs quarterly settlement — fixed to annual;
3. which download bundle wins when two rows disagree — fixed to latest `dump_last_modified`.

The third is not optional: a column cannot hold two values, so any pivot must resolve it. So the
author's choice is between **a defensible data model that is 600x slow** and **a fast one that has
moved research decisions into an ETL step**. The package currently makes that a real trade, and it
does not have to be one — every one of 044, 045 and 035 removes part of it without asking the user
to give anything up.

What the package does *not* offer, and what would close this:

* no way to declare which rows a requirement wants (045);
* no way to receive a window in columns rather than as one dict per row (035);
* no read path that trusts what registration already validated (044, and 035's owner ruling);
* and no guidance anywhere that says a long registration is expensive to read, so the cost is
  discovered after the schema is committed to, not while it is being chosen.

The last one is the cheapest thing on this list and is worth doing even if none of the others are:
**say in `SKILL.md` that the read cost of a dataset scales with the cells its window admits, and
that a long/EAV registration multiplies those cells by its key width.** An author told that once
will register a second, narrow dataset beside the faithful one on purpose — which is the shape this
research environment arrived at after paying for it.

## Reproducing

`kwam-enhanced-index/vqapr-performance-testbed/`:

```
uv run python wide_experiment.py --instruments 1600 --evaluations 4
```

It builds the pivot, verifies the grain properties, materializes both, diffs the published parquet,
and prints the table above. `pivot_experiment.py` isolates the read alone (10.19s -> 0.048s on one
window), and `bench.py --stage datamodel` is the ladder the 1.9%/48.6%/44.7% split comes from.

**One caution on absolute seconds.** The same long point measured 492.58s in an earlier ladder and
806.61s here, at `busy` 1.0 in both — no other process was taking the core, so the likeliest cause
is clock behaviour under a long single-threaded load. **The 614x is a within-process ratio measured
back to back and does not depend on that**, but absolute seconds from different sessions should not
be compared.
