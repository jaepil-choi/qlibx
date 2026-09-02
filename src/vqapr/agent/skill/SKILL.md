---
name: vqapr
description: Quantitative strategy backtesting framework — registration, materialization, simulation, and measurement
---

# vqapr agent skill

**Use this skill when the task involves registering financial datasets, building and testing
quantitative strategy models, materializing evaluation data, or running backtesting simulations
with the vqapr framework.**

## What vqapr is

vqapr is a deterministic backtesting framework for quantitative portfolio strategies. It takes
registered datasets and strategy components, materializes evaluation data, runs simulations
against a declared venue, and produces measurement results. The framework validates every input
before executing and refuses with structured diagnostics when something is wrong.

## What this skill does and does not do

**The CLI owns usage; this skill owns remedy.** When vqapr refuses an input, the CLI tells you
*what* failed (structured JSON with stage, code, requirement, observed, and examples). This skill
tells you *how to fix it* — what the failure means in context, what your options are, and what
trade-offs each option carries.

This skill **never**:
- Bypasses package validation
- Guesses missing semantics
- Confirms a binding before evidence exists

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## The mission path — three rungs

Work with vqapr follows three rungs. Each rung depends on the previous one succeeding.

### Rung 1 — Registration

**Goal:** a workspace where every dataset, source, component, execution input, and agenda is
registered and passes validation.

1. `vqapr list datasets` -- see what exists (returns empty on a fresh workspace, that is fine)
2. `vqapr new strategy <id> --dataset <d>` or `vqapr new datamodel <id> --dataset <d>` --
   scaffold a runnable `.py` plus a matching `.yaml`. You can register either one: the YAML with
   `vqapr register <file.yaml>`, or the source directly with `vqapr register strategy <id>
   <file.py>`, which needs no YAML at all.
3. `vqapr register strategy <id> <file.py>` -- register it by naming the kind, the id and the
   file. The file must define exactly one `StrategyModel` subclass; zero and two are both
   refused, and the refusal says which.
4. `vqapr new dataset --out d.yaml` -- get a dataset template with every required key
5. `vqapr new execution-input --out ei.yaml` -- get a venue-table template
6. `vqapr new exchange <id> --instruments A005930 A000660 --out venue.py` -- get a runnable
   Exchange plus the declaration that registers it. **Every instrument the run trades needs a
   listing here**, or preflight refuses it by name. `AcademicExchange` and `KrxExchange` are the
   only two profiles a registered Exchange may be; the scaffold uses the first.
7. `vqapr new agendas --out agendas.yaml` -- get agendas, strategy_configs, and valuation_configs
   together (a config binds a role to an agenda, so neither half is usable alone)
8. Fill in the placeholders and `vqapr register <declaration.yaml>` for each. Datasets, sources
   and agendas stay in YAML because they ARE declarations -- there is no code to point at.
9. `vqapr list <kind>` -- confirm what was registered, and `vqapr show model <id>` to see what a
   component declares it reads, decides, forms, weights and records

**What a dataset's shape costs, priced before you commit to it.** Both numbers are measured, and
they are on opposite sides of the ledger.

- **Registration** reads the file once per declared logical key: the cost scales with
  `rows x key width` and not with file size, at roughly 50M row-keys per second. A 37.8M-row
  warehouse registered on six key fields takes seconds, and that is the whole of it -- paid once
  per workspace. If any `fields:` entry exposes a numeric column, registration reads the file once
  more to refuse a NaN or an infinity in it -- one pass for all such columns at once, however many
  you declare. **A non-finite value is refused here or nowhere**: reads trust what registration
  accepted, so a NaN that gets past this point reaches a model and propagates through every number
  it touches while the run still reports a result. Prepare a genuinely absent value as `NULL`,
  which is read as a missing observation rather than as a number.
