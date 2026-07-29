from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from qlibx.cli import dispatch, parser
from qlibx.errors import QlibxError
from qlibx.project import Project
from qlibx.strategy_manifest import (
    invoke_pandas_strategy,
    load_strategy_binding,
    load_strategy_callable,
    load_strategy_manifest,
    plan_strategy_binding,
    resolve_strategy_inputs,
    run_manifest_strategy_execution,
)


def _project(tmp_path: Path) -> Project:
    project = Project.initialize(tmp_path)
    config = project.paths.config
    (config / "data" / "datasets").mkdir(parents=True)
    (config / "strategies").mkdir()
    (config / "bindings").mkdir()
    (project.paths.extensions / "strategies").mkdir(parents=True)

    dates = pd.date_range("2024-01-01", periods=5, name="date")
    rows = [
        {
            "available_at": date,
            "date": date,
            "ticker": ticker,
            "시가": float(position + offset),
            "종가": float(position + offset + 1),
            "in_universe": True,
        }
        for position, date in enumerate(dates, start=10)
        for ticker, offset in (("A", 0), ("B", 10))
    ]
    pd.DataFrame(rows).to_parquet(project.paths.generated_data / "daily.parquet", index=False)
    (config / "data" / "base.yaml").write_text(
        """schema_version: 1
paths:
  canonical: data/qlibx
catalog:
  source_file: sources.yaml
  dataset_files: [datasets/strategy.yaml]
""",
        encoding="utf-8",
    )
    (config / "data" / "sources.yaml").write_text(
        """parquet_sources:
  daily:
    root: canonical
    path: daily.parquet
""",
        encoding="utf-8",
    )
    (config / "data" / "datasets" / "strategy.yaml").write_text(
        """datasets:
  krx_daily_ohlcv:
    kind: table
    sources: [daily]
    query: |
      select available_at, date, ticker, 시가, 종가 from daily
    time_field: date
    availability_field: available_at
  krx_daily_universe:
    kind: matrix
    sources: [daily]
    query: |
      select available_at, date, ticker, in_universe from daily
    index: date
    columns: ticker
    values: in_universe
    time_field: date
    availability_field: available_at
    dtype: bool
""",
        encoding="utf-8",
    )
    (config / "strategies" / "open_close_rebound.yaml").write_text(
        """schema_version: 1
contract: qlibx.pandas_strategy
strategy:
  id: open_close_rebound
  version: "1"
  name: Open Close Rebound
  implementation:
    source: strategies/open_close_rebound.py
    callable: decide
  parameters:
    rebound_threshold: 0.02
  lookback: {kind: rows, value: 2}
  inputs:
    market_data:
      meaning: Daily market prices.
      pandas:
        kind: table
        index: [date, ticker]
      fields:
        open_price:
          meaning: Session open price.
          dtype: float64
          unit: price
          nullable: false
        close_price:
          meaning: Session close price.
          dtype: float64
          unit: price
          nullable: false
  output: {kind: weight}
""",
        encoding="utf-8",
    )
    (config / "bindings" / "open_close_rebound.krx.yaml").write_text(
        """schema_version: 1
binding:
  id: open_close_rebound.krx
  strategy: {id: open_close_rebound, version: "1"}
  inputs:
    universe:
      registered_dataset: krx_daily_universe
    market_data:
      registered_dataset: krx_daily_ohlcv
      fields:
        open_price: 시가
        close_price: 종가
""",
        encoding="utf-8",
    )
    (project.paths.extensions / "strategies" / "open_close_rebound.py").write_text(
        """def child_rebound(*, market_data):
    return market_data["close_price"] - market_data["open_price"]


def decide(*, universe, market_data, rebound_threshold):
    observed = child_rebound(market_data=market_data)
    signal = observed.unstack("ticker")
    return signal.where(universe.reindex_like(signal), 0.0) * rebound_threshold
""",
        encoding="utf-8",
    )
    return project


def test_manifest_inherits_universe_and_unbound_plan_reports_inventory(tmp_path: Path) -> None:
    project = _project(tmp_path)
    manifest = load_strategy_manifest(project, "open_close_rebound")

    assert [item.role for item in manifest.all_inputs] == ["universe", "market_data"]
    assert manifest.all_inputs[0].inherited is True
    plan = plan_strategy_binding(project, manifest)
    assert plan.ready is False
    assert plan.resolution.missing_requirements == ("input.market_data", "input.universe")
    inventory = plan.parameters["registered_field_inventory"]
    assert {"시가", "종가"} <= set(inventory["krx_daily_ohlcv"]["fields"])
    assert "user_questions" not in plan.resolution.to_dict()


