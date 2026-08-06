import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "tests" / "scenarios" / "data_sources.yaml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_parquet_statistics(frame: pd.DataFrame, contract: dict[str, object]) -> None:
    assert len(frame) == contract["rows"]
    assert frame["date"].nunique() == contract["dates"]
    assert frame["ticker"].nunique() == contract["tickers"]
    assert frame["date"].min().date() == contract["first_date"]
    assert frame["date"].max().date() == contract["last_date"]
    assert frame.duplicated(["date", "ticker"]).sum() == contract["duplicate_keys"]


def test_data_source_audit_is_bound_to_current_files() -> None:
    payload = yaml.safe_load(AUDIT.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["purpose"] == "m6_portfolio_constraint_monitoring_inputs"

    for dataset in payload["datasets"].values():
        for layer_name in ("raw", "preprocessed", "qlibx"):
            layer = dataset[layer_name]
            if layer.get("path") is None:
                continue
            path = ROOT / layer["path"]
            assert path.is_file()
            assert _sha256(path) == layer["sha256"]

        assert dataset["pit"]["status"] in {"user_confirmed", "unresolved"}
        if dataset["pit"]["status"] == "user_confirmed":
            assert dataset["pit"]["confirmed_rule"] == "next_trading_session_at_09_00_kst"
            assert dataset["pit"]["observed_qlibx_rule_status"] == "rejected"
        else:
            assert dataset["pit"]["reason"]
            assert dataset["pit"]["prohibited_claim"]


def test_k200_membership_preprocessed_and_qlibx_projection_are_exact() -> None:
    contract = yaml.safe_load(AUDIT.read_text(encoding="utf-8"))["datasets"][
        "k200_membership"
    ]
    preprocessed = pd.read_parquet(ROOT / contract["preprocessed"]["path"])
    runtime = pd.read_parquet(ROOT / contract["qlibx"]["path"])
    _assert_parquet_statistics(preprocessed, contract["preprocessed"])

    expected = preprocessed[["date", "ticker", "index_weight", "is_k200_member"]]
    actual = runtime[["date", "ticker", "index_weight", "is_k200_member"]]
    pd.testing.assert_frame_equal(
        actual.sort_values(["date", "ticker"]).reset_index(drop=True),
        expected.sort_values(["date", "ticker"]).reset_index(drop=True),
        check_dtype=False,
    )
    assert runtime["available_at"].sub(runtime["date"]).dt.days.eq(-1).all()
    daily = preprocessed.groupby("date")["index_weight"].agg(["sum", "size"])
    assert daily["sum"].min() == contract["preprocessed"]["weight_sum_min"]
    assert daily["sum"].max() == contract["preprocessed"]["weight_sum_max"]
    assert daily["size"].min() == contract["preprocessed"]["members_per_date_min"]
    assert daily["size"].max() == contract["preprocessed"]["members_per_date_max"]


def test_sector_preprocessed_and_qlibx_projection_are_exact() -> None:
    contract = yaml.safe_load(AUDIT.read_text(encoding="utf-8"))["datasets"][
        "sector_classification"
    ]
    preprocessed = pd.read_parquet(ROOT / contract["preprocessed"]["path"])
    runtime = pd.read_parquet(ROOT / contract["qlibx"]["path"])
    _assert_parquet_statistics(preprocessed, contract["preprocessed"])

    expected = preprocessed[["date", "ticker", "industry_code"]]
    actual = runtime[["date", "ticker", "industry_code"]]
    pd.testing.assert_frame_equal(
        actual.sort_values(["date", "ticker"]).reset_index(drop=True),
        expected.sort_values(["date", "ticker"]).reset_index(drop=True),
        check_dtype=False,
    )
    assert runtime["available_at"].sub(runtime["date"]).dt.days.eq(0).all()
    years = preprocessed.assign(year=preprocessed["date"].dt.year).groupby("year")["date"].nunique()
    assert years.loc[2018] == 244
    assert years.loc[2019] == 246
    assert years.loc[2020:2025].eq(12).all()
    assert years.loc[2026] == 4


def test_etf_preprocessed_fields_and_position_factor_are_exact() -> None:
    contract = yaml.safe_load(AUDIT.read_text(encoding="utf-8"))["datasets"][
        "k200_etf_prices"
    ]
    frame = pd.read_parquet(ROOT / contract["preprocessed"]["path"])
    _assert_parquet_statistics(frame, contract["preprocessed"])
    assert frame.select_dtypes(include="number").notna().all().all()

    adjustment = frame.pivot(
        index="date", columns="ticker", values="quantity_adjustment_factor"
    ).astype("float64")
    event_factor = adjustment.mask(adjustment.eq(0.0), 1.0)
    expected = 1.0 / event_factor.iloc[::-1].shift(1).cumprod().iloc[::-1].fillna(1.0)
    actual = frame.pivot(index="date", columns="ticker", values="position_unit_factor").astype(
        "float64"
    )
    assert np.array_equal(actual.to_numpy(), expected.to_numpy())
