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

**Goal:** a workspace where every dataset, source, component and execution input is
registered and passes validation.

**Before you author anything, see one run happen.** `vqapr new sample --out ./first-run` writes a
complete journey the product can run as it is: a five-day reversal strategy, a venue, a small
synthetic panel (ten names over three years of real KRX sessions, prices and names made up so it
is not market data) and `sample.yaml`, the one declaration that registers all of it. Then
`vqapr register ./first-run/sample.yaml`, `vqapr check sample-run`, `vqapr run sample-run`,
`vqapr show run sample-run`. The panel is deliberately unbalanced -- one name lists late, one
stops trading early -- so what you see is the shape a real run has. Do not draw a conclusion about
a market from it; do copy its `sample.yaml` when you write your own declaration.

1. `vqapr list datasets` -- see what exists (returns empty on a fresh workspace, that is fine)
2. `vqapr new strategy <id> --dataset <d>` or `vqapr new datamodel <id> --dataset <d>` --
   scaffold a runnable `.py` plus a matching `.yaml`. You can register either one: the YAML with
   `vqapr register <file.yaml>`, or the source directly with `vqapr register strategy <id>
   <file.py>`, which needs no YAML at all.
3. `vqapr register strategy <id> <file.py>` -- register it by naming the kind, the id and the
   file. The file must define exactly one `StrategyModel` subclass; zero and two are both
   refused, and the refusal says which. **One strategy is one file.** Re-registering an edited
   file keeps the id and records a new fingerprint, and a reader of the run record sees that as
   *tuning* the same strategy. A variant you do not mean as a tuning -- another arm of a
   methodology, a different signal, even the same class with one constant changed -- is a new
   file under a new id. There is no config channel; which of the two you mean is your call.
4. `vqapr new dataset --out d.yaml` -- get a dataset template with every required key
5. `vqapr new execution-input --out ei.yaml` -- get a venue-table template
6. `vqapr new exchange <id> --instruments A005930 A000660 --out venue.py` -- get a runnable
   Exchange plus the declaration that registers it. **Every instrument the run trades needs a
   listing here**, or preflight refuses it by name. `AcademicExchange` and `KrxExchange` are the
   only two profiles a registered Exchange may be; the scaffold uses the first.
7. Fill in the placeholders and `vqapr register <declaration.yaml>` for each. Datasets, sources
   and execution inputs stay in YAML because they ARE declarations -- there is no code to
   point at. There is no agenda to declare: the run itself says which sessions it fires on
   and at what wall time (rung 2).
8. `vqapr list <kind>` -- confirm what was registered, and `vqapr show model <id>` to see what a
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
with one of two verbs, in every role. `inputs()` is evaluated at registration and at preflight,
BEFORE any memory is restored and before a run's `initial_model_memory` is applied, so what a
model reads cannot depend on either: a family of settings that changes the reads is a family of
registered components, one file and one id each.

- **`read(alias, field)` on a panel grain** (`instrument_instant`, `instant`) returns a
  **`PanelWindow`**: `instants` (the same for every name) x `instruments`; `values[name]` is
  that name's values over the instants, `None` where it had none; **`current()` is the
  cross-section at the last instant** -- a name with no row there is absent, not carried forward;
  `latest()` is the newest value per name anywhere in the window, however old. On a sparse table
  (a name has a row only on sessions it is eligible) a decision wants `current()`: `latest()`
  silently trades an ineligible name on a stale value. It is a slice of a panel the run built
  once, not a query.