def test_binding_resolves_fixed_lookback_and_invokes_plain_pandas_strategy(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    manifest = load_strategy_manifest(project, "open_close_rebound")
    binding = load_strategy_binding(project, "open_close_rebound.krx")

    assert plan_strategy_binding(project, manifest, binding).ready is True
    resolved = resolve_strategy_inputs(
        project,
        manifest,
        binding,
        decision_time="2024-01-04",
    )
    market = resolved.inputs["market_data"]
    assert list(market.columns) == ["open_price", "close_price"]
    assert set(market.index.get_level_values("date")) == {
        pd.Timestamp("2024-01-03"),
        pd.Timestamp("2024-01-04"),
    }
    assert resolved.inputs["universe"].index.max() == pd.Timestamp("2024-01-04")
    result = invoke_pandas_strategy(
        manifest,
        resolved,
        load_strategy_callable(project, manifest),
    )
    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == ["A", "B"]


def test_registered_availability_allows_known_future_event_time(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project.paths.generated_data / "daily.parquet"
    existing = pd.read_parquet(source)
    future = pd.DataFrame(
        [
            {
                "available_at": pd.Timestamp("2024-01-04"),
                "date": pd.Timestamp("2024-02-01"),
                "ticker": ticker,
                "시가": 20.0,
                "종가": 21.0,
                "in_universe": True,
            }
            for ticker in ("A", "B")
        ]
    )
    pd.concat([existing, future], ignore_index=True).to_parquet(source, index=False)
    manifest = load_strategy_manifest(project, "open_close_rebound")
    binding = load_strategy_binding(project, "open_close_rebound.krx")

    resolved = resolve_strategy_inputs(
        project,
        manifest,
        binding,
        decision_time="2024-01-04",
    )
    dates = resolved.inputs["market_data"].index.get_level_values("date")
    assert dates.max() == pd.Timestamp("2024-02-01")


def test_universe_requires_explicit_membership_for_every_matrix_cell(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project.paths.generated_data / "daily.parquet"
    data = pd.read_parquet(source)
    incomplete = data.loc[~((data["date"] == pd.Timestamp("2024-01-04")) & (data["ticker"] == "B"))]
    incomplete.to_parquet(source, index=False)
    manifest = load_strategy_manifest(project, "open_close_rebound")
    binding = load_strategy_binding(project, "open_close_rebound.krx")

    with pytest.raises(QlibxError) as captured:
        resolve_strategy_inputs(
            project,
            manifest,
            binding,
            decision_time="2024-01-04",
        )
    assert captured.value.code == "QLIBX_STRATEGY_UNIVERSE_NULL"


def test_strategy_cli_exposes_requirements_plan_and_preview(tmp_path: Path, capsys) -> None:
    project = _project(tmp_path)
    command = parser()
    common = ["--root", str(project.root), "--strategy", "open_close_rebound"]

    assert dispatch(command.parse_args(["strategy", "requirements", *common])) == 0
    assert (
        dispatch(
            command.parse_args(["strategy", "plan", *common, "--binding", "open_close_rebound.krx"])
        )
        == 0
    )
    assert (
        dispatch(
            command.parse_args(
                [
                    "strategy",
                    "preview",
                    *common,
                    "--binding",
                    "open_close_rebound.krx",
                    "--decision-time",
                    "2024-01-04",
                ]
            )
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"role": "universe"' in output
    assert '"ready": true' in output
    assert '"open_price"' in output


def test_manifest_strategy_runs_in_qlib_decision_loop(tmp_path: Path) -> None:
    project = _project(tmp_path)
    manifest = load_strategy_manifest(project, "open_close_rebound")
    binding = load_strategy_binding(project, "open_close_rebound.krx")
    dates = pd.date_range("2024-01-01", periods=5)
    columns = ["A", "B"]
    price = pd.DataFrame(100.0, index=dates, columns=columns)
    universe = pd.DataFrame(True, index=dates, columns=columns)
    volume = pd.DataFrame(1_000_000.0, index=dates, columns=columns)

    result = run_manifest_strategy_execution(
        project,
        manifest,
        binding,
        execution_price=price,
        valuation_price=price,
        universe=universe,
        volume=volume,
        initial_cash=1_000_000.0,
    )
    assert len(result.decisions) == len(dates)
    assert all(
        decision.diagnostics["binding_id"] == "open_close_rebound.krx"
        for decision in result.decisions
    )
