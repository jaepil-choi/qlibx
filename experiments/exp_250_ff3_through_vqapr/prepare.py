"""Prepare the testbed data for vqapr and write every declaration the runs need.

    PYTHONUTF8=1 uv run python experiments/exp_250_ff3_through_vqapr/prepare.py [--data]

`--data` (or a missing work/data/) rebuilds the prepared parquet from the four read-only testbed
files; without it only a missing file is built and the declarations and generated components are
rewritten, so the files the datasets were registered against keep their digests.

Under work/ (gitignored):

- data/prices.parquet       date x ticker, available_at = that session's close (15:30 Asia/Seoul)
- data/listing.parquet      month-end attributes, available_at = that month-end session's close
- data/financials.parquet   annual statements, available_at = fiscal-year end + 3 months
                            (18:00 Asia/Seoul on the last calendar day of that month)
- data/financials_x.parquet the same rows with total_assets and total_liabilities (arm ff3x)
- data/rates.parquet        CD91 and the KOSPI level, grain `instant`, available_at = the close
- data/kospi.parquet        the KOSPI level as an execution table of one instrument, `KOSPI`
- data/instruments_{stock,index}.parquet and instruments.yaml: the roster
- venue.py                  an academic venue listing every instrument the runs may order
- arm ff3:  ff_{s1..b3}.py from strategy_template.py, ff_market.py; datasets.yaml,
            components.yaml, runs.yaml
- arm ff3x: ffx_{s1..b3}.py from strategy_template_x.py; datasets_ff3x.yaml,
            components_ff3x.yaml, runs_ff3x.yaml
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
DATA = WORK / "data"
SRC = HERE.parents[2] / "kwam-enhanced-index" / "vqapr-ff3-testbed" / "data"

START = "2018-07-01T00:00:00+09:00"
MARKET_START = "2018-06-01T00:00:00+09:00"
LEGS = [("S", "1"), ("S", "2"), ("S", "3"), ("B", "1"), ("B", "2"), ("B", "3")]
# arm -> (template, component-id prefix, file prefix, class name)
ARMS = {
    "ff3": ("strategy_template.py", "ff", "ff", "FfLeg"),
    "ff3x": ("strategy_template_x.py", "ffx", "ffx", "FfLegX"),
}
FIN = ["ticker", "fiscal_yyyymm", "total_equity", "noncontrolling_interest", "controlling_equity"]


def seoul(naive: pd.Series) -> pa.Array:
    """Read a naive wall clock AS Seoul time (assume_timezone, not a cast)."""
    arr = pa.array(naive.astype("datetime64[us]").to_numpy(), type=pa.timestamp("us"))
    return pc.assume_timezone(arr, "Asia/Seoul")


def prove_timezone() -> None:
    """register-dataset/references/timezone-proof.md, through the exact code used below."""
    one = seoul(pd.Series(pd.to_datetime(["2024-01-02"])) + pd.Timedelta(hours=15, minutes=30))
    v = one[0].as_py()
    assert v.isoformat() == "2024-01-02T15:30:00+09:00", v
    assert one.cast(pa.timestamp("us", tz="UTC"))[0].as_py().hour == 6
    assert one.cast(pa.timestamp("us", tz="Asia/Seoul"))[0].as_py().hour == 15


def write(table: pd.DataFrame, at: pa.Array, name: str) -> None:
    t = pa.Table.from_pandas(table.reset_index(drop=True), preserve_index=False)  # NaN -> null
    t = t.append_column("available_at", at)
    pq.write_table(t, DATA / name)


def financials(columns: list[str], name: str) -> None:
    fs = pd.read_parquet(SRC / "financials_annual.parquet")
    fy_end = pd.to_datetime(fs["fiscal_yyyymm"].astype(str) + "01") + pd.offsets.MonthEnd(0)
    known = fy_end + pd.offsets.MonthEnd(3) + pd.Timedelta(hours=18)
    write(fs[columns], seoul(known), name)


def build_data() -> None:
    prove_timezone()
    if DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True)

    # prices: the execution table. is_tradable is the halt flag, negated -- a declared rule.
    px = pd.read_parquet(SRC / "prices_daily.parquet")
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["date", "ticker"])
    px["is_tradable"] = ~px["is_trading_halt"]
    cols = ["ticker", "close", "market_cap", "is_trading_halt", "is_tradable"]
    write(px[cols], seoul(px["date"] + pd.Timedelta(hours=15, minutes=30)), "prices.parquet")

    ls = pd.read_parquet(SRC / "listing_monthly.parquet")
    ls["month_end"] = pd.to_datetime(ls["month_end"])
    at = seoul(ls["month_end"] + pd.Timedelta(hours=15, minutes=30))
    write(ls[["ticker", "market", "is_spac", "is_financial"]], at, "listing.parquet")

    financials(FIN, "financials.parquet")

    rt = pd.read_parquet(SRC / "rates_daily.parquet")
    rt["date"] = pd.to_datetime(rt["date"])
    write(rt[["cd91_annual_percent", "kospi_level"]],
          seoul(rt["date"] + pd.Timedelta(hours=15, minutes=30)), "rates.parquet")

    ix = rt.dropna(subset=["kospi_level"]).copy()
    ix = ix[ix["date"].isin(set(px["date"]))]  # the index trades on the same sessions
    kospi = pd.DataFrame({"ticker": "KOSPI", "close": ix["kospi_level"].to_numpy(),
                          "is_tradable": True})
    write(kospi, seoul(ix["date"] + pd.Timedelta(hours=15, minutes=30)), "kospi.parquet")

    # universe: every ticker with a price row inside the run period (and its 14-day lookback)
    live = px[(px["date"] >= "2018-06-01") & (px["date"] <= "2024-12-30")]
    universe = sorted(live["ticker"].unique())
    pq.write_table(pa.table({"instrument_id": universe, "kind": ["stock"] * len(universe)}),
                   DATA / "instruments_stock.parquet")
    pq.write_table(pa.table({"instrument_id": ["KOSPI"], "kind": ["index"]}),
                   DATA / "instruments_index.parquet")
    print(f"universe {len(universe)} tickers; prices {len(px):,} rows; kospi {len(kospi)} rows")


def write_declarations() -> None:
    for p in WORK.iterdir():
        if p.is_file() and p.suffix in (".py", ".yaml"):
            p.unlink()
    universe = pq.read_table(DATA / "instruments_stock.parquet")["instrument_id"].to_pylist()
    (WORK / "instruments.yaml").write_text(
        "instruments:\n  tables:\n    stock: data/instruments_stock.parquet\n"
        "    index: data/instruments_index.parquet\n", encoding="utf-8")

    ids = ",\n".join(f'    "{t}"' for t in [*universe, "KOSPI"])
    (WORK / "venue.py").write_text(VENUE.replace("__IDS__", ids), encoding="utf-8")
    (WORK / "datasets.yaml").write_text(DATASETS, encoding="utf-8")
    (WORK / "datasets_ff3x.yaml").write_text(DATASETS_X, encoding="utf-8")
    uni = "\n".join(f"      - {t}" for t in universe)

    for arm, (template_name, comp_prefix, file_prefix, cls) in ARMS.items():
        template = (HERE / template_name).read_text(encoding="utf-8")
        comps = ["components:"]
        runs = ["runs:"]
        if arm == "ff3":
            comps += ["  ff3-venue:", "    kind: exchange", "    path: venue.py",
                      "    object_name: Venue"]
        for size, bm in LEGS:
            leg = f"{size}{bm}".lower()
            body = re.sub(r'^SIZE = "S"', f'SIZE = "{size}"', template, flags=re.M)
            body = re.sub(r'^BM = "1"', f'BM = "{bm}"', body, flags=re.M)
            (WORK / f"{file_prefix}_{leg}.py").write_text(body, encoding="utf-8")
            comps += [f"  {comp_prefix}-{leg}:", "    kind: strategy",
                      f"    path: {file_prefix}_{leg}.py", f"    object_name: {cls}"]
            runs.append(RUN.format(run=f"{arm}-{leg}", comp=f"{comp_prefix}-{leg}",
                                   start=START, execution="ff-prices", instruments=uni))
        if arm == "ff3":
            shutil.copy(HERE / "market_strategy.py", WORK / "ff_market.py")
            comps += ["  ff-market:", "    kind: strategy", "    path: ff_market.py",
                      "    object_name: FfMarket"]
            runs.append(RUN.format(run="ff3-market", comp="ff-market", start=MARKET_START,
                                   execution="ff-kospi", instruments="      - KOSPI"))
        suffix = "" if arm == "ff3" else f"_{arm}"
        (WORK / f"components{suffix}.yaml").write_text("\n".join(comps) + "\n", encoding="utf-8")
        (WORK / f"runs{suffix}.yaml").write_text("\n".join(runs), encoding="utf-8")


def main() -> None:
    if "--data" in sys.argv or not (DATA / "prices.parquet").exists():
        build_data()
    if not (DATA / "financials_x.parquet").exists():
        financials([*FIN, "total_assets", "total_liabilities"], "financials_x.parquet")
    write_declarations()


VENUE = '''"""Academic venue: every instrument the FF3 runs may order, whole shares, no cost."""

from decimal import Decimal

from vqapr.public import AcademicExchange, TradeRule

IDS = (
__IDS__,
)


def _rule(instrument_id: str) -> TradeRule:
    return TradeRule(
        instrument_id=instrument_id,
        quantity_step=Decimal(1),
        minimum_quantity=Decimal(1),
        fractional_allowed=False,
    )


class Venue(AcademicExchange):
    """Fills every order completely at the venue price, with no cost or slippage."""

    def __init__(self) -> None:
        super().__init__(listings={i: _rule(i) for i in IDS})
'''

DATASETS = """datasets:
  ff-prices:
    source_id: ff-prices-source
    path: data/prices.parquet
    instrument_field: ticker
    available_at: available_at      # the session's close, 15:30 Asia/Seoul
    grain: instrument_instant
    key_fields: [available_at, ticker]
    fields:
      close: close                  # adjusted close; its day-on-day change is the total return
      market_cap: market_cap
      is_trading_halt: is_trading_halt
      is_tradable: is_tradable
    field_types:
      close: DOUBLE
      market_cap: INTEGER
      is_trading_halt: BOOLEAN
      is_tradable: BOOLEAN
    execution:
      is_tradable: is_tradable      # declared rule: a halted session does not fill
  ff-listing:
    source_id: ff-listing-source
    path: data/listing.parquet
    instrument_field: ticker
    available_at: available_at      # the month-end session's close
    grain: instrument_instant
    key_fields: [available_at, ticker]
    fields:
      market: market
      is_spac: is_spac
      is_financial: is_financial
    field_types:
      market: VARCHAR
      is_spac: BOOLEAN
      is_financial: BOOLEAN
  ff-financials:
    source_id: ff-financials-source
    path: data/financials.parquet
    instrument_field: ticker
    available_at: available_at      # fiscal-year end + 3 months (the spec's availability rule)
    grain: instrument_instant
    key_fields: [available_at, ticker]
    fields:
      fiscal_yyyymm: fiscal_yyyymm
      total_equity: total_equity
      noncontrolling_interest: noncontrolling_interest
      controlling_equity: controlling_equity
    field_types:
      fiscal_yyyymm: INTEGER
      total_equity: DOUBLE
      noncontrolling_interest: DOUBLE
      controlling_equity: DOUBLE
  ff-rates:
    source_id: ff-rates-source
    path: data/rates.parquet
    available_at: available_at      # the close, 15:30 Asia/Seoul
    grain: instant
    key_fields: [available_at]
    fields:
      cd91_annual_percent: cd91_annual_percent
      kospi_level: kospi_level
    field_types:
      cd91_annual_percent: DOUBLE
      kospi_level: DOUBLE
  ff-kospi:
    source_id: ff-kospi-source
    path: data/kospi.parquet
    instrument_field: ticker
    available_at: available_at
    grain: instrument_instant
    key_fields: [available_at, ticker]
    fields:
      close: close
      is_tradable: is_tradable
    field_types:
      close: DOUBLE
      is_tradable: BOOLEAN
    execution:
      is_tradable: is_tradable