- **`rows(alias)` on `grain: rows`** (the vendor's long table) returns a **tuple of
  `Observation`s**, one per (instant, instrument), each carrying `instrument_id`, its own
  `available_at` and `values`; names interleave within an instant.
- Each verb refuses the other grain by name. **A value arrives as the type the dataset
  declared** in `field_types`: a `DOUBLE` field is a `float`, an `INTEGER` an `int`, a
  `VARCHAR` a `str`, a `TIMESTAMP_TZ` an aware `datetime`. Registration compared that
  declaration with the file once, and a DECIMAL column was refused there, so `Decimal` never
  arrives from a dataset. Where you want exact arithmetic on a price, cross once with
  `Decimal(str(value))` -- never `Decimal(value)`, which inherits a float's binary expansion.
- **What `compute()` returns is typed by its first session, and must be a declarable type.**
  The output dataset's `field_types` are read off the first non-empty session's rows and
  registered as the declaration; every later session must fit that schema, and nothing is cast.
  Return `float` for a continuous quantity and `int` for a count. A `Decimal` value field is
  refused at the first session (`datamodel.output.field_type`), because a dataset carries one
  numeric type per field and DECIMAL is not one a dataset may declare. A later session whose
  rows do not fit the first session's schema is refused with `datamodel.output.schema_mismatch`,
  which quotes pyarrow and the established schema and does not guess further.

**Choose the lookback member deliberately; they are a pair.** `RowsLookback(rows=N)` gives each name
its **own** last N observations, so on an unbalanced panel the batch's calendar span is set by the
sparsest name and is unbounded above: a real 1,637-name universe asking for 313 rows got rows
spanning 1,865 sessions, back eight years. That is right for a per-name question -- a trailing
return, a moving average -- and silently wrong for a cross-sectional one, where a correlation matrix
would mix a live name's recent returns with a delisted name's decade-old ones and pass every check.
`CalendarLookback(days=N, timezone=...)` gives every name the same window and is the member a
covariance matrix, a factor regression or any date-aligned model wants. Scaffold the first with
`vqapr new datamodel --lookback N` and the second with `--calendar-lookback DAYS`.

A datamodel is run as a registered run, exactly like a strategy (record 148): a `runs:` entry
whose `datamodels:` names the component and the dataset it writes, on the sessions and at the wall
time the run declares. No account, no venue, no execution input -- those keys are refused on a
datamodel run. `vqapr new datamodel <id> --dataset <d>` emits the block beside the component:

```yaml
runs:
  my-derived-run:
    instruments: [A005930, A000660]  # the universe every session computes over
    start: "2024-01-02T00:00:00+09:00"
    end:   "2024-12-31T23:00:00+09:00"
    sessions_from: prices            # every session that registered dataset has (or `sessions:`)
    timezone: Asia/Seoul
    at: "16:00"                      # when compute() is called, each session
    datamodels:
      my-derived:                    # the registered DataModel component
        dataset_id: my-derived-values  # must NOT already be registered
        value_fields: [value]          # the columns each row carries beside `instrument`
```

Then `vqapr register <file.yaml>`, `vqapr check <run-id>` and `vqapr run <run-id>` by id -- the
same three commands a strategy run takes; a YAML path handed to `run` or `check` is refused by
name. The sessions' rows land as one parquet file under `.vqapr/materialized/<dataset_id>/` when
the last session completes, the dataset registers right after, and the run's
record lands under `.vqapr/runs/<run-id>/datamodels/<id>@<fp8>/datamodel.json` -- one line per
session (evaluation time, output `available_at`, row count), no per-instrument lineage.
`vqapr list datasets` shows the dataset arrived, `vqapr list datamodels --run <run-id>` and
`vqapr show datamodel <run-id>/<id>@<fp8>` read the record, and `vqapr show dataset <id>` reads
back what it computed. The output is readable by any component that declares it -- which is the
point: one model's output is the next model's input. Running the same run again is refused while
its output dataset is registered (`datamodel.output_registered`, 409); `vqapr rm dataset <id>`
withdraws the registration and deletes the files under `.vqapr/materialized/<id>/`, and is the
way to retry a datamodel run or to drop a throw-away output. It refuses while a registered run
takes its sessions from that dataset (`sessions_from`), naming the run; a dataset you registered
from your own path is withdrawn without touching your file.

**`vqapr show dataset <id> [--limit N]`** works for any registered dataset, not just a
materialized one. It reports the registration's own facts — source, path, declared fields, span —
alongside the rows, and reports `rows_total` separately from `returned` so a truncated page never
reads as a short dataset. `--limit 0` returns every row.

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
table, strategy_ref)`.** `store_root` is the path the run's result printed under that name --
`<project>/.vqapr` unless `--store-root` moved it -- and NOT the project directory;
`strategy_ref` is the `record` the result printed (`<strategy-id>@<fp8>`), or the bare
`<strategy-id>` when one record of it exists, or omitted when the run holds one strategy. A root,
run id or ref that names no record is refused (`RunRecordMissing`) naming what was found
instead, so an empty frame means an empty table and nothing else. The rows are parquet on
disk, one directory per table and one file per table
(`.vqapr/runs/<run-id>/strategies/<strategy-id>@<fp8>/tables/<table>/all.parquet`), so
`duckdb.read_parquet` on that directory reads them too: an instant is a `TIMESTAMPTZ` and comes
back as the same instant, and a `Decimal` is exact text (the column's metadata marks it) that
`read_strategy_table` restores and you cast yourself anywhere else.
`read_strategy_table` decodes by the column types the writer recorded beside the table, so
`nav` comes back a `Decimal` and `observed_at` an aware `datetime`. Rows stay in memory while
the run executes and land once, when it ends -- normally, or through an exception or Ctrl+C,
which keep every row recorded up to then beside no record. Only a hard kill (`taskkill /F`, an
OOM kill) loses rows, and then only what came after the last spill (a part written when the
buffer passes 256 MB). A long run can still be watched -- `vqapr list strategies --run
<run-id>` lists a strategy that has no record yet with `status: running`, its `chunks` (accepted
sessions so far) and its `last_event_time`, from a progress file the run rewrites every few
seconds; see "Watching a long run" below.

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

A run whose strategy declared constraints records a fourth:

- **`vqapr.monitoring`** -- what each declared constraint measured on the committed account
  right after each commit. `constraint` (the rule's id), `passed` (the author's own comparison),
  `measured`, `bound`, `excess`, `verdict` (the framework's: `held`, `within_tolerance` or
  `breached`), `tolerance` (what the excess was judged against), `offenders` (the breaching
  instrument ids, space-separated; empty when none), `account_version`. `event_time` is the fill
  instant the book was committed and judged at. **This is the table compliance questions are asked
  of** -- the strategy record's `contract` block only counts (`held` / `within_tolerance` /
  `breached` of `checked`, with the worst excess of each); which name breached which limit by how
  much is here, one row per constraint per commit.

Every row of every table also carries the same five envelope fields: `run_id`, `producer_id`,
`stage`, `event_time` and `sequence` -- which run wrote it, what wrote it, at what point, when the
fact happened, and in what order. A table cannot declare one of these as a column of its own.

A fill's `kind` is what the ROSTER said. What it was CHARGED as comes from the venue's own terms.
Those are two statements and nothing compares them (`docs/issues/013`), so keep a venue's declared
categories in step with the registered roster.

**A run needs four declarations**: a dataset, an execution input, an exchange, and at least one
component. Each has a `vqapr new` scaffold; if you are hand-writing one of them, check for the
template first.

**And it wants a sixth: the instrument roster.** `vqapr new instruments` scaffolds the exporter and
its declaration. It is not in the five because a run without one still completes -- but every fill
then records `kind: None`, the report's cost by kind collapses to one `unknown` bucket, and on a costed
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
it is recorded, and `show strategy` reports it under `contract`. **Compare strictly; the
framework applies the tolerance.** A book executes in whole lots and is marked after its fills,
so the realised weight lands a little off the target -- the framework judges every finding's
`excess` against `max(bound * 1%, 10bp of NAV)` once, in one place, and files it as `held`,
`within_tolerance` or `breached`; only `breached` makes the contract `ok: false`, and the counts
of all three are reported so nothing is hidden. Override the line with a `tolerance` property on
your Constraint returning a `Decimal` share of NAV (`None`, the default, keeps the framework's).

**Stop condition:** `register` accepted every declaration without failures, and each kind you
registered lists what you expect. `list` takes exactly one kind per call and `kind` is a required
positional -- there is no all-kinds form, and bare `vqapr list` is refused with
`usage.rejected` -- so checking a Rung 1 setup is one call per kind:

```
vqapr list datasets
vqapr list sources
vqapr list components
vqapr list execution-inputs
vqapr list instruments
```

The remaining three kinds are `runs`, `strategies` and `datamodels`, all Rung 2: `vqapr list runs` is the registered runs and the records
beside each, `vqapr list strategies --run <run-id>` and `vqapr list datamodels --run <run-id>` those records. A kind you registered nothing
under returns `count: 0`, which is an answer rather than a failure.

#### Correcting a registration during setup

Registrations are identities: one id means one declaration, and editing a COMPONENT you already
registered is the ordinary loop: change the file and run the same `vqapr register <kind> <id>
<file.py>` again. It replaces the
registration in place, with no flag -- there is no `register --force`; the only `--force` the CLI
has belongs to `vqapr run`, where it replaces a run RECORD. **A `runs:` declaration is the
exception:** a run definition is the provenance of a result, so re-registering the same `run_id`
with a changed body is refused (`run.registered`, 409). To edit one during setup,
withdraw it first -- `vqapr rm run-definition <run-id>` -- and register the edited declaration
again; its records, if any, stay readable. The success payload then carries
`replaced: {fingerprint: <the old one>}`, and is silent about it when the id was new or the bytes
unchanged. The id stays, the runs that name it keep working, and the next run's record carries a
new `source_digest` for whatever ran.

That digest is the provenance, and it is a **receipt rather than a gate**: it records what ran, and
nothing re-checks it afterwards. Two runs of edited code carry two different digests, which is what
makes an edit visible in the record. A run that already pinned the old fingerprint is unaffected:
its record testifies to what it used.

- **Editing a component you registered:** change the file and re-register. No new id, no flag,
  no run edit.
- **Withdrawing one:** `vqapr rm <kind> <id>` refuses while a registered run still names it, and
  names which run does.
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

### Rung 2 — Run

**Goal:** a completed run that produces a result per model: a record and tables per strategy, or
a registered dataset per datamodel.

A run is configuration, registered like everything else: the universe, the period, the
sessions it fires on (`sessions_from: <dataset>` or a `sessions:` list) and the venue-local
wall time it fires at (`timezone`, `at`), the venue, the execution input, the initial account
declaration, and the strategies it tries. Every strategy is called on EVERY session at `at`
and decides for itself whether to act -- a monthly rebalance is a rule inside the strategy,
read from `call.evaluation_time` and kept in `self.memory`. The book is valued at the instant
the venue fills and the declared constraints judge it right after each commit; there is no
valuation or monitoring time to declare. Each strategy runs with its OWN account from that
declaration and writes its own record. Three factor models on one cadence are one run with
three strategies, not three runs.

1. `vqapr new run --out runs.yaml` — get a `runs:` declaration template with every required
   key explained
2. Fill in the template with registered component ids, instruments, dates, the sessions and
   the wall time; list every strategy to try under `strategies:`
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
returns `ok:true` with a `strategies` map carrying `status: completed`, an `occurrences` count,
an `account_version` and a `record` (`<strategy-id>@<fp8>`) per strategy -- or, for a datamodel
run, a `datamodels` map carrying `dataset_id`, `rows`, `sessions` and its `record`.

**When one strategy fails, the others still run.** Each strategy is its own flow with its own
account, so a refusal inside one -- your `decide()` raised, or the `Rebalance` it returned was
outside its budget -- is that strategy's outcome, not the run's. The envelope is then `ok:false`
with `stage: run.strategy_failed` and the SAME `strategies` map: `status: completed` lines as
above beside `status: failed` lines that carry that strategy's refusal (`stage`, `component_id`,
`failures`, `at`). The top-level `failures` gathers every failed strategy's entries, each stamped
`strategy: <id>`; read `fix` first, as always, and `source` names the strategy
(`key_path: strategies.<id>`) and, for a raise from your own file, the file and the line. The
completed records stand. Fix the failed strategy, register the file again, and
`vqapr run <run-id> --strategy <id>` runs it alone into a new record beside them. The shape is
the same under `--jobs N`.

**Watching a long run.** A strategy's record (`strategy.json`) is written last, so until then
`vqapr list strategies --run <run-id>` lists it with `status: running`, `chunks` (accepted
sessions so far), `last_event_time` (the last session it accepted) and `lock.refreshed_ago`
(seconds since the run last touched its lock); the first two come from a progress file the run
rewrites every few seconds, so they can lag that much. A directory whose lock has gone quiet for two
minutes and still has no record is `status: unfinished`: the strategy was killed, or its flow
ended in a refusal -- the run's own envelope says which. `vqapr show strategy` reads finished
records only.

**Registering a run's table as a dataset.** A strategy's record streams every table it
writes -- the package's `vqapr.weight`, `vqapr.account`, `vqapr.fill`, `vqapr.monitoring`, and
any table the strategy declared with `tables()` -- as a parquet directory under
`.vqapr/runs/<run-id>/strategies/<strategy-id>@<fp8>/tables/<table>/`. That directory registers
like any other source, so one run's decisions are the next run's input (a member run feeding an
ensemble) with no publishing step in between:

```yaml
datasets:
  reversal_allocation:
    source_id: reversal-weights
    path: .vqapr/runs/reversal/strategies/reversal@1a2b3c4d/tables/vqapr.weight
    instrument_field: instrument
    available_at: event_time        # the decision instant the row was written at
    grain: instrument_instant
    key_fields: [event_time, instrument]
    fields:
      weight: "CAST(weight AS DOUBLE)"   # a record stores Decimals as text
    field_types:
      weight: DOUBLE