- **Reading** depends on the dataset's `grain`. A panel grain (`instrument_instant`, `instant`)
  is read into a **panel once per run** -- one scan -- and every later read is a slice of it, by
  arithmetic. A `rows` grain (the vendor's long / EAV table) is re-cut on the file per read, and
  the cost scales with the **cells the window admits** times the key width: every one is read,
  boxed into a dict and handed across the boundary even when the model discards it.

**Register a date x ticker table as `grain: instrument_instant`.** That is the shape a panel is
built from and the shape a cross-sectional model reads safely. When the vendor's grain must be
preserved -- several rows per name and date, each a fact of its own -- register it **as well**, as
`grain: rows`, and derive the `instrument_instant` table from it with a DataModel: which of a
name's many rows on one date a research question means is a research decision, and keeping the
collapsing in a reviewable component rather than an ETL step is the point (`docs/issues/049`
measured one such pair at 614x with byte-identical output). A `rows` dataset is read with
`rows(alias)` and an `InstantsLookback`; a panel with `read(alias, field)` and a `RowsLookback`
or `CalendarLookback`.

**A DataModel derives a column, and `run` executes it.** A StrategyModel decides what to hold; a
DataModel computes a new dataset from the ones you registered; a Constraint bounds what a book may
hold. All three are authored the same way -- one import, `from vqapr import authoring as va`; one
declaration, `inputs()`; one read verb, `.read(alias)` -- and differ only in the verb that is
theirs: `decide`, `compute`, `project`/`monitor`. `vqapr show model <id>` describes any of them.

**What a model is handed follows the dataset's `grain`.** `inputs()` returns a mapping from an
alias you name to a `va.DatasetInput(dataset_id=, fields=, lookback=)`, and the call reads it
with one of two verbs, in every role:

- **`read(alias, field)` on a panel grain** (`instrument_instant`, `instant`) returns a
  **`PanelWindow`**: `instants` (the same for every name) x `instruments`; `values[name]` is
  that name's values over the instants, `None` where it had none; `latest()` is the newest value
  per name -- the cross-section. It is a slice of a panel the run built once, not a query.
- **`rows(alias)` on `grain: rows`** (the vendor's long table) returns a **tuple of
  `Observation`s**, one per (instant, instrument), each carrying `instrument_id`, its own
  `available_at` and `values`; names interleave within an instant.
- Each verb refuses the other grain by name. A value keeps its parquet column's type -- `float`
  from a DOUBLE column, `Decimal` from a DECIMAL one -- so write `Decimal(str(value))` and never
  `Decimal(value)`.

**Choose the lookback member deliberately; they are a pair.** `RowsLookback(rows=N)` gives each name
its **own** last N observations, so on an unbalanced panel the batch's calendar span is set by the
sparsest name and is unbounded above: a real 1,637-name universe asking for 313 rows got rows
spanning 1,865 sessions, back eight years. That is right for a per-name question -- a trailing
return, a moving average -- and silently wrong for a cross-sectional one, where a correlation matrix
would mix a live name's recent returns with a delisted name's decade-old ones and pass every check.
`CalendarLookback(days=N, timezone=...)` gives every name the same window and is the member a
covariance matrix, a factor regression or any date-aligned model wants. Scaffold the first with
`vqapr new datamodel --lookback N` and the second with `--calendar-lookback DAYS`.

A materialization spec names `datamodel:` where a simulation names `strategy:`, and that is what
tells `run` which it is holding — declare both, or neither, and it refuses rather than guessing:

```yaml
datamodel: my-derived            # the registered component to run
instruments: [A005930, A000660]  # what to evaluate over
output:
  dataset_id: my-derived-values  # must NOT already be registered
  value_fields: [value]          # the columns it writes
evaluate_at:                     # when to evaluate; timezone-aware, one entry minimum
  - "2024-03-06T04:00:00+09:00"
```

Then `vqapr check <spec.yaml>` and `vqapr run <spec.yaml>` with the file's path -- a
materialization is the one spec that is still a file; a simulation is a registered run and is
named by id (Rung 2). It registers a dataset rather than writing a run record, so `vqapr list
datasets` shows it arrived and
`vqapr show dataset <id>` reads back what it computed. The output is readable by any component
that declares it — which is the point: one model's output is the next model's input.

**`vqapr show dataset <id> [--limit N]`** works for any registered dataset, not just a
materialized one. It reports the registration's own facts — source, path, declared fields, span —
alongside the rows, and reports `rows_total` separately from `returned` so a truncated page never
reads as a short dataset. `--limit 0` returns every row.

`--strategy`, `--jobs` and `--force` are refused here. All are defined in terms of a run record
and a materialization writes none; to replace an output, remove its dataset registration first.

**Reading a finished run: two records.** `vqapr show run <run-id>` gives the CONFIGURATION
every strategy of the run shared -- instruments, period, venue, the execution input and its
fill convention, the initial account, the datasets read and their source digests -- and
`recorded`, the strategy records the store holds as `<strategy-id>@<fp8>`. `vqapr show
strategy <run-id>/<strategy-id>@<fp8>` gives one strategy's OUTPUT: the component that ran
(path and its own fingerprint, registered and as loaded), its constraints, the final account,
the contract report, the roster it read, and per-table row counts. `--table <name>` on
`show strategy` gives the rows themselves, with `--limit` (0 for all) and `--instrument <id>`
to keep only one instrument's rows -- `--instrument _ACCOUNT` on `vqapr.account` is that
strategy's NAV series. It reports `rows_total`, `matched` and `returned` separately, so a
truncated page never reads as a short run. `<run-id>/<strategy-id>` without the fingerprint
works when exactly one record of that strategy exists; `vqapr list strategies --run <run-id>`
lists them all, filterable by `--strategy`, `--fingerprint`, `--failed-contract`, `--since`.

**Read a record from Python with `vqapr.public.read_strategy_table(store_root, run_id,
table, strategy_ref)`, never by parsing the JSONL yourself.** The rows are JSONL on disk
(`.vqapr/runs/<run-id>/strategies/<strategy-id>@<fp8>/tables/`), and JSON has no `Decimal`
and no offset-aware instant: a reader that guesses from the text -- `read_json_auto` included
-- shifts every instant by its offset and the panel built from it registers cleanly.
`read_strategy_table` decodes by the column types the writer recorded beside the table, so
`nav` comes back a `Decimal` and `observed_at` an aware `datetime`. Rows reach the disk as
each occurrence is accepted, so a long run can be watched and a killed one keeps what it did.

`vqapr run <run-id> --no-account-positions` records only the `_ACCOUNT` row (cash and NAV)
at each valuation instead of one row per held instrument; fills are recorded either way.

Every run records three tables, plus any the model **declared and then formed** — a table must
be returned from `StrategyModel.tables()` as a `TableSpec` before `decide()` may write to it
through `self.recorder`, and writing to an undeclared one refuses mid-run:

- **`vqapr.account`** -- the book over time. `instrument` (`_ACCOUNT` on the cash and NAV row),
  `account_version`, `cash`, `quantity`, `price`, `nav`, `observed_at`. `observed_at` is declared
  by this table alone and is not the same clock as the envelope's `event_time`: one is when the
  fact was seen, the other when it happened.
- **`vqapr.fill`** -- what was traded and what it cost. `instrument`, `kind` (the category the
  registered roster gave it, or null when none was registered), `requested_quantity`,
  `dealt_quantity` (negative on a sale), `price`, `commission`, `tax`, `cash_delta`, `reason`,
  `account_version`. **This is the table cost questions are asked of** -- commission and tax are
  per fill and per side, so a category's true cost is a sum over this table, not a rate you can
  read off a venue.
- **`vqapr.weight`** -- the intended allocation per evaluation, before execution. `instrument`,
  `weight`.

Every row of every table also carries the same five envelope fields: `run_id`, `producer_id`,
`stage`, `event_time` and `sequence` -- which run wrote it, what wrote it, at what point, when the
fact happened, and in what order. A table cannot declare one of these as a column of its own.

A fill's `kind` is what the ROSTER said. What it was CHARGED as comes from the venue's own terms.
Those are two statements and nothing compares them (`docs/issues/013`), so keep a venue's declared
categories in step with the registered roster.

**A run needs five declarations**: a dataset, an execution input, an exchange, agendas with their
configs, and at least one component. Each has a `vqapr new` scaffold; if you are hand-writing one
of them, check for the template first.

**And it wants a sixth: the instrument roster.** `vqapr new instruments` scaffolds the exporter and
its declaration. It is not in the five because a run without one still completes -- but every fill
then records `kind: None`, `cost_by_kind()` collapses to one unlabelled bucket, and on a costed
venue every name is charged as if it were the same thing. `vqapr run` states which roster it read,
or that it read none, and `vqapr list instruments` shows what is registered.

**Costs.** `vqapr new exchange <id> --profile krx` emits a venue that charges what KRX charges,
built from `krx_rules` -- the one call that gets the ETF sale-tax exemption right, since a stock
pays it and an ETF does not. The default `--profile academic` fills free, which is what makes it
academic; its scaffold names `buy=`/`sell=` `SideCost` as the fields it deliberately leaves out.
A venue names no categories at all: `KrxExchange` takes ids, and what each one IS comes from the
registered roster at fill time. A KRX venue run without a roster refuses to charge rather than
assuming a share.

**The `krx` profile is long-only, and the venue has to agree with the account.** `krx_listings`
sets `access=ListingAccess.LONG_ONLY` on every rule it builds, so `--profile krx` cannot hold a
short. Pairing it with `initial_account.mode: SIGNED` is a combination nothing refuses at scaffold
time and that cannot hold a position -- the account permits the short and the venue declines it.

**So a costed long/short book needs a venue you write.** There is no shipped SIGNED costed profile.
Set `access=ListingAccess.SIGNED` on your own listings, which is the `ListingAccess` member for a
rule that may be held either way, and declare the costs as below. `--profile krx` is the right
starting point for a long-only book and the wrong one for a signed book.

**Writing your own costed venue.** Subclass `AcademicExchange` and declare the cost one of two
ways, and the choice matters:

- **A per-instrument fee** — give each listing its own `buy`/`sell` `SideCost`. Right when the rate
  genuinely belongs to the instrument.
- **A rate that follows the category** — set the class attribute `terms_by_kind`, a mapping of
  `InstrumentKind` to `TradeTerms`. The charge is then resolved per fill from the roster.

Do not express a category-driven rate as per-instrument costs. That keeps a second copy of what the
roster already declares, and the two can disagree — the fill records the roster's category while
the money follows yours. Nothing detects it, because per-instrument rates are legitimate when they
are not standing in for a category.

**Constraints.** A strategy's optional `constraints:` list -- under its entry in the run's
`strategies:` -- names registered components of kind `constraint`. `vqapr new constraint <id> --cap 0.2` scaffolds a single-name position cap that
registers and runs unedited. It has two members and two consumers: `project` returns the lower AND
upper weight bound for every instrument -- the box the optimiser must stay inside, not the
offenders and not a correction -- and `monitor` looks at the marked account from outside and
returns a `ConstraintFinding` with the bound and the measured value. A breach never stops a run;
it is recorded, and `show strategy` reports it under `contract`.

**Stop condition:** `register` accepted every declaration without failures, and each kind you
registered lists what you expect. `list` takes exactly one kind per call and `kind` is a required
positional -- there is no all-kinds form, and bare `vqapr list` is refused with
`cli.usage.rejected` -- so checking a Rung 1 setup is one call per kind:

```
vqapr list datasets
vqapr list sources
vqapr list components
vqapr list agendas
vqapr list execution-inputs
vqapr list strategy-configs
vqapr list instruments
```

The remaining four kinds are `valuation-configs`, `monitoring-policies`, `runs` and
`strategies` -- the last two are Rung 2: `vqapr list runs` is the registered runs and the records
beside each, `vqapr list strategies --run <run-id>` those records. A kind you registered nothing
under returns `count: 0`, which is an answer rather than a failure.

#### Correcting a registration during setup

Registrations are immutable identities in the sense that one id means one declaration -- registering
a *different* declaration under an id that is already taken is refused, because that is a genuine
mistake rather than an edit. Correcting the thing you already registered is not that, and it is the
ordinary loop: edit the file and `vqapr register <file> --force` to replace it in place. The id
stays, dependent configs and specs keep working, and the run record carries a new `source_digest`
for whatever ran.

That digest is the provenance, and it is a **receipt rather than a gate**: it records what ran, and
nothing re-checks it afterwards. Two runs of edited code carry two different digests, which is what
makes an edit visible in the record.

- **Editing a component you registered:** change the file and re-register with `--force`. No new id,
  no config edit, no spec edit.
- **Withdrawing one:** `vqapr remove <kind> <id>` refuses while something still references it, and
  names what does.
- **A genuinely different declaration:** give it its own id, so one id never means two things.
- If this is a disposable first-run workspace with no result to preserve, keep the authored YAML
  and component files, obtain approval for the destructive reset, remove only the project-local
  `.vqapr/` workspace state, then register the corrected declarations from scratch. Never delete
  source data or authored declarations as part of that reset.

#### Before registering: settle what `available_at` means

**This is the decision to raise before the first `register`, not after it fails.** The framework
validates schema, keys and duplicates. It cannot detect a look-ahead, because a timestamp that is
wrong in meaning is still perfectly well-formed.

`available_at` is **when the row could first have been known**, not when the event it describes
happened. Those differ, and the gap is where look-ahead enters:

- A daily close observed at the session close is available at that close, not at midnight of the
  same date.
- An accounting fact for a fiscal quarter is available when it was *published*, which is weeks or
  months after the period it covers. A fixed lag applied to a period end is an approximation, and
  whether it is a safe one is a judgement about the data, not about vqapr.
- A revised or restated value is available at the revision, not at the original observation.

Ask, and do not answer on the user's behalf:

1. Is this column an observation, a publication, or a revision?
2. What timezone is the timestamp in, and is it the event instant or a date?
3. If it is a date, what instant within that date is defensible?

If the answer is not in the data or its documentation, say that it is unknown and let the user
decide. **Do not infer a convention from a column name.** A column called `date` proves nothing
about availability, and a registration built on that guess produces results that look correct.

#### Prove the timezone conversion on one known instant

Naming the right zone is not enough. A schema-valid, timezone-aware column can still hold the
wrong instant. Before preparing the whole dataset:

1. Pick one row whose local wall time and UTC equivalent are known.
2. Run that row through the exact preparation code.
3. Assert the local date, local time, UTC offset, and UTC conversion.
4. Convert it back to the venue zone and assert the original wall time is recovered.

This catches a common pyarrow footgun: casting a timezone-naive timestamp to
`timestamp(..., tz="Asia/Seoul")` preserves the underlying epoch value and changes how it is
displayed; it does **not** mean "interpret this wall clock as Seoul time." For that operation use
an explicit localization operation such as `pyarrow.compute.assume_timezone`, then prove the
round-trip. A daily row shifted by nine hours still has a valid timezone-aware schema, so
`vqapr register` cannot distinguish it from an intentional timestamp.

The same care applies to query patterns written at registration time. Moving averages, cumulative
sums and ranks can each reach across rows in a way that pulls future information into a past row;
flag them and explain what would have to be true for the pattern to be safe.

### Rung 2 — Materialization and run

**Goal:** a completed run that produces a result per strategy.

A run is configuration, registered like everything else: the universe, the period, the
venue, the execution input, the initial account declaration, and the strategies it tries.
Each strategy runs with its OWN account from that declaration, under the agenda its
`strategy_configs` binding names, and writes its own record. Three factor models on one
cadence are one run with three strategies, not three runs.

1. `vqapr new run --out runs.yaml` — get a `runs:` declaration template with every required
   key explained
2. Fill in the template with registered component ids, the valuation agenda id, instruments
   and dates; list every strategy to try under `strategies:` (each needs a binding from
   `vqapr new agendas`)
3. `vqapr register runs.yaml` — the run is refused here if it names anything unregistered
4. `vqapr check <run-id>` — prove it before spending a run. `check` runs **four phases** and
   makes **eight independent judgments** -- for every strategy the run names -- and reports
   all of them in one call, so a run with four defects costs one command rather than four. It
   writes nothing.

   The two numbers are different things and the envelope shows the first: `checked` lists the
   four phases — `workspace`, `run`, `judgments`, `preflight` — and the phase named
   `judgments` is where the eight are made. Counting the envelope's list and expecting eight
   is the obvious mistake; it is four, and nothing is missing.
5. `vqapr run <run-id> [--strategy <id>]... [--jobs N]` — preflight once, freeze, and execute
   every strategy (or those named), in `N` processes when asked

**Stop condition:** `vqapr check <run-id>` returns `ok:true`, then `vqapr run <run-id>`
returns `ok:true` with a `strategies` map carrying an `occurrences` count, an
`account_version` and a `record` (`<strategy-id>@<fp8>`) per strategy.

**Tweaks are directories.** A strategy's record is named by its registered fingerprint, which
folds the file bytes and the config: edit the strategy and re-register it under the same id,
run again, and the new record lands BESIDE the old one. Counting `<strategy-id>@*` under
`.vqapr/runs/<run-id>/strategies/` is how many times it was tweaked. Running the same
fingerprint again is refused unless `--force` replaces that one record; `vqapr rm strategy
<run-id>/<strategy-id>@<fp8>` and `vqapr rm run <run-id> [--keep-latest]` remove records, and
both refuse while a writer may still hold the record.

## Writing a strategy

A strategy is a Python file. It declares what it reads and returns what it wants; identity,
provenance and the account version are the framework's, and an author never writes them.

```python
from vqapr import authoring as va

class Momentum(va.StrategyModel):
    def inputs(self):
        read = va.DatasetInput(dataset_id="prices", fields=("close",), lookback=va.RowsLookback(rows=20))
        return {"prices": read}

    def decide(self, call):
        window = call.read("prices", "close")   # instants x instruments; window.values[name]
        ...
        return va.Rebalance.of(long={"A": 2, "B": 1}, invested="0.9")
```

What the strategy needs to remember between callbacks lives in `self.memory` (strict JSON): the
framework restores it before every `decide()` and snapshots it after, so read it, change it, and
leave it. One instance serves the whole run.

`Rebalance.of` takes **relative** conviction. `long={"A": 2, "B": 1}` means A is liked twice as
much as B; normalising, rounding onto the canonical grid and balancing against cash is the
package's arithmetic, not yours. You never make weights sum to one by hand.

A short is declared by **which mapping** a name appears in, never by a negative number:
`short={"A": 2}` means twice as short. Passing both sides makes the book signed automatically.

Return `Hold(reason="...")` to decline. The reason is one token, no spaces.

### Before you hand-roll it: `vqapr.public`

`vqapr.public` exports about 160 names, and **the CLI help does not list them**. Check it before
writing portfolio arithmetic of your own — a first-time journey hand-rolled 30/70 breakpoints and a
bucket assignment that were already in the package, and four of that journey's findings turned out
to be answerable from this one module.

```python
import vqapr.public as public
[name for name in dir(public) if not name.startswith("_")]
```

Three families are worth knowing by name.

**Fama-French sorting.** `fama_french_cut_points(values, reference=..., fractions=...)` returns the
quantile thresholds estimated from the reference subset only; `fama_french_assign(values,
thresholds=..., labels=...)` maps names onto buckets. `fractions=(Decimal("0.3"), Decimal("0.7"))`
is the standard 2x3 sort. Interpolation is explicit because it moves portfolio membership:
`linear` is the pandas/numpy default and matches the validated Korean replication behind these
helpers; `nearest` is the alternative.

**Weighting and neutralization.** `equal_weight`, `proportional_weight`, `signal_weight`,
`neutralize`, `optimize`, `rescale`, `net_members`. Each has a matching typed refusal —
`WeightingRefusal`, `NeutralizationRefusal`, `OptimizeRefusal` — so a book that cannot be built
says why rather than returning something plausible.

**Measurement.** `information_coefficient`, `rank_information_coefficient`, `rank`, `nav_series`,
`returns`, `drawdown`, `hit_rate`, `decay`.

These are library calls, not CLI verbs. Use them inside `decide()`, or in your own preparation code
before a run.

### Rung 3 — Measurement

**Goal:** verify that the simulation produced the expected results and that measurements are
reproducible.

This rung depends on what the specific task requires. Common steps:
- Compare output against known baselines
- Verify that account state matches expectations
- Check that the simulation result is deterministic across runs with identical inputs

## Reading vqapr's output

Every vqapr command returns exactly one line of JSON to stdout. The shape is always:

```json
{"ok": true, "stage": "...", ...}
```
or
```json
{"ok": false, "stage": "...", "family": "...", "failures": [...], "error": "..."}
```

**`ok`** — did the command succeed?
**`stage`** — which processing stage produced this result (e.g. `workspace.register`,
`run.complete`, `cli.input`)
**`failures`** — an array of structured diagnostics. Every entry carries `code`, `source`,
`requirement`, `observed`, `fix` and `explain`; `examples` and `example_total` are present but
**may be empty**. The six keys are always present, including on a `cli.usage` refusal from the
argument parser; `source` and `explain` are `null` there, because a rejected command line has no
file to point at and no package concept to explain, but `fix` is always a sentence you can act on
**`error`** — the Python exception as a string, for traceability

When `ok` is false, read `fix` first. It is the sentence that fixes *this* occurrence, written as
an action you can take. `requirement` says what was needed and `observed` says what was found;
`source` says where — it is an object with `file`, `key_path` and `line`, any of which may be
`null` when the failure does not have that kind of location. Read `source` as structure, never by
parsing a formatted string out of the other fields.

`explain` names the section of this skill that explains why the whole class of failure happens and
how to stop causing it. The set of topic ids is closed and every one of them resolves to a
"Recovering from…" section below. It is `null` on a `cli.usage` refusal, and only there: the
argument parser rejected the command line before any package concept was involved, so there is no
class of failure to explain — `fix` carries the whole answer.

**`examples` is empty for structural checks, and that is not a bug.** A check on a column's
*type* has no offending row to quote, so it reports `"examples": [], "example_total": 0`. A check
on row *contents* — a duplicated key, a null in a key field — quotes up to five offending values
and `example_total` says how many there were before truncation. An empty `examples` next to a
non-zero `example_total` never happens; if you see one, that is worth reporting.

Fix the inputs and retry.

## Recovering from a refusal

Every refusal carries an `explain` topic. There are seven, and each names one of the sections
below. `fix` tells you what to do about the single failure in front of you; these sections tell
you what the failure means and how to stop hitting it.

### Recovering from: declaration-shape

The declaration document does not have the shape the contract requires — a missing key, a value
of the wrong type, a value outside the permitted set, or a section vqapr does not recognise.

vqapr never guesses a missing key and never coerces a value. Read `source.key_path`: it names the
exact position in the document, so you can go straight there rather than re-reading the file.
`observed` shows what was found at that position. When a value must come from a fixed set, the
`requirement` lists that set.

Generate a fresh template with `vqapr new` when a document has drifted far from the contract;
editing a correct template is faster than repairing a wrong one.

### Recovering from: dataset-preparation

The declaration is well-formed but the parquet behind it does not satisfy what registration
requires: a declared column is absent, the logical key is not unique or contains nulls,
`available_at` is not timezone-aware, or the dataset carries no dated row at all.

These are all fixed while *preparing* the source, not while registering it. vqapr deliberately
does not convert a naive timestamp for you: only you know which instant a value means, and a
wrong localisation is a silent point-in-time leak rather than an error. Localize at the instant
the row became knowable — a daily close is knowable at that session's close in the venue's
timezone, not at midnight.

For key failures, `examples` quotes up to five offending values and `example_total` says how many
there were, so you can tell a typo from a systematic duplicate.

### Recovering from: source-access

The declaration is right and the data may be fine, but the path cannot be reached or read: the
file is not there, it is not readable parquet, or a specific field cannot be queried from it.

Check `source.file` first — it is the path vqapr actually resolved, which is often the surprise.
A relative path is resolved against the declaration's own directory, so a path that looks right
in the document can still resolve somewhere you did not expect.

### Recovering from: component-contract

User code does not have the shape the framework can call: a required method is missing or is not
callable, a signature does not accept the arguments the framework passes, the module fails to
import, or a Model read a `DataRequirement` it never declared.

The contract is checked before the run so that a component fails at registration rather than
halfway through a simulation. Declare every requirement before compute — reading an undeclared
one is refused deliberately, because a requirement that is not declared is not point-in-time
bounded.

The checks on a DataModel's *output rows* scan the whole batch: when rows name instruments that
were never requested, or name one instrument twice, `examples` quotes up to five of the offending
instruments and `example_total` says how many distinct ones there were — so you can tell one stray
name from a systematic fault in one pass, instead of one refusal per offending row. The checks on
a row's *shape* — a missing field, a forged `available_at` — still stop at the first bad row,
which has no content to quote.

### Recovering from: run-precondition

Something a run needs was not in place before it started: a holding with no listing on the
selected Exchange, a holding that cannot be closed, a quantity below a listing minimum or off its
step, a short in a long-only account, an execution input that does not declare a price the
Exchange requires, or a strategy occurrence with no execution instant inside the horizon.

Every one of these is a fact about the declared run rather than about the data. Fix the
declaration — the Exchange listing set, the initial account, the execution input, or the horizon —
and re-run preflight. Preflight exists so these fail in seconds instead of after a long run.

### Recovering from: workspace-state

What is already registered in the workspace conflicts with what is being registered now: an id
bound to a different declaration or a different source, a lookup for something never registered,
or a registration written before a contract the current version requires.

vqapr never silently redefines a registered id, because a later reader would have no way to know
which definition produced an earlier result. Either keep the existing declaration or register the
new one under a new id. When a registration predates a required field, the refusal names the
exact command that repairs it, and repairing one id does not disturb the others.

A workspace can also refuse because another process holds its lock. Registration takes an
exclusive lock so two concurrent writers cannot lose each other's declarations; the refusal means
something else is registering right now, not that anything is corrupt. Wait for the other command
to finish and retry. If nothing else is running, a lock file was left behind by a process that
died, and removing it is safe once you have confirmed no vqapr command is live.

**A strategy record refuses on the same principle, with a different clock and no file to
remove.** `vqapr run` claims each strategy's record with a lock it refreshes as it writes, so a refusal that the id is `held by a
lock inside its heartbeat window` means the lock was touched in the last 120 seconds -- **not**
that the holder is provably alive. The pid in that message is copied out of the lock file, never
interrogated. A run killed by Ctrl-C, a CI timeout or an OOM kill leaves exactly this state, and
inside the window nothing can tell it from a run that is executing.

That lock releases itself 120 seconds after its last refresh, and the refusal states how many
seconds are left; re-running the same command after that reclaims the record with no flag and
no cleanup. Waiting is the answer that is safe under both readings; `vqapr rm strategy
<run-id>/<strategy-id>@<fp8>` clears an abandoned record once its lock has aged out. `--force`
is neither, and against a run that really is live it destroys the rows that run is still
writing.

### Recovering from: publication

A step that writes an artifact refused: the output path already exists, or the workspace file
could not be written back to disk.

vqapr refuses to overwrite a published artifact. One producer owns one output, so a repeated run
to the same result name is a conflict rather than an update — choose a new result name, or remove
the existing artifact deliberately if it is genuinely obsolete.

## CLI reference

Run `vqapr --help` for the full verb list, and `vqapr <command> --help` for each command's
arguments and options. The CLI help text is the authoritative usage reference; this skill does
not duplicate it.

## Friction logging

When something is harder than it should be, write it down **before** resolving it. Record:
- What you were doing
- What you expected
- What actually happened
- How long it took and how you resolved it
- What would have prevented it

This log is the deliverable. The framework improves from honest friction, not from workarounds.
