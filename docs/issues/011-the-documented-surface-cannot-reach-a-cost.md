# 011 — The documented surface cannot reach a cost, or a roster

**Status:** open. Found 2026-08-28 by two independent first-time-user journeys in `testbed/` and
`testbed-claude/`, run against the installed package with no access to `src/`, `tests/` or `docs/`.

Both journeys **completed** — `check` and `run` both returned `ok:true`. Everything below is a gap
between what the package can do and what its documented surface says it can do, which is the more
expensive kind: a journey that finishes wrong teaches nothing until someone reads the numbers.

Two of the seven were fixed on the spot and are recorded in `docs/implementations/067`. The rest
are open.

---

## Open

### 011.1 — There is no reachable way to declare a per-trade cost (HIGH)

A mission asking "do ETFs cost less to trade than stocks?" cannot be answered from the documented
surface.

`vqapr new exchange` emits a subclass of `AcademicExchange`, whose docstring says it fills *"with
no cost or slippage"*. The skill and the scaffold both state that `AcademicExchange` and
`KrxExchange` are the only legal profiles, so `KrxExchange` must be the costed one — and **nothing
on the public surface describes it.** `--instruments` is the only option `vqapr new exchange` has.

The other agent spent the largest single block of its mission looking for the rate, black-box:

- 26 candidate keywords against `KrxExchange(listings=..., **kw)` — all rejected. It takes exactly
  `listings` and `exchange_id`.
- 16 against `TradeRule(...)` — all rejected.
- Rate columns added to the roster parquets — accepted silently, and every fill still `0.00`.

Meanwhile every downstream artifact promises costs exist: `vqapr.fill` carries `commission`, `tax`
and `kind` per fill, and the instruments template warns that a mis-keyed roster would *"charge the
wrong rate for the life of the project"*. After a complete passing run, all 64 fills carried
`commission: 0.00` and `tax: 0.00` on buys and sells alike.

**The rates do exist.** `krx_rules({"A": "stock", "B": "etf"})` produces exactly what the ETF
exemption is for — verified: a stock sale pays `tax=2000.000` on a 1,000,000 notional and an ETF
sale pays `0`. But `krx_rules` appears **zero times** in the installed skill, and the emitted
scaffold never mentions it.

This is the sharpest form of the problem: the capability this repository spent an entire session
building is real, correct, and unreachable by a user following the documentation.

**Fix:** `vqapr new exchange <id> --profile krx` emitting a costed scaffold built from
`krx_rules`, with `price_limits=` visible and commented. Failing that, one paragraph in the skill
naming `krx_rules` and what it charges.

### 011.2 — The roster is unreachable, and unlistable (HIGH)

The skill states, in bold, that *"a run needs five declarations: a dataset, an execution input, an
exchange, agendas with their configs, and at least one component."* The roster is not among them.

`vqapr new --help` accepts eight kinds and documents six; `instruments` is accepted and appears
nowhere else in the help text. The skill mentions "instruments" twice, both the `--instruments`
flag of `new exchange`.

`vqapr list` has no `instruments` kind — it covers eight others — so a registered roster cannot be
inspected from the CLI at all. Both journeys found the workspace file by reading
`.vqapr/instruments.json` directly, which a user should not have to do.

**Fix:** name the roster in the skill's declaration list and the `new` usage block; add
`vqapr list instruments`.

### 011.3 — A run with no roster completes silently (HIGH)

Following the documented five declarations produces a run where every fill records `kind: None`.
No refusal, no warning, nothing in the success envelope.

On an academic venue that is harmless. On a KRX-shaped venue it means every name is charged
identically while the record says the categories were never known — and `cost_by_kind()` collapses
to one unlabelled bucket, so the report that would expose it is the one the gap erases.

**Fix:** have `run` state the roster it read — id, digest, or the per-category counts registration
already prints. This single change also closes 011.5 and gives 011.2 its missing signal.

### 011.4 — `roster_id` is declared, echoed, and discarded (MEDIUM)

The declaration syntax invites naming a roster; `.vqapr/instruments.json` stores `schema`,
`tables` and `digest` and **no id**. Registering a second roster under a different id silently
replaces the first and returns `ok` with the new id echoed back.

Roster re-registration being ordinary is correct and deliberate — it tracks a changing world, and
what a past run treated an instrument as is testified to by that run's own fills. But silently
discarding a declared identifier is a different thing from allowing updates, and it means a
project cannot hold two rosters even though the syntax says it can.

**Fix:** honour `roster_id` as an identity, or drop it from the template and document the roster
as one global slot each registration replaces.

