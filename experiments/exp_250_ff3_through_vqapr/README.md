# exp_250 - the Fama-French three factors, built through vqapr

**Question.** In the ff3 testbed (kwam-enhanced-index/vqapr-ff3-testbed), three coding agents were
handed vqapr with its skills installed and asked to build daily RMRF, SMB and HML on Korean data.
All three read the skills and built the factors in pandas instead, because they concluded vqapr
could not express "a value-weighted average of returns". Before the entry skill is rewritten to
say that *a factor's return is the NAV return of a factor-mimicking portfolio, which is a
StrategyModel on the academic venue*, that sentence has to be proven by a real run. This is that run.
The mission, data and answer key are the testbed's own (`PROMPT.md`, the four parquet files,
`tools/verify_kimchi.py`).

**Answer. Yes, it holds.** Six long-only portfolios and one index-holding book, all run through
the ordinary vqapr surface, give factors that track the published Kimchi series as closely as the
correct pandas scripts did. When the same portfolio membership is recomputed the pandas way, the
vqapr version differs from it by only 15 bp^2 (SMB) and 24 bp^2 (HML): correlations of 0.999 and
0.998. Almost all of the remaining gap to Kimchi is the data and the definition, not vqapr.

vqapr 0.14.3, branch `develop`, 2026-09-11. Nothing under `src/` or `tests/` was touched.

## Result

Two arms ran. They differ in one rule only: what a company's book equity (BE) is when its
statement has neither `total_equity` nor `controlling_equity`. The specification says nothing
about that case. In this data it covers every FY2017 statement except about 220 of them.

- **ff3** follows the specification's words and drops those names. So its 2018 books hold 199
  names in total, against about 1,500 in every later year.
- **ff3x** uses total assets minus total liabilities for them. By the balance-sheet identity that
  *is* total equity; it matches exactly on 99.95% of the rows that carry all three. This is the
  headline arm, and `outputs/factors.csv` is its output.

Daily returns 2018-07-02 .. 2024-12-30 (1,600 sessions) against Kimchi (`verify_kimchi.compare`):

| arm | factor | corr | MSE bp^2 | ann. mean vqapr / Kimchi | ann. vol vqapr / Kimchi |
|---|---|---:|---:|---:|---:|
| ff3x | RMRF | 1.0000 | 0.0 | 0.14% / 0.14% | 18.85% / 18.85% |
| ff3x | SMB | 0.9889 | 145.9 | -0.80% / -0.89% | 12.78% / 12.93% |
| ff3x | HML | 0.9736 | 331.8 | 6.53% / 7.45% | 12.32% / 12.67% |
| ff3x | **total** | | **477.7** | | |
| ff3 | SMB | 0.9585 | 566.6 | -0.99% / -0.89% | 13.23% / 12.93% |
| ff3 | HML | 0.9157 | 1183.7 | 8.74% / 7.45% | 13.58% / 12.67% |
| ff3 | total | | 1750.3 | | |
| ff3, from 2019-07 | total (SMB 0.988 / 154, HML 0.973 / 363) | | 517.7 | | |

The correct pandas implementations in the testbed reached SMB corr about 0.99, HML about 0.975 and
a total MSE of about 460 bp^2. Arm ff3x lands there.

RMRF is exact. The market book's NAV return equals the KOSPI index return to within 1e-11, and
RF is the same formula on the same rates series.

SMB and HML are exactly 0 on 2018-07-02. On that day every leg is still cash: its first book fills
at that day's close, so its first return is 2018-07-03. The row is what the record says, and it
is kept rather than dropped.

**Where the remaining gap comes from** (`outputs/decomposition_ff3x.md`, full period, MSE bp^2).
Each leg's membership was taken from vqapr's own record and recomputed the way a pandas script
does it:

| step | SMB | HML |
|---|---:|---:|
| vqapr against pandas, same membership, same timing (what vqapr's execution decided) | 15.3 (corr 0.999) | 24.4 (corr 0.998) |
| one-day formation lag (the new book is held from the second July session) | 5.8 | 4.7 |
| pandas with Kimchi's timing against Kimchi (membership, BE and data) | 141.7 | 327.0 |

The worst holding year, 2023-07..2024-06 (SMB 373, HML 916), is just as bad in the pandas
recomputation (381, 854), while vqapr against pandas is only 17 and 29 that year. So that year is
the data or the definition, not vqapr.

**How many names each portfolio held** (from `vqapr.weight`, arm ff3x). Arm ff3 is identical from
2019 on; in 2018 it has 40 / 53 / 31 / 42 / 20 / 13, 199 names in all, 113 of them KOSPI.

| July of | S1 | S2 | S3 | B1 | B2 | B3 | total | KOSPI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 418 | 393 | 193 | 277 | 129 | 64 | 1474 | 583 |
| 2019 | 453 | 390 | 193 | 274 | 140 | 67 | 1517 | 598 |
| 2020 | 402 | 440 | 179 | 340 | 131 | 68 | 1560 | 607 |
| 2021 | 489 | 439 | 175 | 300 | 145 | 72 | 1620 | 611 |
| 2022 | 514 | 458 | 194 | 304 | 149 | 73 | 1692 | 627 |
| 2023 | 537 | 488 | 188 | 327 | 157 | 74 | 1771 | 635 |
| 2024 | 478 | 538 | 231 | 339 | 155 | 75 | 1816 | 642 |

## The recipe (quotable)

In plain words:

1. **Register the four files as they are, with honest "when was this known" stamps.** A daily
   price and market cap are known at that day's close, 15:30 Seoul. A month-end listing is known
   at that month-end's close. An annual statement is known three months after its fiscal year
   ends. That last one is the specification's availability rule, and here it becomes a
   registration fact that every read respects. The price table is also the venue table: a halted
   day cannot fill.
2. **Build one portfolio per leg (S1 S2 S3 B1 B2 B3).** Each decides once a year, on July's first
   trading day, using what it can see: June's last close for size, the June month-end listing,
   and the newest statement from the previous fiscal year. It sorts with the package's own
   Fama-French cut and bucket helpers, KOSPI-only breakpoints applied to both markets, and asks to
   hold its names in proportion to size. Between Julys it just holds its shares, so the weights
   drift the way a value-weighted buy-and-hold does.
3. **Build one more book that holds the KOSPI index.** The index level is registered as a
   one-instrument price table, and its NAV return is the market return.
4. **Run each as its own run on the frictionless academic venue**, filling at the decision day's
   close with a large account (10 trillion KRW, whole shares).
5. **Read each run's daily NAV return back from the record, then do the factor arithmetic.**
   SMB = mean(S) - mean(B), HML = mean(S3, B3) - mean(S1, B1), RMRF = market book return - RF,
   with RF from the registered rates.

<details><summary>The same, with the names</summary>

1. `grain: instrument_instant` for prices / listing / financials. `available_at` is built with
   `pyarrow.compute.assume_timezone(..., "Asia/Seoul")` and proved on one instant, as in
   `timezone-proof.md`. The prices dataset carries `execution: {is_tradable: is_tradable}`, with
   `is_tradable = not is_trading_halt`. Rates are `grain: instant`. The KOSPI level is its own
   `instrument_instant` execution table with one instrument, `KOSPI`.
2. Roster: every ticker as `stock`, plus `KOSPI` as `index`, written by hand as
   `instruments_{stock,index}.parquet`. One `AcademicExchange` lists them all
   (`quantity_step=1`).
3. `strategy_template.py`, six copies differing only in `SIZE` and `BM`:
   - `CalendarLookback(days=14)` on `market_cap`, `is_trading_halt`: `.current()` is June's last
     close, and `.current().at` is asserted to be in June.
   - `CalendarLookback(days=45)` on the listing: `.current()` is the June month-end row.
   - `CalendarLookback(days=600)` on the financials: `.matrix()` gives the newest row whose
     `fiscal_yyyymm // 100 == year - 1`.
   - Breakpoints via `fama_french_cut_points(..., reference=kospi, fractions=(0.5,))` and
     `(0.3, 0.7)`, then `fama_french_assign`.
   - The decision is `Rebalance.of(long={name: ME}, invested=1)`.
4. `market_strategy.py` returns `Rebalance.of(long={"KOSPI": 1})`.
5. Runs: `agenda: {every: 12M, at: "15:29"}`, `start` on July 1 (June 1 for the market run),
   `execution.fill.at: "15:30"`, `trade_price: close`, `initial_account.cash: "10000000000000"`,
   `LONG_ONLY`. Seven runs: a run is one model. Run them serially, not with `--jobs`; see friction 2.
6. `strategy_report(store, run_id).performance.returns` for each leg. RF is
   `(1 + cd91/100) ** (1/252) - 1`, read back through `vqapr show dataset ff-rates --limit N`
   (`factors.py`).

</details>

**Why six long-only legs, not two signed books.** A signed SMB book built with `Rebalance.signed`
holds all six portfolios in one account. Between rebalances the six drift against each other, so
its daily return is not "the average of three small portfolios minus the average of three big
ones", which re-averages every day. Six separate accounts reproduce the definition exactly: value
weights with drift inside each leg, and an equal-weight average across legs taken by arithmetic
after the run. (`Rebalance.of` on a signed book would also halve the scale; its own docstring says so.)

**What the mapping could not express exactly.**

- **The June-end formation.** There is no month-end cadence: `every: 12M` fires on the first
  trading day of the run's first month. A fill must also come strictly after the decision, and
  vqapr will not trade at a close on data from that same close. So the books are formed on
  July's first session from June-end data and filled at that session's close, and the first July
  session still carries last year's book. The cost is measured: 5.8 bp^2 on SMB and 4.7 bp^2 on
  HML (arm ff3x).
- **The factor itself is not a strategy.** It is arithmetic on seven strategies' NAV returns,
  done after the run.

## Frictions, most expensive first

Tags: **product-gap** means vqapr cannot do it, or does it wrongly. **skill-gap** means vqapr can
do it but the shipped skills did not say how, or said something wrong.

1. **Six files per portfolio set, and a second set costs six more (product-gap).** A
   StrategyModel has no config channel, and the skills say an arm is a new file with a new id
   (`make-strategy`, "One strategy is one file"). So there are six generated copies per arm
   (`prepare.py`). Arm ff3x also needed a second dataset registration, `ff-financials-x`: adding
   two fields to the registered `ff-financials` would have changed the inputs under arm ff3's
   records. Thirteen runs in all.
2. **A `--jobs` batch leaves runs that cannot be read (product-gap, known).**
   `vqapr run ff3x-s1 ... --jobs 3` answered `ok: true` with every strategy `completed`. But no
   `runs/<id>/run.json` was written. `strategy_report` raised `FileNotFoundError: no complete run
   record for 'ff3x-s1' ... known runs: ff3-b1, ...`, and `vqapr show run ff3x-s1` was refused:
   `argument.value_invalid`, 400, fix "run `vqapr list runs` to see what this store holds". Yet
   `vqapr list strategies --run ff3x-s1` shows the record as completed. This is already reported,
   untriaged: `docs/issues/report-2026-09-11-a-jobs-batch-writes-no-run-record-so-show-run-refuses-runs-it-reported-completed.md`.
   The workaround was to rerun serially with `--force`.
3. **The same `--force` rerun is refused if the project root is spelled differently
   (product-gap).** Retrying with an absolute `--project-root` instead of `.` gave
   `dataset.source_conflict`, 409: "source_id 'materialized-ff3x-b2-weights' must keep its
   existing physical declaration". The fix it offered was "reuse the registered SourceSpec for
   'materialized-ff3x-b2-weights', or register under a new source_id", which points at a
   registration the user never wrote: the run publishes it. Spelling the root `.` again worked.
4. **Money in holdings that cannot be sold starves the new book, and the record calls it "no
   change" (product-gap, needed `src/`).** At a rebalance, a held name that is halted, or delisted
   with no row, cannot be sold. So its value cannot pay for the new book. The planner pays for
   buys largest-first and drops the smallest ones whole. Example: S1 in July 2019 had 5.7% of NAV
   stuck, and 67 new names worth 5.5% of the target were never bought. The fill table records
   those as `no_trade`, which the enum's docstring describes as a market fact ("the plan asked for
   no change"), not `unfunded`; `UNFUNDED` is only ever emitted by the KRX venue. The public
   docstrings did not explain why a name with a positive target and a tradable row got nothing,
   so I read `src/`: `exchange/venue.py:221`, `exchange/planning.py` (`plan_orders`,
   `_apply_venue_rules`, `_buy_order`), `domain/fills.py`, `exchange/venues/krx.py:497`.
5. **What happens to a delisted holding is written nowhere (skill-gap).** A held name that loses
   its row is never sold: an `absent` order with quantity 0. It then sits in NAV at its last close
   until the run ends. For example, A197210 held 3.0M shares frozen at 38 KRW from 2020-05-13 to
   2024-12-30. The book report still counts it as marked (`unmarked` stays 0). By July 2024 such
   frozen positions were 0.5% of S1's NAV, 1.7% of S2's and 2.2% of B1's (`outputs/semantics.md`).
6. **The skill said "one run with all strategies"; the product says one model per run
   (skill-gap).** `run-backtest/SKILL.md` says: "Three factor models on one cadence are one run
   with three strategies, not three runs". `run-backtest/references/run-declaration.md` and
   `vqapr run --help` ("a run is one model (record 201)") say the opposite. This brief's own
   "one run with all strategies" came from that sentence. Reality: seven runs.
7. **No month-end cadence (product-gap).** See "What the mapping could not express exactly". The
   skills do state the anchor rule, and it behaved as documented.
8. **`vqapr new instruments` does not do what the skill says (skill-gap).** `run-declaration.md`
   says "`vqapr new instruments <ids...>` writes the tables and the declaration". Positional ids
   are refused: `usage.rejected`, 400, "unrecognized arguments: A000030", fix "run `vqapr --help`".
   The `--instruments` form writes only the YAML, not the tables. The two roster parquet files
   were written by hand; the template's comments made that easy.
9. **Memory is far above the documented sizing rule (skill-gap).** One leg over 4,276 names used
   1.7 to 2.1 GB of private memory (0.9 to 1.2 GB working set). The rule in `run-backtest` section 5
   (period x lookback x instruments, plus 130 MB) predicts about 0.25 GB. Three workers took
   5.9 GB. Fills were few (about 4k orders per leg), so this is not the fill growth of the
   2026-09-11 memory report; it is the baseline.
10. **The market leg and the RF series needed guesswork (skill-gap).** No skill says an index can
    be an instrument (roster kind `index`) with its own execution table. It works exactly. The
    rates register cleanly as `grain: instant`, but `vqapr.public` has no Python reader for a
    registered dataset's rows, so RF comes back through the JSON of
    `vqapr show dataset ff-rates --limit 5000`.
11. **Small things.**
    - `strategy_report` series mix a fixed `+09:00` instant (the run start) with `ZoneInfo`
      instants, and pandas refuses them without `utc=True`.
    - `vqapr.fill.kind` is null on zero-dealt rows, though `result-tables.md` says it is never null.
    - The docstrings of `Workspace`, `DatasetRegistration` and `register_dataset` are in Korean,
      while the rest of the public surface is English.
    - The skills do not say how to read a `CalendarLookback` window's newest instant; `.at` on
      `current()` worked.
12. **Data, not vqapr.** FY2017 statements carry no `total_equity` and no NCI at all, and
    `controlling_equity` for only about 220 names. Any implementation that follows the
    specification literally gets 199 names in 2018. That, and not vqapr, is the reason for arm ff3x.

Nothing in registration, `check` or the main runs was refused. All four declarations registered
on the first try, including the 6M-row price table.

## What vqapr decided that a pandas script decides silently

Evidence comes from the record: `outputs/semantics.md`, which reads `vqapr.fill`,
`vqapr.account` and `vqapr.weight` per leg and per rebalance.

- **When a fact was known.** A statement is invisible until three months after its fiscal year
  ends, because registration stamped it that way and every read obeys `available_at <= t`. A
  pandas script applies the same lag in a merge that nothing checks. One subtlety survived: a
  March-year-end company's current-year statement becomes visible on June 30, so the strategy
  still filters on "fiscal year ended last calendar year", as the specification says.
- **You cannot trade at a close on data from that close.** The decision at 15:29 on July's first
  session sees June's last close, the previous session (asserted in the code). The fill is at
  15:30 on that same July session, so the new book's first return is on the second July session.
  Kimchi and pandas hold the new book from June's close.
- **Weights drift by shares, not by a re-weighting.** On the eve of each rebalance the book is 10
  to 49 percentage points (sum of |realised - intended|) away from last July's target. That is
  value-weighted buy-and-hold, the same thing as pandas' previous-day market-cap weights except
  where share counts change.
- **A halted name cannot be traded.** A name halted at the July fill is not bought if new, and
  not sold if old. An old one then stays held for another year. That was 5 to 37 names per
  rebalance in S1. Pandas includes the halted name in the new book at a zero return.
- **A delisted name is frozen, not dropped.** Pandas drops it and silently re-spreads its weight
  over the rest. vqapr keeps it at its last price until the run ends (friction 5). That is dead
  capital, never reinvested: up to 2.2% of a leg's NAV.
- **Stuck money cannot pay for the new book.** Friction 4: up to 5.8% of S1's NAV, with the
  smallest new buys dropped whole.
- **Cash.** The book is fully invested. Whole-share rounding leaves 4e-8 of NAV in cash at 10
  trillion KRW.

Together these cost 15 and 24 bp^2 against the pandas recomputation of the same membership. The
effect is largest in the small-value legs: S3 earned 7.24% a year in vqapr against 6.69% in
pandas, and S1 -2.86% against -2.42% (arm ff3x).

## Wall time and peak memory

Memory is the process tree's private bytes and working set, sampled every 0.25 s by
`measure.py`; it includes the `uv` launcher.

| what | wall | peak private | peak working set |
|---|---:|---:|---:|
| `prepare.py --data` (6M rows, pandas + pyarrow) | 87 s | | |
| `vqapr check` (one run) | 1-2 s | | |
| `ff3-market` | 2 s | | |
| `ff3-s1` alone | 11.7 s | 1.69 GB | 0.86 GB |
| ff3 S2..B3, one serial batch of 5 | 40.3 s | 1.76 GB | 0.95 GB |
| ff3x, 6 runs `--jobs 3` (records unreadable, friction 2) | 32.1 s | 5.93 GB | 2.77 GB |
| ff3x, 6 runs serial `--force` | 62.9 s | 2.05 GB | 1.17 GB |
| `factors.py` per arm (7 `strategy_report` calls, about 7 s each) | about 110 s | | |

## Reproduce

```bash
export PYTHONUTF8=1
uv run python experiments/exp_250_ff3_through_vqapr/prepare.py --data
cd experiments/exp_250_ff3_through_vqapr/work
for f in datasets.yaml instruments.yaml components.yaml runs.yaml \
         datasets_ff3x.yaml components_ff3x.yaml runs_ff3x.yaml; do
  uv run vqapr --project-root . register $f
done
uv run vqapr --project-root . check ff3-s1
uv run vqapr --project-root . run ff3-market ff3-s1 ff3-s2 ff3-s3 ff3-b1 ff3-b2 ff3-b3  # serial: see friction 2
uv run vqapr --project-root . run ff3x-s1 ff3x-s2 ff3x-s3 ff3x-b1 ff3x-b2 ff3x-b3
cd ../../..
for arm in ff3 ff3x; do
  uv run --with tabulate python experiments/exp_250_ff3_through_vqapr/factors.py $arm
  uv run --with tabulate python experiments/exp_250_ff3_through_vqapr/diagnose.py $arm
done
uv run --with tabulate python experiments/exp_250_ff3_through_vqapr/semantics.py   # arm ff3
```

`psutil` (`measure.py`) and `tabulate` (the markdown tables) are not in the project environment.
`uv run --with` overlays them without touching the lock.

## Files

- `prepare.py`: data preparation (timezone proof included), the roster, the venue, both arms'
  strategies, and every declaration. Writes into `work/`, which is gitignored along with the
  vqapr workspace and the prepared parquet.
- `strategy_template.py` (arm ff3), `strategy_template_x.py` (arm ff3x), `market_strategy.py`.
- `factors.py`: factors from the record, and the Kimchi comparison.
- `diagnose.py`: the decomposition.
- `semantics.py`: per-rebalance evidence.
- `measure.py`: wall time and memory.
- `outputs/`
  - `factors.csv` (arm ff3x), `factors_ff3.csv`, `factors_ff3x.csv`
  - `kimchi_compare_<arm>.{md,json}`, `decomposition_<arm>.md`, `names_per_year_<arm>.csv`
  - `legs_<arm>.csv`: the six legs' daily NAV returns
  - `semantics.{csv,md}`

  The root `.gitignore` ignores `experiments/exp_*/outputs/`, so these need `git add -f`.
