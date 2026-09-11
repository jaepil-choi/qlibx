# Panels from the tables — name by name, instant by instant

## Contents

- Why the tables
- Read a table into a frame
- Held weights
- Intended weights, and the gap per name
- P&L per name per period
- Reconcile before drawing
- Costs and refusals per fill
- Fill price against the price at the decision
- Figures

## Why the tables

The report computes the summary numbers once: quote those and never recompute them. Its sections
are totals, though — `book` sums the weights at each instant, `attribution.by_instrument` sums each
name's P&L over the whole run. A deep dive wants the panels under those totals: each name's weight
at each instant, each name's P&L in each period, each fill's cost and price. **Those are already
rows in the four tables.** Build them here, at the rendering edge; nothing about what a run records
changes to get them.

Every recipe below reproduces a report number exactly when summed. Check that before drawing.

The blocks run in order: later ones use the frames earlier ones built. `store` is the store root
and `run_id` the run; a run with one strategy needs no `ref`.

## Read a table into a frame

```python
import numpy as np
import pandas as pd
from vqapr.public import read_run_record, read_strategy_table


def table(store, run_id, name, ref=None) -> pd.DataFrame:
    frame = pd.DataFrame(read_strategy_table(store, run_id, name, ref))
    for column in ("event_time", "observed_at"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame
```

- **Every instant to UTC, once, here.** `event_time` is stored in the run's zone, `observed_at` in
  UTC, and the report's opening instant carries a fixed offset. Mixed zone objects make pandas
  refuse, or fall back to an `object` index that no join matches. Convert back to local time only
  for axis labels.
- **Some numbers come back as text.** `vqapr.weight.weight`, and in `vqapr.fill` the quantities and
  `cash_delta` — on some venues `price`, `commission` and `tax` too — are plain strings.
  `.astype(float)` them here and nowhere earlier.

## Held weights — instrument × valuation

```python
account = table(store, run_id, "vqapr.account")
head = account[account.instrument == "_ACCOUNT"].set_index("event_time").sort_index()
nav = head["nav"].astype(float)

held = account[account.instrument != "_ACCOUNT"].copy()
held["value"] = held["quantity"].astype(float) * held["price"].astype(float)
value = held.pivot(index="event_time", columns="instrument", values="value")
present = held.pivot(index="event_time", columns="instrument", values="quantity").notna()
value = value.where(present, 0.0).reindex(nav.index, fill_value=0.0)
held_weight = value.div(nav, axis=0)
```

A name not held is `0`; a name held with no mark is `NaN` and stays `NaN` — `book.unmarked` counts
those. `held_weight.sum(axis=1)` is `book.net_exposure` at each valuation; the report's `book`
may also carry the initial book in front (see the P&L section), which has no row here. A run recorded with
`--no-account-positions` has only the `_ACCOUNT` rows, and this panel does not exist.

## Intended weights, and the gap per name

```python
weight = table(store, run_id, "vqapr.weight")
weight["weight"] = weight["weight"].astype(float)
intended = weight.pivot(index="event_time", columns="instrument", values="weight").fillna(0.0)
```

A decision's rows are its whole target book, so a name missing from a decision is `0`. A hold or a
decline writes no rows at all; to show the target in force at every valuation, forward-fill it:
`intended.reindex(held_weight.index, method="ffill")`.

The book a decision got is the first valuation at or after it:

```python
asked = intended[intended.index <= held_weight.index[-1]]  # the report skips later ones too
got_at = held_weight.index[held_weight.index.searchsorted(asked.index, side="left")]
names = held_weight.columns.union(asked.columns)
gap = pd.DataFrame(
    held_weight.reindex(index=got_at, columns=names).fillna(0.0).to_numpy()
    - asked.reindex(columns=names, fill_value=0.0).to_numpy(),
    index=asked.index,
    columns=names,
)
```

`gap.abs().sum(axis=1)` is `intent.gap`, and `gap` itself says which names made it.

## P&L per name per period

