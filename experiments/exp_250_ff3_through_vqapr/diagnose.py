"""Where the gap to Kimchi comes from: vqapr's execution, the one-day timing, or the definition.

    PYTHONUTF8=1 uv run --with tabulate python experiments/exp_250_ff3_through_vqapr/diagnose.py [arm]

A diagnostic, not a second pipeline. It takes each leg's membership from vqapr's own record
(`vqapr.weight` at each July decision) and recomputes the leg the way a pandas script does:
value-weighted by the previous session's market cap, over the members that have a return that
day (a delisted name simply drops out, its weight going to the rest). Two timings:

- pandas, Kimchi timing: held from the first July session's return on (formed at June's close)
- pandas, vqapr timing:  held from the session after the fill (the book vqapr can actually hold)

Then:
- vqapr vs pandas-vqapr-timing   = what vqapr's execution decided (share drift instead of
  market-cap reweighting, halted names that could not be bought or sold, delisted names frozen
  at their last price, buys clipped when unsellable holdings could not fund them)
- pandas-vqapr vs pandas-Kimchi   = the one-day formation lag
- pandas-Kimchi vs Kimchi         = the definition and the data (membership, BE, breakpoints)

`arm` is the run-id prefix: `ff3` (default) or another arm's prefix.
Writes outputs/decomposition_<arm>.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from vqapr.public import read_strategy_table

HERE = Path(__file__).resolve().parent
STORE = HERE / "work" / ".vqapr"
OUT = HERE / "outputs"
TESTBED = HERE.parents[2] / "kwam-enhanced-index" / "vqapr-ff3-testbed"
LEGS = ["s1", "s2", "s3", "b1", "b2", "b3"]
FIRST, LAST = "2018-07-02", "2024-12-30"


def factors(legs: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "SMB": legs[["S1", "S2", "S3"]].mean(axis=1) - legs[["B1", "B2", "B3"]].mean(axis=1),
        "HML": legs[["S3", "B3"]].mean(axis=1) - legs[["S1", "B1"]].mean(axis=1),
    })


def mse(a: pd.Series, b: pd.Series) -> tuple[float, float]:
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1, sort=True).dropna()
    d = j.a - j.b
    return round(float((d ** 2).mean() * 1e8), 1), round(float(j.a.corr(j.b)), 4)


def main() -> None:
    arm = sys.argv[1] if len(sys.argv) > 1 else "ff3"
    sys.path.insert(0, str(TESTBED / "tools"))
    import verify_kimchi

    px = pd.read_parquet(TESTBED / "data" / "prices_daily.parquet",
                         columns=["date", "ticker", "ret", "market_cap"])
    px["date"] = pd.to_datetime(px["date"])
    ret = px.pivot(index="date", columns="ticker", values="ret")
    cap = px.pivot(index="date", columns="ticker", values="market_cap").astype(float).shift(1)
    sessions = ret.index[(ret.index >= FIRST) & (ret.index <= LAST)]

    kimchi_t, vqapr_t = {}, {}
    for leg in LEGS:
        w = pd.DataFrame(read_strategy_table(STORE, f"{arm}-{leg}", "vqapr.weight"))
        w["day"] = pd.to_datetime(w["event_time"].astype(str), utc=True).dt.tz_convert(
            "Asia/Seoul").dt.tz_localize(None).dt.normalize()
        decisions = sorted(w["day"].unique())
        rk = pd.Series(np.nan, index=sessions)
        rv = pd.Series(np.nan, index=sessions)
        for k, d in enumerate(decisions):
            members = [m for m in w.loc[w["day"] == d, "instrument"] if m in ret.columns]
            nxt = decisions[k + 1] if k + 1 < len(decisions) else pd.Timestamp("2100-01-01")
            r, c = ret[members], cap[members]
            ok = r.notna() & c.notna() & (c > 0)
            vw = (r.where(ok) * c.where(ok)).sum(axis=1) / c.where(ok).sum(axis=1)
            kd = sessions[(sessions >= d) & (sessions < nxt)]
            vd = sessions[(sessions > d) & (sessions <= nxt)]
            rk.loc[kd] = vw.reindex(kd).to_numpy()
            rv.loc[vd] = vw.reindex(vd).to_numpy()
        kimchi_t[leg.upper()] = rk
        vqapr_t[leg.upper()] = rv.fillna(0.0)  # before the first fill vqapr holds cash

    legs = pd.read_csv(OUT / f"legs_{arm}.csv", index_col=0, parse_dates=True)
    fv = factors(legs)
    fpk = factors(pd.DataFrame(kimchi_t))
    fpv = factors(pd.DataFrame(vqapr_t))
    ref = verify_kimchi.kimchi()

    rows = []
    for view, lo in (("full", FIRST), ("from 2019-07", "2019-07-01")):
        for fac in ("SMB", "HML"):
            def cut(s: pd.Series, lo: str = lo) -> pd.Series:
                return s[s.index >= lo]

            rows.append({
                "view": view, "factor": fac,
                "vqapr vs Kimchi (mse, corr)": mse(cut(fv[fac]), ref[fac]),
                "vqapr vs pandas-vqapr-timing": mse(cut(fv[fac]), cut(fpv[fac])),
                "pandas-vqapr vs pandas-Kimchi timing": mse(cut(fpv[fac]), cut(fpk[fac])),
                "pandas-Kimchi-timing vs Kimchi": mse(cut(fpk[fac]), ref[fac]),
            })
    year_rows = []
    hy = np.where(fv.index.month >= 7, fv.index.year, fv.index.year - 1)
    for y0 in sorted(set(hy)):
        idx = fv.index[hy == y0]
        row = {"holding_year": f"{y0}-07..{y0 + 1}-06"}
        for fac in ("SMB", "HML"):
            row[f"{fac} vqapr vs Kimchi"] = mse(fv.loc[idx, fac], ref[fac])[0]
            row[f"{fac} vqapr vs pandas-vqapr"] = mse(fv.loc[idx, fac], fpv.loc[idx, fac])[0]
            row[f"{fac} pandas-Kimchi vs Kimchi"] = mse(fpk.loc[idx, fac], ref[fac])[0]
        year_rows.append(row)
    leg_rows = []
    for leg in [x.upper() for x in LEGS]:
        leg_rows.append({"leg": leg,
                         "vqapr vs pandas-vqapr-timing (mse bp2, corr)": mse(legs[leg], pd.Series(vqapr_t[leg])),
                         "vqapr ann. mean": round(float(legs[leg].mean() * 252), 4),
                         "pandas-vqapr-timing ann. mean": round(float(pd.Series(vqapr_t[leg]).mean() * 252), 4)})
    md = [f"# Decomposing the gap to Kimchi (arm `{arm}`)", "",
          "Each cell is (MSE in bp^2, correlation) of daily returns.", "",
          pd.DataFrame(rows).to_markdown(index=False), "",
          "## by holding year (MSE in bp^2)", "",
          pd.DataFrame(year_rows).to_markdown(index=False), "",
          "## per leg: vqapr's NAV return against the same membership computed the pandas way", "",
          pd.DataFrame(leg_rows).to_markdown(index=False), ""]
    OUT.mkdir(exist_ok=True)
    (OUT / f"decomposition_{arm}.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
