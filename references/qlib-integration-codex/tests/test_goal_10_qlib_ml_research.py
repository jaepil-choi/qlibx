from __future__ import annotations

import copy
import hashlib
import json

import numpy as np
import pandas as pd

from qlib.backtest.account import Account
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP

from kwam_qlib_backend.ml_research import (
    MLResearchInputs,
    MLResearchSegments,
    PortableSignalArtifact,
    QlibMLResearchConfig,
    QlibMLResearchPipeline,
)
from kwam_qlib_backend.research_graph import (
    DatasetDefinition,
    DatasetSnapshot,
    NodeDatasetDependency,
    ParquetResearchCatalog,
    ResearchEdge,
    ResearchGraph,
    ResearchNodeSpec,
    StrategyRootSpec,
)


def _inputs(*, future_scale: float = 1.0) -> MLResearchInputs:
    dates = pd.bdate_range("2024-01-02", periods=18)
    index = pd.MultiIndex.from_product(
        [dates, ["A", "B"]], names=["datetime", "instrument"]
    )
    time = np.repeat(np.arange(len(dates), dtype="float64"), 2)
    instrument = np.tile(np.array([-1.0, 1.0]), len(dates))
    feature = pd.DataFrame(
        {"momentum": time + instrument, "quality": 0.5 * time - instrument},
        index=index,
    )
    feature.loc[pd.IndexSlice[dates[8] :, :], :] *= future_scale
    label = pd.DataFrame(
        {"forward_return": 0.02 * time + 0.01 * instrument}, index=index
    )
    universe = pd.DataFrame({"eligible": True}, index=index)
    observation_dates = pd.Series(
        index.get_level_values("datetime") - pd.offsets.BDay(1),
        index=index,
        name="max_observation_date",
    )
    return MLResearchInputs(
        features=feature,
        labels=label,
        universe=universe,
        observation_dates=observation_dates,
    )


def _config() -> QlibMLResearchConfig:
    dates = pd.bdate_range("2024-01-02", periods=18)
    return QlibMLResearchConfig(
        model_id="linear-peer-alpha.v1",
        seed=7,
        segments=MLResearchSegments(
            train=(dates[0], dates[7]),
            valid=(dates[8], dates[12]),
            test=(dates[13], dates[17]),
        ),
        label_horizon=2,
        embargo=1,
        ridge=1e-8,
        code_version="goal-10-contract-v1",
    )


def _graph() -> ResearchGraph:
    return ResearchGraph.compile(
        datasets=[
            DatasetDefinition("ml_features", "PIT ML feature matrix", "1"),
            DatasetDefinition("forward_label", "forward return label", "1"),
            DatasetDefinition("ml_universe", "PIT ML universe", "1"),
        ],
        nodes=[
            ResearchNodeSpec("ml_prediction", "signal", "qlib_linear_model"),
            ResearchNodeSpec(
                "intent",
                "active_intent",
                "normalize",
                input_types={"signal": ("signal",)},
            ),
            ResearchNodeSpec(
                "target",
                "physical_target",
                "intent_tracking_optimizer",
                input_types={"intent": ("active_intent",)},
            ),
        ],
        edges=[
            ResearchEdge("ml_prediction", "intent", "signal", 0),
            ResearchEdge("intent", "target", "intent", 0),
        ],
        dependencies=[
            NodeDatasetDependency(
                "ml_prediction", "ml_features", "feature", 20, "pit_close"
            ),
            NodeDatasetDependency(
                "ml_prediction", "forward_label", "label", 2, "forward_purged"
            ),
            NodeDatasetDependency(
                "ml_prediction", "ml_universe", "universe", 0, "pit_open"
            ),
        ],
        strategy_roots=[StrategyRootSpec("ml-enhanced.v1", "target")],
    )