```

`vqapr list strategies --run <run-id>` gives the `<strategy-id>@<fp8>`; `available_at` is
`event_time` for every package table (a valuation writes `observed_at` and `event_time` at the
same instant). A `Decimal` column is stored as text with `vqapr.type: decimal` metadata, so a
numeric field is `CAST` in the registration -- to `DOUBLE`, the one non-integer numeric type a
dataset may declare; a weight on the optimiser's `1e-12` grid is at most twelve significant
digits and a float64 carries fifteen. The run's own `run.json` carries the sha256 of every source
it read, which is the provenance a later reader wants.

**Tweaks are records, not directories.** A strategy's record is named by its registered
fingerprint, which folds the file bytes and the config: edit the strategy and re-register it under
the same id, run again, and the new record lands BESIDE the old one. **Count records**: the rows
`vqapr list strategies --run <run-id>` (or `list datamodels --run`) reports with
`status: completed` are how many times it was tweaked. Counting directories over-counts by the
crashes: a run killed or refused inside a callback leaves a directory with rows and no record,
which `list` shows as `status: unfinished` and which `vqapr rm strategy|datamodel <run-id>/<ref>`
removes. Running the same fingerprint again is refused unless `--force` replaces that one record;
`vqapr rm strategy <run-id>/<strategy-id>@<fp8>` and `vqapr rm run <run-id> [--keep-latest]`
remove records, and both refuse while a writer may still hold the record.

**Removing a run entirely: `vqapr rm run <run-id> --cascade`.** One gesture removes its records,
its registered definition, the materialized datasets its datamodels wrote, and the components it
named -- keeping, and naming as `kept`, any dataset or component another registered run still
names. The single-kind verbs still exist for the step-by-step case, `vqapr list runs` keeps
showing a run whose definition was withdrawn but whose records remain (`status: orphaned`), and
`rm run-definition` reports the records it left and the verb that removes them.

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

State that will not fit strict JSON goes through `save_payload`/`load_payload`, and preflight
proves the pair **before the first callback**: it calls `save_payload` on a fresh instance,
`load_payload` on a second fresh instance with those bytes, then `save_payload` again, and the two
byte strings must match. So `save_payload` must be deterministic (no timestamp, no `id()`, no
unordered set iteration), and `load_payload` must accept an **empty** source -- the default
`save_payload` writes nothing, so a bare `pickle.load(source)` refuses the run with `EOFError`.
The refusal names which of the three steps failed and carries the original exception.

`Rebalance.of` takes **relative** conviction. `long={"A": 2, "B": 1}` means A is liked twice as
much as B; normalising, rounding onto the canonical grid and balancing against cash is the
package's arithmetic, not yours. You never make weights sum to one by hand.

A short is declared by **which mapping** a name appears in, never by a negative number:
`short={"A": 2}` means twice as short. Passing both sides makes the book signed automatically.

`of` splits `invested` **evenly** between the two sides, so it tops out at half a textbook
$1-long/$1-short book and cannot say "more shorts than longs". When the signal decides the split,
use `Rebalance.signed(weights, gross=1)` instead: weights are **signed** there (a negative number
IS the short), `gross` is the sum of absolute weights, and the long/short ratio comes out exactly
as the signal produced it. `gross=2` is the textbook $1/$1 book. Cash is the net residual either
way, so a dollar-neutral book has cash 1.

```python
return va.Rebalance.signed({"A": 0.8, "B": 0.2, "C": -1.0})   # 0.5 long, 0.5 short
```

Return `Hold(reason="...")` to decline. The reason is prose a human reads -- spaces are fine,
and only an empty string is refused.

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

**Start from the report, not from the tables.** `strategy_report` and `run_report` in
`vqapr.public` read a finished record back and compute, once, what a paper's tables need:

```python
from decimal import Decimal
from pathlib import Path
from vqapr.public import run_report, strategy_report