The report's identity (`attribution`): a period runs from one valuation to the next, and a fill
belongs to the period whose closing valuation is the first with `account_version` at or above the
fill's — the version is the commit order, exact where a clock comparison would be a guess. Per
name and period:

    pnl = value at close − value at open + Σ cash_delta of that name's fills in the period

`cash_delta` is the venue's own cash effect of the fill, commission and tax included, so this P&L
is **net of cost**.

```python
version = head["account_version"].astype(int)
run = read_run_record(store, run_id)
initial = run["initial_account"]
if int(version.iloc[0]) > 0 and not initial["positions"]:
    # The first valuation already holds the first fills: put the initial book in front of it,
    # as the report does, or the first day's fills fall outside every period.
    start = pd.Timestamp(run["period"]["start"]).tz_convert("UTC")
    nav = pd.concat([pd.Series([float(initial["cash"])], index=[start]), nav])
    version = pd.concat([pd.Series([0], index=[start]), version])
    value = pd.concat([pd.DataFrame(0.0, index=[start], columns=value.columns), value])

fill = table(store, run_id, "vqapr.fill")
for column in ("requested_quantity", "dealt_quantity", "price", "cash_delta", "commission", "tax"):
    fill[column] = fill[column].astype(float)
closing = np.searchsorted(version.to_numpy(), fill["account_version"].to_numpy(), side="left")
inside = (closing > 0) & (closing < len(version))
placed = fill[inside].assign(period_end=nav.index[closing[inside]])
traded = placed.pivot_table(
    index="period_end", columns="instrument", values="cash_delta", aggfunc="sum"
)

every = value.columns.union(traded.columns)
move = value.diff().iloc[1:].reindex(columns=every, fill_value=0.0)  # unmarked stays NaN
cash = traded.reindex(index=move.index, columns=every).fillna(0.0)
pnl = move + cash
residual = nav.diff().iloc[1:] - pnl.sum(axis=1)
contribution = pnl.div(nav.shift(1).iloc[1:], axis=0)  # share of the opening NAV
```

A name unmarked at either end of a period has `NaN` there: its P&L is in `residual`, as in the
report. A name bought and sold inside one period never appears in `vqapr.account` and still gets
its cash, which is why the columns are the union.

## Reconcile before drawing

```python
from vqapr.public import strategy_report

report = strategy_report(store, run_id)
att = report.attribution
scale = nav.mean()
period_total = pd.Series(
    [float(v) for v in att.total], index=pd.to_datetime(att.instants, utc=True)
)
by_name = pd.Series({entry.instrument: float(entry.pnl) for entry in att.by_instrument})
assert (pnl.sum(axis=1) - period_total).abs().max() < 1e-9 * scale
assert (pnl.sum().reindex(by_name.index) - by_name).abs().max() < 1e-9 * scale
```

If these do not hold, the panel is wrong and is not drawn. On a 1,600-period, 632-name record they
agree to 1e-16 of NAV.

## Costs and refusals per fill

```python
costs = (
    fill.assign(
        fees=fill["commission"].fillna(0.0) + fill["tax"].fillna(0.0),
        notional=(fill["dealt_quantity"] * fill["price"]).abs(),
    )
    .groupby("event_time")[["fees", "notional"]]
    .sum()
)
costs["bps"] = costs["fees"] / costs["notional"] * 1e4  # per rebalance

refused = (
    fill[fill["dealt_quantity"] == 0]
    .groupby(["event_time", "reason"])
    .size()
    .unstack(fill_value=0)
)
partial = fill[
    (fill["dealt_quantity"] != 0) & (fill["dealt_quantity"] != fill["requested_quantity"])
]
```

`costs["fees"].sum()` is `trading.costs.total`. `reason` is `absent`, `nontradable`, `no_trade` or
`unfunded`; `requested_quantity` beside `dealt_quantity` is the order beside what it got.

## Fill price against the price at the decision