### 011.5 — A partly-commented roster declaration drops a category (MEDIUM)

The emitted `instruments.yaml` ships with `stock:` live and `etf:`, `index:`, `factor:` commented.
A user who exports twelve names across two categories and registers the emitted declaration
unchanged registers **ten**, silently: the ETF table sits beside it undeclared.

The per-category receipt caught it — `{"stock": 10}` against a universe of twelve is legible — but
the mitigation is a number a user must notice, not a refusal.

**Fix:** registration comparing declared tables against the files present beside them, and saying
*"instruments_etf.parquet exists and is not declared"*.

### 011.6 — Constraints are advertised and undocumented (HIGH)

The run-spec template offers an optional `constraints:` list of `constraint-component-id`. There is
no `vqapr new constraint` scaffold, `register --help` names only `datamodel` and `strategy`, and
the skill never mentions constraints.

Probing by refusal showed the kind is real: registering an empty subclass yields *"Can't
instantiate abstract class without an implementation for abstract methods 'constraint_id',
'evaluate', 'project', 'requirements', 'validate_intended'"*. Five abstract methods, no documented
signature or return type — and `project` is a semantic contract (project a proposed book onto the
feasible set) that cannot be guessed.

The other agent correctly refused to guess: guessing `project` wrong produces a backtest that looks
correct and is not. A 20%-position-cap requirement went unmet as a result.

**Fix:** a `vqapr new constraint <id>` scaffold with the five methods stubbed and commented, or
remove the section from the run-spec template until constraints are usable from outside.

### 011.7 — `KeyError: 'component'` as a refusal (MODERATE)

Writing `component_id:` where the run-spec template says `component:` yields:

```
code    : run.check.declaration_invalid
observed: KeyError: 'component'
fix     : correct the run spec at spec.yaml so the declaration phase completes, then check again
```

A raw Python exception as `observed`, a `fix` naming no cause, and a null `source.key_path`. Cost
about four minutes of diffing against a re-emitted template.

Every other refusal in both journeys named its cause precisely, which is why this stands out — see
the lookback refusal below.

**Fix:** validate the spec's keys before the declaration phase, so a missing key reports as a
missing key rather than as the exception it later causes.

### 011.8 — The `workspace.open.missing` fix names a Python API (LOW)

Registering into a directory with no workspace refuses with
`fix: "call Workspace.create() to initialize the workspace before opening it"` — a Python call, to
a user who has only ever run CLI commands.

**Fix:** name the CLI path that creates a workspace.

### 011.9 — The templated 15:29 callback cannot see the 15:30 close (LOW)

The agendas template suggests `at: "15:29"` for both strategy and valuation, explained purely as an
ordering rule ("strictly before the execution template's 15:30 target").

What it means for a dataset whose `available_at` is the 15:30 close is that a strategy firing at
15:29 on session *N* decides on session *N-1*'s data. That is correct and desirable. Applied to
*valuation* it is not: a 15:29 mark values the book at the previous session's close, so the daily
NAV series lags by one session for no stated reason.

**Fix:** one sentence in the agendas template — a callback at 15:29 sees data available strictly
before 15:29, and valuation is usually placed after the execution instant instead.

---

## Fixed already — see `docs/implementations/067`

- **A registered roster changed nothing.** All 599 fills recorded `kind: None` with twelve
  instruments registered and the digest in the workspace. `vqapr.fill` never declared a `kind`
  column, so the value was computed at fill time and dropped at the recorder. Now
  `{stock: 458, etf: 86, None: 55}`, every `None` a zero-dealt `no_trade` that was never charged.
- **`vqapr new instruments --out <name>.py` emitted two halves that disagreed.** The declaration
  derived table names from the script's stem; the exporter always wrote `instruments_*.parquet`.
  They agreed only at the default name, and `--out` is offered on the same command.

---

## What the surface got right, recorded as the standard

- **The lookback refusal.** *"dataset begins 2024-01-02 15:30:00+09:00, run starts
  2024-01-02T00:00:00+09:00, lookback 6 row(s)"* with a fix naming both remedies and a timestamp
  pasteable straight into the spec. Fixed in under a minute. Every refusal should read like this.
- **`check` collects.** Two independent failures in one call, as the skill promises.
- **The timezone guidance was specific and correct** — it named `assume_timezone` over a cast, and
  prescribed a round-trip proof.
- **Every scaffold ran as emitted.** `new strategy` registered and executed with no edits.
- **The per-category registration receipt** is the only mechanical check in the roster path that
  fires on the success path, and it is what caught 011.5.