store = Path(".vqapr")                       # the `store_root` `vqapr run` printed
one = strategy_report(store, "reversal")     # the run's only strategy, or name "<id>" / "<id>@<fp8>"
every = run_report(store, "ff-arm", benchmark="bm-book", risk_free_annual=Decimal("0.03"))
one.as_record()                              # JSON-ready: Decimal as text, instants with offset
```

A `StrategyReport` has six sections, each a pydantic document, each `None` with a reason in
`omitted` when the record cannot give it:

- **`performance`** — NAV, period returns and drawdown as series (`instants` beside `values`);
  total and annualised return, volatility, Sharpe, Sortino, Calmar, max drawdown and when,
  positive-period share; `by_year` and `by_month`. `periods_per_year` is inferred from the
  valuation grid and says so (`inferred`); pass it to override. Sharpe is against
  `risk_free_annual`, zero unless you give one -- the record holds no rate.
- **`book`** — held / long / short counts and gross, net, long, short exposure, cash share, max
  weight and HHI, per valuation, from the marked positions.
- **`attribution`** — P&L per period by name and by side (long / short), and `residual`: the part
  of the NAV change no marked name explains. Zero when every held name was marked; a non-zero
  residual is a finding, not noise. `position_hit_rate` is the share of name-periods with a
  positive P&L.
- **`trading`** — one-way realised turnover (from fills) beside one-way intended turnover (from
  weights); costs summed from `vqapr.fill` (commission, tax, basis points of notional, share of
  mean NAV per year, by roster kind); `fills` (the same summary `vqapr run` prints, including
  `never_filled`); holding periods.
- **`intent`** — each decision's weights against the book at the first valuation after it:
  `gap` (Σ |realised − intended|) and `weight_sign_hit_rate`.
- **`compliance`** — per constraint: `checked` split into `held` / `within_tolerance` /
  `breached` / `unmeasured`, the worst excess and when, the offending names by count.

A `RunReport` holds every strategy's report plus `headline` (one row per strategy), the
`correlation` of period returns on the instants all strategies share, and `relative` (active
return, tracking error, information ratio) against the `benchmark` strategy you name -- a
benchmark must be a book of the same run, because an index level is not in the record.

**Three hit rates, three names.** `positive_period_share`, `position_hit_rate` and
`weight_sign_hit_rate` measure different things; do not report any of them as "hit ratio"
without saying which.

#### Reporting: tables and figures for a paper

The package computes the values and stops there; **it ships no plotting library and no
renderer**, on purpose (PRD UC-REPORT-001). Render in the project with whatever the project
already uses -- `pandas` + `matplotlib` is the usual pair; add them to the project, never to
vqapr. Every series in the document is `instants` beside `values`, so
`pd.Series(s.values, index=pd.DatetimeIndex(s.instants)).astype(float)` is the whole bridge.

What a paper expects, and where it comes from:

- **Table 1, the headline.** One row per strategy: annualised return, volatility, Sharpe, max
  drawdown, turnover, cost, breaches. `run_report(...).headline`. Round for the table only;
  keep the document's exact text for the appendix or the replication package.
- **Table 2, by year.** `performance.by_year` per strategy: total return, volatility, Sharpe, max
  drawdown. Add `relative` columns when a benchmark book is in the run.
- **Figure 1, cumulative return with drawdown beneath.** `performance.nav` normalised to 1 (or
  cumulative `returns`), one line per strategy, `performance.drawdown` as a filled area below on a
  shared x axis.
- **Figure 2, the book over time.** `book.gross_exposure`, `net_exposure`, `held` -- three small
  panels, one x axis.
- **Figure 3, correlation.** `run_report(...).correlation.values` as a heat map with the value
  printed in each cell.
- **Table 3, execution.** `trading.costs`, `trading.fills`, `intent.mean_gap`,
  `annualized_realized_turnover` beside `annualized_intended_turnover` -- the second pair is the
  size of what did not execute.
- **Table 4, compliance.** `compliance.constraints`: checked / held / within tolerance / breached,
  worst excess, top offenders.

House style for a paper figure: serif or the journal's font; one column ≈ 3.3 in wide, two
columns ≈ 7 in; 300 dpi PNG for review, PDF for submission; no top and right spines; a light
horizontal grid only; a legend inside the axes or a caption; colour that survives greyscale
(vary line style, not only hue); the zero line drawn. Label axes with units (`%`, `× NAV/yr`).
State in the caption what `periods_per_year` and `risk_free_annual` were, because the
document carries them and a reader will ask.

## Reading vqapr's output

Every vqapr command returns exactly one line of JSON to stdout. The shape is always:

```json
{"ok": true, "stage": "...", ...}
```
or
```json
{"ok": false, "stage": "...", "mutation": false, "retry_precondition": null,
 "correlation_id": "...", "failures": [...]}