The record holds when each weight was decided (`vqapr.weight` `event_time`) and what each fill dealt
at (`vqapr.fill` `price`). What the market showed at the decision is in the execution dataset the
run named: `run["execution"]` gives its `dataset_id`, `price_fields` and `fill.trade_price`, and
`vqapr show dataset <id> --limit 0` gives `path`, `workspace_root`, `instrument_field`,
`available_at` and `fields`.

```python
import json
import subprocess
from pathlib import Path

import duckdb

execution = run["execution"]
shown = json.loads(
    subprocess.run(  # inside `uv run python`, where `vqapr` is on PATH
        ["vqapr", "show", "dataset", execution["dataset_id"], "--limit", "0"],
        capture_output=True, text=True, check=True,
    ).stdout
)
field = shown["fields"][execution["price_fields"][execution["fill"]["trade_price"]]]
source = (Path(shown["workspace_root"]) / shown["path"]).as_posix()
key, at = shown["instrument_field"], shown["available_at"]
wanted = ", ".join(f"'{name}'" for name in sorted(fill["instrument"].unique()))
prices = duckdb.sql(
    f"select {key} as instrument, {at} as available_at, {field} as decision_price "
    f"from read_parquet('{source}') where {key} in ({wanted})"
).df()
prices["available_at"] = pd.to_datetime(prices["available_at"], utc=True)
prices = prices.sort_values("available_at")

decided = pd.DataFrame({"decided_at": sorted(weight["event_time"].unique())})
dealt = fill[(fill["dealt_quantity"] != 0) & fill["price"].notna()].sort_values("event_time")
dealt = pd.merge_asof(dealt, decided, left_on="event_time", right_on="decided_at")
dealt = pd.merge_asof(
    dealt.sort_values("decided_at"), prices,
    left_on="decided_at", right_on="available_at", by="instrument",
)
dealt["shortfall_bps"] = (
    np.sign(dealt["dealt_quantity"]) * (dealt["price"] / dealt["decision_price"] - 1) * 1e4
)
```

`path` is the registered file; use the duckdb reader that matches its format (`read_parquet`,
`read_csv_auto`). Positive `shortfall_bps` is adverse: a buy dealt above, or a sale below, the last
price the decision could see. When the fill is the next close, most of it is the market's move over
that interval — about ±170 bp between quartiles on daily legs — not a charge; commission and tax
are `fees`, above. Say which it is when you quote it.

## Figures

| panel | figure |
|---|---|
| `held_weight` | heat map, names × time: the largest 30 by mean \|weight\|, month end |
| `gap` | heat map of the gap per name at each decision |
| `contribution` | cumulative lines for the top and bottom five names; total by name as bars |
| `pnl` | concentration: share of total P&L from the top k names |
| `costs` | fees per rebalance as bars, `bps` as a line |
| `refused` | stacked bars by reason |
| `dealt["shortfall_bps"]` | histogram, or against order size |

```python
import matplotlib.pyplot as plt
import seaborn as sns

top = held_weight.abs().mean().nlargest(30).index
monthly = held_weight[top].resample("ME").last()
fig, ax = plt.subplots(figsize=(10, 7))
sns.heatmap(
    monthly.T.fillna(0.0), cmap="Blues", ax=ax, cbar_kws={"label": "weight of NAV"},
    xticklabels=[d.strftime("%Y-%m") if d.month == 1 else "" for d in monthly.index],
)
fig.savefig("held_weight.png", dpi=150, bbox_inches="tight")

cumulative = contribution.fillna(0.0).cumsum()
final = cumulative.iloc[-1]
fig, ax = plt.subplots(figsize=(10, 5))
for name in [*final.nlargest(5).index, *final.nsmallest(5).index]:
    ax.plot(cumulative.index, cumulative[name] * 100, label=name, linewidth=1)
ax.axhline(0, color="black", linewidth=0.8)
ax.set_ylabel("cumulative contribution (% of NAV)")
ax.legend(ncol=2, fontsize=7, frameon=False)
fig.savefig("contribution.png", dpi=150, bbox_inches="tight")
```

A name's cumulative contribution sums shares of each period's opening NAV; it is additive across
names, not a compounded return.