"""

DATASETS_X = """datasets:
  ff-financials-x:
    source_id: ff-financials-x-source
    path: data/financials_x.parquet
    instrument_field: ticker
    available_at: available_at      # fiscal-year end + 3 months, as ff-financials
    grain: instrument_instant
    key_fields: [available_at, ticker]
    fields:
      fiscal_yyyymm: fiscal_yyyymm
      total_equity: total_equity
      noncontrolling_interest: noncontrolling_interest
      controlling_equity: controlling_equity
      total_assets: total_assets
      total_liabilities: total_liabilities
    field_types:
      fiscal_yyyymm: INTEGER
      total_equity: DOUBLE
      noncontrolling_interest: DOUBLE
      controlling_equity: DOUBLE
      total_assets: DOUBLE
      total_liabilities: DOUBLE
"""

RUN = """  {run}:
    instruments:
{instruments}
    start: "{start}"
    end: "2024-12-30T15:30:00+09:00"
    timezone: Asia/Seoul
    agenda:
      every: 12M
      at: "15:29"
    exchange: ff3-venue
    execution:
      dataset: {execution}
      trade_price: close
      fill:
        at: "15:30"
    initial_account:
      cash: "10000000000000"
      mode: LONG_ONLY
      positions: {{}}
    writes: {run}-weights
    strategy:
      component: {comp}
"""

if __name__ == "__main__":
    main()