```

**`ok`** — did the command succeed?
**`stage`** — which operation was under way when the command stopped (the closed set is listed
below)
**`mutation`** — whether anything was written before the refusal; `retry_precondition` says what
must hold before retrying when it was
**`correlation_id`** — quote it when you report the refusal anywhere
**`error`** — the exception as one line, `Type: message`; the whole traceback is in each
failure's `cause`. When a `detail` key is present it names a diagnostics file holding the same
traceback, written beside the workspace as a convenience, never as a substitute
**`failures`** — an array of structured diagnostics, **one entry per unmet requirement**: vqapr
collects every failure of an operation before refusing, so fix them all in one pass. Every entry
carries exactly these keys, in this order: `code`, `status`, `source`, `requirement`, `observed`,
`fix`, `cause`, `examples`, `example_total`. All nine are always present, including on a `usage`
refusal from the argument parser; `source`'s three fields (`file`, `key_path`, `line`) and
`observed` may be `null`, `examples` **may be empty**, and `fix` is always a sentence you can act
on.

When `ok` is false, read `fix` first. It is the sentence that fixes *this* occurrence, written as
an action you can take. `requirement` says what was needed and `observed` says what was found;
`source` says where — it is an object with `file`, `key_path` and `line`, any of which may be
`null` when the failure does not have that kind of location. Read `source` as structure, never by
parsing a formatted string out of the other fields.

Beyond `fix`, an agent branches on three things, in this order:

1. **`status` — who must act.** A closed set with HTTP's numbers, on purpose: you already know
   what 404 and 409 mean. **4xx: your submission is wrong** — a declaration, an argument, a data
   file, a precondition — and retrying without changing it is pointless. **5xx: your submission
   is fine; something that ran failed** — your own code (502), the framework (500), or the
   machine (503). Branch on `status` before you branch on `code`. `code` names the specific
   situation (`dataset.field_missing`, `workspace.locked`) and the set of codes is open in beta;
   **a `code` you do not recognise is handled as its `status`**, the way an HTTP client treats an
   unknown 4xx as 400. Each status has a "Recovering from" section below.
2. **`stage` — which operation was under way.** One of: `usage` (the command line itself),
   `open` (opening the workspace), `read` (reading a source, roster or record file), `register`
   (proving and writing a declaration), `lookup` (resolving a reference), `remove`, `write`
   (writing the workspace document), `load` (importing and constructing your component), `check`
   (the judgments `vqapr check` makes and `vqapr run` repeats), `freeze` (freezing a run's
   authority before it executes), `run` (executing: callbacks, fills, valuations, datamodel
   computations), `record` (writing a record or a datamodel's dataset). The same `code` can be
   raised at more than one stage — `datamodel.output_registered` at `check` and at `freeze` — and
   the stage tells you how far the command got.
3. **`cause` — what actually happened, whole.** An object with `type`, `message`, `where`,
   `origin` and `traceback`. When an exception was involved, `type`/`message`/`traceback` are the
   exception as Python would print it, **never truncated**; when the framework refused
   deliberately without one, those three are `null`. `where` is always set: the innermost frame
   that is not the interpreter's, as `file:line (function)`. `origin` says whose frame that is:
   `"user"` for a file outside the vqapr package, `"framework"` for one inside it. The
   classification above is not guaranteed to be MECE in beta, so `cause` is how you decide
   *correctly* after `status` let you decide *quickly*. Two readings matter most: **`origin:
   "user"` with status 502 means your own code raised** — go to `where`, it is your line; and
   **`origin: "framework"` with status 500 means the framework failed** — that is not yours to
   fix, so file an issue upstream and quote `cause` whole, traceback included.

**`examples` is empty for structural checks, and that is not a bug.** A check on a column's
*type* has no offending row to quote, so it reports `"examples": [], "example_total": 0`. A check
on row *contents* — a duplicated key, a null in a key field — quotes up to five offending values
and `example_total` says how many there were before truncation. An empty `examples` next to a
non-zero `example_total` never happens; if you see one, that is worth reporting.

Fix the inputs and retry.

## Recovering from a refusal

Every refusal carries a `status`, and there are nine. Each names one of the sections below.
`fix` tells you what to do about the single failure in front of you; these sections tell you what
the status means, which codes you will typically see under it, and the recovery move for the
whole class. When several failures arrive together, the error's own status is the most severe
among them (5xx before 4xx), but each entry carries its own — read them one by one.

### Recovering from: 400 invalid

The shape of what you handed in does not meet the contract: a declaration key, a command-line
argument, a parquet schema. Nothing ran on it; nothing could.

Typical codes: `declaration.key_missing`, `declaration.key_unknown`,
`declaration.unknown_section`, `declaration.value_invalid`, `declaration.value_not_permitted`,
`declaration.grain_undeclared`, `declaration.run_invalid`; `dataset.field_missing`,
`dataset.key_duplicate`, `dataset.key_null`, `dataset.available_at_not_tz`,
`dataset.available_at_not_a_timestamp`, `dataset.field_not_tz`, `dataset.field_not_portable`,
`dataset.projection_unbindable`, `dataset.span_absent`, `dataset.span_empty`,
`dataset.value_not_finite`; `execution_input.field_type`, `execution_input.price_type`,
`execution_input.price_invalid`, `execution_input.key_duplicate`, `execution_input.key_null`;
`argument.not_a_mapping`, `argument.keys_missing`, `argument.value_invalid`, `usage.rejected`;
`workspace.invalid`, `dataset.reference_invalid`, `component.reference_invalid`,
`run.reference_invalid`, `remove.unsupported_kind`.

**A declaration document** (`declaration.*`, stage `register`): vqapr never guesses a missing key
and never coerces a value. Read `source.key_path`: it names the exact position in the document, so
you can go straight there rather than re-reading the file. `observed` shows what was found at
that position. When a value must come from a fixed set, the `requirement` lists that set. Generate
a fresh template with `vqapr new` when a document has drifted far from the contract; editing a
correct template is faster than repairing a wrong one.

**A data file** (`dataset.*`, `execution_input.*`, stage `register`): the declaration is
well-formed but the parquet behind it does not satisfy what registration requires — a declared
column is absent, the logical key is not unique or contains nulls, `available_at` is not
timezone-aware, a field's column is not the type `field_types` declares for it
(`dataset.field_type_mismatch` quotes both; a DECIMAL column is `dataset.field_decimal` and is
cast to DOUBLE while preparing), or the dataset carries no dated row at all. These are all fixed
while *preparing* the source, not while registering it. vqapr deliberately does not convert a
naive timestamp for you: only you know which instant a value means, and a wrong localisation is
a silent point-in-time leak rather than an error. Localize at the instant the row became knowable
— a daily close is knowable at that session's close in the venue's timezone, not at midnight. For
key failures, `examples` quotes up to five offending values and `example_total` says how many
there were, so you can tell a typo from a systematic duplicate.

**A command line** (`usage.rejected`, `argument.*`, stage `usage`): the parser refused before any
package concept was involved; `fix` carries the whole answer, and `vqapr <command> --help` the
rest.

### Recovering from: 404 missing

A name was given and nothing registered answers to it, or the path it names is not there.

Typical codes: `workspace.missing` (no workspace at the root you pointed at), `source.path_missing`
and `argument.file_missing` (a path that does not exist), `dataset.unregistered`,
`source.unregistered`, `component.unregistered`, `execution_input.unregistered`,
`run.unregistered` (a run id the workspace does not hold),
`field.absent`, `universe.absent`, `store.field_missing` (a field a component asked for that the
dataset does not carry), `execution.missing`, `execution.requirement_missing` (a run that names an
execution input, or a price on one, that was never declared).

Check `source.file` first when the refusal is about a path — it is the path vqapr actually
resolved, which is often the surprise. A relative path is resolved against the declaration's own
directory, so a path that looks right in the document can still resolve somewhere you did not
expect. When the refusal is about an id, `vqapr list <kind>` shows what the workspace holds under
that kind; register the missing declaration, or correct the reference to one that exists. A
missing field is fixed in the dataset declaration's `fields` — the requirement names the field and
the dataset it was expected in.

### Recovering from: 409 conflict

What is being registered or removed disagrees with what the workspace already holds.

Typical codes: `dataset.registered`, `execution_input.registered`, `run.registered` (the id is
bound to a different declaration), `dataset.source_conflict`, `execution_input.source_conflict`,
`dataset.source_mismatch` (the same id, a different source), `datamodel.output_registered` (a
datamodel run whose output dataset is already there), `remove.referenced` (something still
depends on what you are removing), `constraint.identity_mismatch`, `argument.file_exists` (an
output path that already exists).

vqapr never silently redefines a registered id, because a later reader would have no way to know
which definition produced an earlier result. Either keep the existing declaration or register the
new one under a new id. A `runs:` declaration is the one that refuses on a changed body — withdraw
it with `vqapr rm run-definition <run-id>` and register the edited one. A datamodel's output is
withdrawn with `vqapr rm dataset <id>` before the run is repeated. vqapr refuses to overwrite a
published artifact for the same reason: one producer owns one output, so a repeated run to the
same result name is a conflict rather than an update — choose a new name, or remove the existing
artifact deliberately if it is genuinely obsolete. `remove.referenced` names the dependant; remove
it first, or leave both.

### Recovering from: 412 precondition

The declaration is well-formed and everything it names exists, but a condition of running it does
not hold. This is what `vqapr check` is for, and `vqapr run` makes the same judgments before it
starts.

Typical codes: `lookback.uncovered`, `period.uncovered` (a lookback or a run period reaching
before the data starts or past where it ends), `execution.not_after_decision` (an execution
instant at or before its decision), `weights.mode_conflict`, `weights.venue_conflict`;
at stage `freeze`: `account.mode` (a short in a long-only account), `account.unlisted_holding`,
`account.holding_not_closable`, `account.minimum_quantity`, `account.quantity_step`,
`account.fractional_quantity`, `universe.unlisted_instrument`, `universe.untradable_listing`,
`execution.target_outside_horizon` (a strategy occurrence with no execution instant inside the
horizon).

Every one of these is a fact about the declared run rather than about the data. Fix the
declaration — the sessions and times, the lookback, the Exchange listing set, the initial account,
the execution input, or the horizon — and run `vqapr check` again. Preflight exists so these fail
in seconds instead of after a long run.

### Recovering from: 422 contract

Your code is not something the framework can call, or what it returned is not something the
framework can use. Distinct from 502: nothing of yours crashed; it has the wrong shape.

Typical codes: `component.method_missing`, `component.method_not_callable`,
`component.signature_invalid`, `component.wrong_type`, `component.module_invalid`,
`component.requirements_missing`, `component.requirements_invalid`,
`component.execution_profile_invalid`, `component.constraint_id_mismatch` (a Constraint registered
under an id its own `constraint_id` does not return); `requirement.undeclared` (a Model read a
`DataRequirement` it never declared); `datamodel.output.schema_mismatch`,
`datamodel.output.empty`, `datamodel.output.fields_invalid`, `datamodel.output.rows_invalid`,
`datamodel.output.instrument_invalid`, `datamodel.output.instrument_duplicate`,
`datamodel.output.instrument_unrequested`, `datamodel.output.available_at_owned`.

The contract is checked before the run so that a component fails at registration rather than
halfway through a simulation. Declare every requirement before compute — reading an undeclared
one is refused deliberately, because a requirement that is not declared is not point-in-time
bounded. `cause.where` names the framework line that judged the shape; `requirement` names the
method or signature it expected, and `vqapr.public`'s base classes are the authority on both.

The checks on a DataModel's *output rows* scan the whole batch: when rows name instruments that
were never requested, or name one instrument twice, `examples` quotes up to five of the offending
instruments and `example_total` says how many distinct ones there were — so you can tell one stray
name from a systematic fault in one pass, instead of one refusal per offending row. The checks on
a row's *shape* — a missing field, a forged `available_at` — still stop at the first bad row,
which has no content to quote.

### Recovering from: 423 locked

Another process holds it: the workspace document, or a live strategy record. Nothing is corrupt,
and nothing about your submission is wrong.

Typical codes: `workspace.locked` (stage `write`), `record.live` (stage `record`).

**The workspace** takes an exclusive lock so two concurrent writers cannot lose each other's
declarations; the refusal means something else is registering right now. Wait for the other
command to finish and retry. If nothing else is running, a lock file was left behind by a process
that died, and removing it is safe once you have confirmed no vqapr command is live.

**A strategy record refuses on the same principle, with a different clock and no file to
remove.** `vqapr run` claims each strategy's record with a lock it refreshes as it writes, so a
refusal that the id is `held by a lock inside its heartbeat window` means the lock was touched in
the last 120 seconds -- **not** that the holder is provably alive. The pid in that message is
copied out of the lock file, never interrogated. A run killed by Ctrl-C, a CI timeout or an OOM
kill leaves exactly this state, and inside the window nothing can tell it from a run that is
executing.

That lock releases itself 120 seconds after its last refresh, and the refusal states how many
seconds are left; re-running the same command after that reclaims the record with no flag and
no cleanup. Waiting is the answer that is safe under both readings; `vqapr rm strategy
<run-id>/<strategy-id>@<fp8>` clears an abandoned record once its lock has aged out. `--force`
is neither, and against a run that really is live it destroys the rows that run is still
writing.

### Recovering from: 500 internal

The framework itself failed. Your submission is not at fault, and there is nothing in it to fix.

Typical codes: `unhandled` (an exception nobody classified, whose innermost non-interpreter frame
is under the vqapr package); `judgment.blocked` and `preflight.refused` when their `cause.origin`
is `"framework"`.

Do not retry the same command hoping for a different answer, and do not work around it by changing
a declaration that was correct. File an issue upstream and quote `cause` whole — `type`, `message`,
`where` and the full `traceback` — together with the command that produced it and the
`correlation_id`. `cause.where` is the framework line that raised, which is exactly what the
maintainer needs. If the same failure appears with `origin: "user"` instead, it is a 502 and the
section below applies: the classification is read from the traceback, not from the code.

### Recovering from: 502 crashed

Your own code raised while the framework was running it — the gateway's upstream failed.
`cause.where` names your line.

Typical codes: `component.import_failed` (your module raised on import), 
`component.construction_failed` (your class raised in `__init__`), `component.requirements_failed`
(your `requirements()` raised), `datamodel.compute_failed` (your `compute` raised),
`strategy.<stage>` — `strategy.callback.intent`, `strategy.callback.no_decision` and the other
simulation stages — when a strategy callback raised, and `unhandled` when the innermost frame of
an unclassified exception is a file of yours; `judgment.blocked` and `preflight.refused` when
their `cause.origin` is `"user"`.

Read `cause.traceback` from the bottom: the innermost frame that is not the interpreter's is
yours, and `cause.where` already points at it. `cause.type` and `cause.message` are the exception
as your code raised it, whole. Fix the code, and rerun; the run's record, if one was started, was
not completed and needs no cleanup beyond what the refusal states in `retry_precondition`. A crash
inside a callback is the one refusal whose `mutation` can be true — a fill may already have been
committed — so read `retry_precondition` before rerunning.

### Recovering from: 503 unavailable

The machine refused: a file could not be read or written, a disk was full, a path was not
readable parquet. The declaration is right and the data may be fine.

Typical codes: `workspace.unreadable`, `workspace.write_failed` (the workspace document itself),
`source.unreadable`, `source.observations_unreadable`, `source.distinct_unreadable`,
`source.finite_unreadable`, `source.conditional_positive_unreadable`,
`source.execution_snapshot_unreadable`, `source.execution_candidates_unreadable` (a source that
exists but could not be scanned or queried), `roster.unreadable`, `component.source_unreadable`,
`argument.file_unreadable`, `datamodel.chunk_failed` (a datamodel's output could not be written).

Check `source.file` first — it is the path vqapr actually resolved. `cause.type` and
`cause.message` carry the operating system's or the reader's own error (`PermissionError`,
pyarrow's `ArrowInvalid`), which usually says what is wrong with the file. Fix the file or the
permission and retry the same command unchanged; nothing in the declaration needs to change. A
write that failed (`workspace.write_failed`, `datamodel.chunk_failed`) left the previous document
or no chunk at all — the refusal's `mutation` says which.

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
