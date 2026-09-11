"""Read the runs' NAV returns back from the record, build RMRF/SMB/HML, compare with Kimchi.

    PYTHONUTF8=1 uv run --with tabulate python experiments/exp_250_ff3_through_vqapr/factors.py [arm]

`arm` is the run-id prefix of the six legs: `ff3` or `ff3x` (default, PRIMARY). Both arms share
the `ff3-market` run.

- each leg's daily return is `strategy_report(store, run_id).performance.returns` (NAV to NAV)
- SMB = mean(S1,S2,S3) - mean(B1,B2,B3); HML = mean(S3,B3) - mean(S1,B1)
- RMRF = the ff3-market run's NAV return (a book holding the KOSPI index) - RF, where RF is
  (1 + cd91/100)^(1/252) - 1 read back from the registered `ff-rates` dataset through
  `vqapr show dataset`
- outputs/factors_<arm>.csv (date,RMRF,SMB,HML; 2018-07-02..2024-12-30), and for PRIMARY also
  outputs/factors.csv; outputs/kimchi_compare_<arm>.{md,json}, names_per_year_<arm>.csv,
  legs_<arm>.csv
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from vqapr.public import read_strategy_table, strategy_report

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
STORE = WORK / ".vqapr"
OUT = HERE / "outputs"
TESTBED = HERE.parents[2] / "kwam-enhanced-index" / "vqapr-ff3-testbed"
LEGS = ["s1", "s2", "s3", "b1", "b2", "b3"]
FIRST, LAST = "2018-07-02", "2024-12-30"
PRIMARY = "ff3x"  # the arm whose factors become outputs/factors.csv (see README, "Result")


def _verify_kimchi():
    spec = importlib.util.spec_from_file_location("verify_kimchi", TESTBED / "tools" / "verify_kimchi.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _days(instants) -> pd.DatetimeIndex:
    return pd.to_datetime([str(i) for i in instants], utc=True).tz_convert("Asia/Seoul").tz_localize(None).normalize()


def nav_returns(run_id: str) -> pd.Series:
    perf = strategy_report(STORE, run_id).performance
    r = pd.Series([float(v) for v in perf.returns.values], index=_days(perf.returns.instants))
    # cross-check: the report's returns are the NAV's day-on-day change
    nav = pd.Series([float(v) for v in perf.nav.values], index=_days(perf.nav.instants))
    assert np.allclose(nav.pct_change().iloc[1:].to_numpy(), r.to_numpy(), atol=1e-12), run_id
    return r[~r.index.duplicated(keep="last")]


def rates() -> pd.DataFrame:
    exe = shutil.which("vqapr")
    env = subprocess.run(
        [exe, "--project-root", str(WORK), "show", "dataset", "ff-rates", "--limit", "5000"],
        capture_output=True, text=True, encoding="utf-8", cwd=WORK,
    )
    if env.returncode != 0:
        raise RuntimeError(f"show dataset exited {env.returncode}\nstdout: {env.stdout[:3000]}"
                           f"\nstderr: {env.stderr[:3000]}")
    doc = json.loads(env.stdout)
    assert doc["ok"] and doc["returned"] == doc["rows_total"], doc.get("rows_total")
    df = pd.DataFrame(doc["items"])
    df.index = _days(df["available_at"])
    return df[["cd91_annual_percent", "kospi_level"]].astype(float)


def names_per_year(arm: str) -> pd.DataFrame:
    ls = pd.read_parquet(WORK / "data" / "listing.parquet", columns=["ticker", "market", "available_at"])
    rows = []
    for leg in LEGS:
        w = pd.DataFrame(read_strategy_table(STORE, f"{arm}-{leg}", "vqapr.weight"))
        w["year"] = _days(w["event_time"]).year
        for year, g in w.groupby("year"):
            june = ls[ls["available_at"].astype(str).str.startswith(f"{year}-06")]
            kospi = set(june.loc[june["market"] == "KOSPI", "ticker"])
            rows.append({"year": year, "leg": leg.upper(), "names": len(g),
                         "kospi": int(g["instrument"].isin(kospi).sum())})
    t = pd.DataFrame(rows)
    wide = t.pivot(index="year", columns="leg", values="names")[[x.upper() for x in LEGS]]
    wide["total"] = wide.sum(axis=1)
    wide["kospi"] = t.groupby("year")["kospi"].sum()
    return wide


def main() -> None:
    arm = sys.argv[1] if len(sys.argv) > 1 else PRIMARY
    sfx = f"_{arm}"
    OUT.mkdir(exist_ok=True)
    legs = pd.DataFrame({leg.upper(): nav_returns(f"{arm}-{leg}") for leg in LEGS})
    mkt = nav_returns("ff3-market")
    rt = rates()
    rf = (1 + rt["cd91_annual_percent"] / 100) ** (1 / 252) - 1

    days = legs.index[(legs.index >= FIRST) & (legs.index <= LAST)]
    f = pd.DataFrame(index=days)
    f["RMRF"] = mkt.reindex(days) - rf.reindex(days)
    f["SMB"] = legs[["S1", "S2", "S3"]].mean(axis=1) - legs[["B1", "B2", "B3"]].mean(axis=1)
    f["HML"] = legs[["S3", "B3"]].mean(axis=1) - legs[["S1", "B1"]].mean(axis=1)
    assert f.notna().all().all(), f[f.isna().any(axis=1)]

    out = f.copy()
    out.index = out.index.strftime("%Y-%m-%d")
    out.index.name = "date"
    out.to_csv(OUT / f"factors{sfx}.csv", float_format="%.10g")
    if arm == PRIMARY:  # the deliverable the testbed's verify_kimchi.py reads
        out.to_csv(OUT / "factors.csv", float_format="%.10g")
    legs.loc[days].to_csv(OUT / f"legs{sfx}.csv", float_format="%.10g")

    # the KOSPI book's NAV return against the index level read back from the registered rates
    kospi_ret = rt["kospi_level"].dropna().pct_change().reindex(days)
    mkt_gap = float((mkt.reindex(days) - kospi_ret).abs().max())

    vk = _verify_kimchi()
    ref = vk.kimchi()
    july_first = [d for d in days if d.month == 7 and d == days[(days.year == d.year) & (days.month == 7)][0]]
    views = {
        "full": days,
        "from 2019-07": days[days >= "2019-07-01"],
        "full, without the 7 July-first days": days.difference(pd.DatetimeIndex(july_first)),
    }
    detail, rows = {}, []
    for view, idx in views.items():
        detail[view] = {}
        for fac in ["RMRF", "SMB", "HML"]:
            c = vk.compare(f.loc[idx, fac], ref[fac])
            detail[view][fac] = c
            rows.append({"view": view, "factor": fac, **c})
    table = pd.DataFrame(rows)
    by_year = []
    for fac in ["RMRF", "SMB", "HML"]:
        j = pd.concat([f[fac].rename("a"), ref[fac].rename("k")], axis=1, sort=True).dropna()
        for y0, g in j.groupby(np.where(j.index.month >= 7, j.index.year, j.index.year - 1)):
            d = g.a - g.k
            by_year.append({"factor": fac, "holding_year": f"{y0}-07..{y0 + 1}-06", "n": len(g),
                            "corr": round(float(g.a.corr(g.k)), 4),
                            "mse_bp2": round(float((d ** 2).mean() * 1e8), 1)})
    by_year = pd.DataFrame(by_year).pivot(index="holding_year", columns="factor", values=["corr", "mse_bp2"])

    counts = names_per_year(arm)
    counts.to_csv(OUT / f"names_per_year{sfx}.csv")

    total = {v: round(sum(detail[v][x]["mse_bp2"] for x in ["RMRF", "SMB", "HML"]), 1) for v in views}
    md = [
        f"# exp_250 arm `{arm}` factors vs published Kimchi factors", "",
        f"days {len(f)}, {out.index[0]} .. {out.index[-1]}; KOSPI book NAV return vs index-level "
        f"return, max |gap| = {mkt_gap:.2e}", "",
        "total MSE (bp^2): " + ", ".join(f"{k}: {v}" for k, v in total.items()), "",
        table.to_markdown(index=False), "",
        "## by holding year", "", by_year.to_markdown(), "",
        "## names per portfolio at each July formation (from vqapr.weight)", "",
        counts.to_markdown(), "",
    ]
    (OUT / f"kimchi_compare{sfx}.md").write_text("\n".join(md), encoding="utf-8")
    (OUT / f"kimchi_compare{sfx}.json").write_text(
        json.dumps({"total_mse_bp2": total, "detail": detail,
                    "kospi_book_vs_index_max_gap": mkt_gap}, indent=2), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