def _frame_fingerprint(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    digest.update(json.dumps([str(column) for column in frame.columns]).encode())
    return digest.hexdigest()


def _snapshots(inputs: MLResearchInputs | None = None) -> list[DatasetSnapshot]:
    actual = inputs or _inputs()
    feature_hash = _frame_fingerprint(actual.features)
    label_hash = _frame_fingerprint(actual.labels)
    universe_hash = _frame_fingerprint(actual.universe)
    return [
        DatasetSnapshot(
            "ml_features", f"features@{feature_hash[:12]}", "2024-01-25", feature_hash
        ),
        DatasetSnapshot(
            "forward_label", f"labels@{label_hash[:12]}", "2024-01-25", label_hash
        ),
        DatasetSnapshot(
            "ml_universe", f"universe@{universe_hash[:12]}", "2024-01-25", universe_hash
        ),
    ]


def _run(tmp_path, *, inputs: MLResearchInputs | None = None, run_id: str = "ml-run-1"):
    actual_inputs = inputs or _inputs()
    snapshots = _snapshots(actual_inputs)
    graph = _graph()
    catalog = ParquetResearchCatalog(tmp_path / "catalog")
    catalog.publish_graph(graph)
    catalog.register_snapshots(snapshots)
    result = QlibMLResearchPipeline().fit_predict(
        inputs=actual_inputs,
        config=_config(),
        output_dir=tmp_path / run_id,
        graph=graph,
        strategy_id="ml-enhanced.v1",
        model_node_id="ml_prediction",
        snapshots=snapshots,
        run_id=run_id,
        catalog=catalog,
    )
    return result, catalog


def test_actual_qlib_ml_surface_and_train_only_processor_fit(tmp_path) -> None:
    result, _ = _run(tmp_path)
    config = _config()
    raw = _inputs().features
    effective_train_end = config.segments.train[1] - pd.offsets.BDay(
        config.label_horizon
    )
    expected_train = raw.loc[pd.IndexSlice[:effective_train_end, :], :]

    assert isinstance(result.dataset, DatasetH)
    assert isinstance(result.dataset.handler, DataHandlerLP)
    assert result.model.__class__.__mro__[1].__name__ == "Model"
    np.testing.assert_allclose(
        result.processor_audit["mean"], expected_train.mean().to_numpy()
    )
    assert result.processor_audit["fit_end"] == effective_train_end

    altered, _ = _run(
        tmp_path,
        inputs=_inputs(future_scale=1_000.0),
        run_id="ml-run-future-altered",
    )
    np.testing.assert_allclose(
        altered.processor_audit["mean"], result.processor_audit["mean"]
    )


def test_purge_embargo_prediction_axis_and_causality_audit(tmp_path) -> None:
    result, _ = _run(tmp_path)
    config = _config()
    test_start = config.segments.test[0] + pd.offsets.BDay(config.embargo)
    expected = _inputs().features.loc[pd.IndexSlice[test_start :, :], :].index

    assert result.predictions.index.equals(expected)
    assert result.predictions.index.names == ["datetime", "instrument"]
    assert result.effective_segments["train"][1] == (
        config.segments.train[1] - pd.offsets.BDay(config.label_horizon)
    )
    assert result.effective_segments["valid"] == (
        config.segments.valid[0] + pd.offsets.BDay(config.embargo),
        config.segments.valid[1] - pd.offsets.BDay(config.label_horizon),
    )
    assert (
        result.prediction_audit["max_observation_date"]
        < result.prediction_audit["decision_date"]
    ).all()


def test_prediction_is_deterministic_portable_and_lineage_bound(tmp_path) -> None:
    first, catalog = _run(tmp_path, run_id="ml-run-1")
    second, _ = _run(tmp_path, run_id="ml-run-2")

    pd.testing.assert_series_equal(first.predictions, second.predictions)
    assert first.prediction_fingerprint == second.prediction_fingerprint
    portable = PortableSignalArtifact.load(first.signal_path)
    pd.testing.assert_series_equal(portable.predictions, first.predictions)
    assert portable.max_observation_dates.index.equals(first.predictions.index)

    manifest = json.loads(first.model_manifest_path.read_text(encoding="utf-8"))
    assert manifest["model_id"] == "linear-peer-alpha.v1"
    expected_snapshots = {
        snapshot.dataset_id: snapshot.snapshot_id for snapshot in _snapshots()
    }
    assert manifest["dataset_snapshots"] == expected_snapshots
    assert manifest["segments"]["effective"]["test"]
    assert manifest["metrics"]["valid_mse"] >= 0.0
    assert set(catalog.load_table("run_dataset_inputs")["dataset_id"]) == {
        "ml_features",
        "forward_label",
        "ml_universe",
    }


def test_model_research_has_no_actual_qlib_account_side_effect(tmp_path) -> None:
    account = Account(
        init_cash=1_000.0,
        position_dict={"A": {"amount": 3, "price": 10.0}},
        port_metr_enabled=False,
    )
    before = copy.deepcopy(account.current_position.position)

    _run(tmp_path)

    assert account.get_cash() == 1_000.0
    assert account.current_position.position == before
