---
name: run-backtest
description: Declares, checks, and executes a vqapr run: choosing sessions and decision times, binding a strategy to an exchange and compliance rules, proving readiness with `vqapr check`, then executing with `vqapr run`. Use when the user wants to run, execute, or backtest something already registered, asks why a run refuses to start, or asks what a long run is doing while it executes.
---

# Run a vqapr backtest

## Invoke the CLI through the active environment

Installing a console script into a virtual environment does not put it on the global shell PATH.
Use one launcher consistently:

- activated environment: `vqapr --help`
- uv-managed project: `uv run vqapr --help`

If bare `vqapr` is not found but `uv run vqapr` works, the package is installed; the environment
is simply not activated. Apply the same prefix to every command below.

## A run is configuration, and it is registered

Not a script and not a set of arguments. A run declares the universe, the period, the sessions it
fires on, the venue-local wall time it fires at, the venue, the execution dataset and the price it fills at, the initial
account, and the strategies it tries — and it is registered like everything else, so a result can
always name the declaration that produced it.

**The strategy is called at every instant of the run's `agenda` and decides for itself whether
to act.** `every: 1d` with `at` is one decision a day; `every: 1M` the first trading day of each
month; `every: 5m` with `from`/`to` every five minutes inside each day. The days come from the
execution dataset, never from a list. There is no valuation or monitoring time to declare: the
book is valued at every instant of the market clock, and the declared compliance rules observe it
right after.

**Three factor models on one cadence are one run with three strategies, not three runs.** Each
strategy runs with its own account and writes its own record.

## Workflow

```
Run progress:
- [ ] 1. vqapr new run --out runs.yaml
- [ ] 2. Fill it with registered ids
- [ ] 3. vqapr register runs.yaml
- [ ] 4. vqapr check <run-id>      <- writes nothing; fix everything it reports
- [ ] 5. vqapr run <run-id>
- [ ] 6. Confirm every strategy reached status: completed
```

### 1–2. Declare it

```bash
vqapr new run --out runs.yaml
```

The template carries every required key with its meaning. Fill it with **registered** ids: an
unregistered component, dataset or exchange is refused at step 3, by name.

The strategy clock is the `agenda:` block — `every` with `at`, or with `from`/`to` — expanded
over the trading days the execution dataset has rows for; `timezone` is the zone it is read in. See
[references/run-declaration.md](references/run-declaration.md) for what a run needs and what it
must not carry.

### 3. Register it

```bash
vqapr register runs.yaml
```

A run definition is the provenance of a result, so re-registering the same `run_id` with a changed
body is refused (`run.registered`, 409). Withdraw it with `vqapr rm run-definition <run-id>` and
register again; existing records stay readable.

### 4. Check it

```bash
vqapr check <run-id>
```

**Prove it before spending a run.** `check` writes nothing and reports every independent problem at
once, so a run with four defects costs one command rather than four round trips.

Read [references/check-before-run.md](references/check-before-run.md) before interpreting the
output — the envelope's `checked` list has four entries and there are eight judgments, and
expecting eight is the obvious mistake.

### 5. Run it

```bash
vqapr run <run-id> [<run-id> ...] [--jobs N] [--force]
```

Preflight once, freeze, execute. Several ids run several runs; `--jobs N` runs them in N
processes, one run per process, strategy and datamodel runs alike, and the batch envelope's
`jobs` says how many processes actually ran it. A batch in which one run reads the dataset
another run in it writes is refused whole before anything starts (`run.batch_dependent`, 400):
run the producer first, then the batch. Each run's entry under `runs` has the same shape a
single run's envelope has.

A YAML path handed to `run` or `check` is refused by name — both take a registered id.

### 6. Confirm

`ok: true` with a `strategies` map where every entry carries `status: completed`, an `occurrences`
count, an `account_version` and a `record` (`<strategy-id>@<fp8>`). For a datamodel run, a
`datamodels` map with `dataset_id`, `rows`, `sessions` and its record.

## When one strategy fails, the others still run

Each strategy is its own flow with its own account, so a refusal inside one is **that strategy's
outcome, not the run's**. The envelope is `ok: false` with `stage: run.strategy_failed` and the
same `strategies` map — completed lines beside failed ones, each failure carrying its `stage`,
`component_id`, `failures` and `at`.

The completed records stand. Fix the failed strategy, register the file again, and
`vqapr run <run-id> --strategy <id>` runs it alone into a new record beside them.

## While it is running

A record is written last, so a strategy with no record yet is not necessarily lost:
[references/watching-and-failures.md](references/watching-and-failures.md) covers `status: running`
versus `status: unfinished`, and how far the progress numbers can lag.

## After it finishes

- Reading the result is the **`analyze-result`** skill's job — start from `strategy_report` and
  `run_report`, not from the raw tables. (Named, not linked: a link into another skill's directory
  would pull its whole body in as a reference, and it is a skill in its own right.)
- Counting how many times a strategy was tweaked, and removing records:
  [references/records-and-tweaks.md](references/records-and-tweaks.md).
- Feeding one run's decisions into the next run as a dataset:
  [references/feeding-the-next-run.md](references/feeding-the-next-run.md).

## Stop condition

`vqapr check <run-id>` returns `ok: true`, then `vqapr run <run-id>` returns `ok: true` with every
strategy at `status: completed`. A run whose envelope is `ok: false` has not finished, even when
some strategies completed — say which ones did and which did not.

---

A refusal carries its own status, stage and cause, plus `fix`, `requirement`, `observed` and
`source` — read it rather than looking for it here. Status **423 or 503 means wait and retry the
same command unchanged**; **502 is a strategy's own code raising** (`cause.origin: "user"`,
`cause.where` names the line) — fix the component; **500 is a vqapr defect**: do not work around
it, report it with the envelope.
