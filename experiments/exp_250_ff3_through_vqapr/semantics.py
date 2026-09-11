"""What the record says vqapr decided at each rebalance: halts, delistings, clipped buys, drift.

    PYTHONUTF8=1 uv run python experiments/exp_250_ff3_through_vqapr/semantics.py

Per leg and per July rebalance, from vqapr.fill / vqapr.account / vqapr.weight only:

- fills by reason (dealt, nontradable = halted at the fill, absent = no row at the fill,
  no_trade = the plan asked for no change)
- locked: the share of NAV held, just before the rebalance, in names that could not be sold
  (halted or without a row), and so could not fund the new book
- skipped: names in the new target that were not held and got no_trade, and their target weight
- stale: positions whose latest mark is older than the valuation (a delisted name), and their
  share of NAV
- drift: the book's max |realised - intended| weight on the eve of the next rebalance

Writes outputs/semantics.csv and outputs/semantics.md.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from vqapr.public import read_strategy_table

HERE = Path(__file__).resolve().parent
STORE = HERE / "work" / ".vqapr"
OUT = HERE / "outputs"
LEGS = ["s1", "s2", "s3", "b1", "b2", "b3"]


def _day(col: pd.Series) -> pd.Series:
    return pd.to_datetime(col.astype(str), utc=True).dt.tz_convert("Asia/Seoul").dt.strftime("%Y-%m-%d")


def leg_rows(leg: str) -> list[dict]:
    run, ref = f"ff3-{leg}", f"ff-{leg}"
    fill = pd.DataFrame(read_strategy_table(STORE, run, "vqapr.fill", ref))
    acct = pd.DataFrame(read_strategy_table(STORE, run, "vqapr.account", ref))
    wt = pd.DataFrame(read_strategy_table(STORE, run, "vqapr.weight", ref))
    for t in (fill, acct, wt):
        t["day"] = _day(t["event_time"])
    acct["seen"] = _day(acct["observed_at"])
    days = sorted(wt["day"].unique())
    rows = []
    for k, day in enumerate(days):
        before = acct[acct["day"] < day]
        fd = fill[fill["day"] == day]
        tgt = wt[wt["day"] == day].set_index("instrument")["weight"].astype(float)
        row = {"leg": leg.upper(), "rebalance": day, "targets": len(tgt),
               "dealt": int(fd["reason"].isna().sum())}
        for reason in ("nontradable", "absent", "no_trade", "unfunded"):
            row[reason] = int((fd["reason"] == reason).sum())
        if len(before):
            last = before["day"].max()
            snap = before[before["day"] == last]
            nav = float(snap.loc[snap["instrument"] == "_ACCOUNT", "nav"].iloc[0])
            book = snap[snap["instrument"] != "_ACCOUNT"].copy()
            book["value"] = book["quantity"].astype(float) * book["price"].astype(float)
            stuck = set(fd.loc[fd["reason"].isin(["nontradable", "absent"]), "instrument"])
            row["locked_share"] = round(book.loc[book["instrument"].isin(stuck), "value"].sum() / nav, 4)
            held = set(book["instrument"])
            skipped = [i for i in fd.loc[fd["reason"] == "no_trade", "instrument"] if i not in held]
            row["skipped_new"] = len(skipped)
            row["skipped_target"] = round(float(tgt.reindex(skipped).sum()), 4)
            stale = book[book["seen"] < last]
            row["stale_positions"] = len(stale)
            row["stale_share"] = round(stale["value"].sum() / nav, 4)
            # drift: the book on the eve of this rebalance against the previous target
            prev = wt[wt["day"] == days[k - 1]].set_index("instrument")["weight"].astype(float)
            real = (book.set_index("instrument")["value"] / nav)
            both = pd.concat([real.rename("r"), prev.rename("i")], axis=1).fillna(0.0)
            row["eve_max_drift"] = round(float((both.r - both.i).abs().max()), 4)
            row["eve_sum_abs_drift"] = round(float((both.r - both.i).abs().sum()), 4)
        rows.append(row)
    return rows


def main() -> None:
    OUT.mkdir(exist_ok=True)
    t = pd.DataFrame([r for leg in LEGS for r in leg_rows(leg)])
    t.to_csv(OUT / "semantics.csv", index=False)
    md = ["# What vqapr decided at each rebalance (from the record)", "",
          "locked_share / stale_share are shares of NAV on the eve of the rebalance; "
          "eve_*_drift compares that book with the previous July's target.", "",
          t.to_markdown(index=False), ""]
    (OUT / "semantics.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
