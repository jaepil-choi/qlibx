from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import qlib
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP
from qlib.data.dataset.loader import StaticDataLoader
from qlib.data.dataset.processor import Processor, ZScoreNorm
from qlib.model.base import Model

from .research_graph import (
    DatasetSnapshot,
    ParquetResearchCatalog,
    ResearchGraph,
)


@dataclass(frozen=True)
class MLResearchInputs:
    features: pd.DataFrame
    labels: pd.DataFrame
    universe: pd.DataFrame
    observation_dates: pd.Series


@dataclass(frozen=True)
class MLResearchSegments:
    train: tuple[Any, Any]
    valid: tuple[Any, Any]
    test: tuple[Any, Any]


@dataclass(frozen=True)
class QlibMLResearchConfig:
    model_id: str
    seed: int
    segments: MLResearchSegments
    label_horizon: int
    embargo: int
    ridge: float = 1e-8
    code_version: str = "unknown"


@dataclass(frozen=True)
class PortableSignalArtifact:
    predictions: pd.Series
    max_observation_dates: pd.Series

    @classmethod
    def load(cls, path: Path) -> PortableSignalArtifact:
        table = pd.read_parquet(path)
        required = {"signal_value", "max_observation_date"}
        if not required <= set(table.columns):
            raise ValueError("portable signal artifact schema is invalid")
        if table.index.names != ["datetime", "instrument"]:
            raise ValueError("portable signal artifact index contract is invalid")
        return cls(
            predictions=table["signal_value"].rename("signal_value"),
            max_observation_dates=table["max_observation_date"].rename(
                "max_observation_date"
            ),
        )


@dataclass(frozen=True)
class MLResearchResult:
    predictions: pd.Series
    prediction_audit: pd.DataFrame
    prediction_fingerprint: str
    signal_path: Path
    model_manifest_path: Path
    model: DeterministicLinearModel
    dataset: DatasetH
    processor_audit: Mapping[str, Any]
    effective_segments: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]]


class _UniverseFilter(Processor):
    def __call__(self, frame: pd.DataFrame) -> pd.DataFrame:
        column = ("universe", "eligible")
        if column not in frame.columns:
            raise ValueError("Qlib ML input is missing universe.eligible")
        eligible = frame[column]
        if eligible.isna().any():
            raise ValueError("Qlib ML universe contains missing eligibility")
        return frame.loc[eligible.astype(bool)].copy()

    def readonly(self) -> bool:
        return True


class DeterministicLinearModel(Model):
    """Small deterministic ridge model implemented through Qlib's Model contract."""

    def __init__(self, *, ridge: float, seed: int) -> None:
        if not np.isfinite(ridge) or ridge < 0:
            raise ValueError("ridge must be finite and non-negative")
        self.ridge = float(ridge)
        self.seed = int(seed)
        self.feature_names: tuple[str, ...] = ()
        self.coefficients: np.ndarray | None = None
        self.metrics: dict[str, float] = {}

    def fit(self, dataset: DatasetH, reweighter: Any = None) -> None:
        del reweighter
        train = dataset.prepare(
            "train", col_set=["feature", "label"], data_key=DataHandlerLP.DK_L
        )
        valid = dataset.prepare(
            "valid", col_set=["feature", "label"], data_key=DataHandlerLP.DK_L
        )
        train_x, train_y = _model_arrays(train)
        if train_x.empty:
            raise ValueError("Qlib ML effective train segment has no finite rows")
        self.feature_names = tuple(str(column) for column in train_x.columns)
        design = np.column_stack(
            [np.ones(len(train_x), dtype="float64"), train_x.to_numpy(dtype="float64")]
        )
        penalty = np.eye(design.shape[1], dtype="float64") * self.ridge
        penalty[0, 0] = 0.0
        lhs = design.T @ design + penalty
        rhs = design.T @ train_y.to_numpy(dtype="float64")
        self.coefficients = np.linalg.pinv(lhs) @ rhs

        valid_x, valid_y = _model_arrays(valid)
        if valid_x.empty:
            raise ValueError("Qlib ML effective valid segment has no finite rows")
        valid_prediction = self._predict_frame(valid_x)
        self.metrics = {
            "valid_mse": float(
                np.mean(
                    np.square(
                        valid_prediction.to_numpy()
                        - valid_y.to_numpy(dtype="float64")
                    )
                )
            )
        }

    def predict(
        self, dataset: DatasetH, segment: str | slice = "test"
    ) -> pd.Series:
        frame = dataset.prepare(
            segment, col_set="feature", data_key=DataHandlerLP.DK_I
        )
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("Qlib DatasetH feature segment must be a DataFrame")
        if frame.isna().any().any():
            raise ValueError("Qlib ML prediction features contain missing values")
        return self._predict_frame(frame).rename("signal_value")

    def _predict_frame(self, features: pd.DataFrame) -> pd.Series:
        if self.coefficients is None:
            raise ValueError("Qlib model must be fitted before predict")
        actual_names = tuple(str(column) for column in features.columns)
        if actual_names != self.feature_names:
            raise ValueError("Qlib ML prediction feature schema differs from train")
        design = np.column_stack(
            [
                np.ones(len(features), dtype="float64"),
                features.to_numpy(dtype="float64"),
            ]
        )
        return pd.Series(design @ self.coefficients, index=features.index)


class QlibMLResearchPipeline:
    """Actual Qlib ML data/model path with causal and lineage enforcement."""

    def fit_predict(
        self,
        *,
        inputs: MLResearchInputs,
        config: QlibMLResearchConfig,
        output_dir: Path,
        graph: ResearchGraph,
        strategy_id: str,
        model_node_id: str,
        snapshots: Iterable[DatasetSnapshot],
        run_id: str,
        catalog: ParquetResearchCatalog,
    ) -> MLResearchResult:
        _validate_config(config)
        _validate_inputs(inputs)
        snapshot_list = tuple(snapshots)
        _validate_snapshot_content(graph, model_node_id, inputs, snapshot_list)
        calendar = pd.DatetimeIndex(
            inputs.features.index.get_level_values("datetime").unique()
        ).sort_values()
        effective = _effective_segments(config, calendar)

        loader = StaticDataLoader(
            {
                "feature": inputs.features.copy(),
                "label": inputs.labels.copy(),
                "universe": inputs.universe.copy(),
            }
        )
        normalizer = ZScoreNorm(
            fit_start_time=effective["train"][0],
            fit_end_time=effective["train"][1],
            fields_group="feature",
        )
        handler = DataHandlerLP(
            data_loader=loader,
            shared_processors=[_UniverseFilter()],
            infer_processors=[normalizer],
        )
        dataset = DatasetH(handler=handler, segments=effective)
        model = DeterministicLinearModel(ridge=config.ridge, seed=config.seed)
        model.fit(dataset)
        predictions = model.predict(dataset, "test")
        if predictions.index.names != ["datetime", "instrument"]:
            raise ValueError("Qlib prediction index contract differs from ML input")

        observation_dates = inputs.observation_dates.loc[predictions.index]
        decision_dates = pd.Series(
            predictions.index.get_level_values("datetime"), index=predictions.index
        )
        if not (observation_dates < decision_dates).all():
            raise ValueError(
                "Qlib ML prediction violates max_observation_date < decision_date"
            )
        prediction_audit = pd.DataFrame(
            {
                "decision_date": decision_dates.to_numpy(),
                "instrument": predictions.index.get_level_values("instrument"),
                "max_observation_date": observation_dates.to_numpy(),
            },
            index=predictions.index,
        )

        signal_table = pd.DataFrame(
            {
                "signal_value": predictions,
                "max_observation_date": observation_dates,
            },
            index=predictions.index,
        )
        prediction_fingerprint = dataframe_fingerprint(signal_table)
        output_root = Path(output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        signal_path = output_root / "prediction_signal.parquet"
        _write_parquet_atomic(signal_table, signal_path)

        root = graph.strategy_root(strategy_id)
        if model_node_id not in set(
            graph.strategy_dataset_dependencies(strategy_id)["node_id"]
        ):
            raise ValueError("ML model node is not reachable from strategy root")
        resolved_inputs = graph.resolve_run_inputs(
            run_id, strategy_id, snapshot_list
        )
        dataset_snapshots = {
            str(row.dataset_id): str(row.snapshot_id)
            for row in resolved_inputs.itertuples(index=False)
        }
        model_definition_hash = _definition_hash(
            {
                "model_class": type(model).__name__,
                "model_id": config.model_id,
                "ridge": config.ridge,
                "seed": config.seed,
                "features": model.feature_names,
                "research_node_definition_hash": graph.node(
                    model_node_id
                ).definition_hash,
            }
        )
        manifest = {
            "model_id": config.model_id,
            "model_definition_hash": model_definition_hash,
            "strategy_id": strategy_id,
            "strategy_definition_hash": root.definition_hash,
            "research_node_id": model_node_id,
            "research_node_definition_hash": graph.node(
                model_node_id
            ).definition_hash,
            "seed": config.seed,
            "code_version": config.code_version,
            "library_versions": {
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "pyqlib": getattr(qlib, "__version__", "unknown"),
            },
            "segments": {
                "requested": _segments_json(config.segments),
                "effective": _segments_json(effective),
                "label_horizon": config.label_horizon,
                "embargo": config.embargo,
            },
            "dataset_snapshots": dataset_snapshots,
            "processor": {
                "class": type(normalizer).__name__,
                "fit_start": pd.Timestamp(normalizer.fit_start_time).isoformat(),
                "fit_end": pd.Timestamp(normalizer.fit_end_time).isoformat(),
                "mean": normalizer.mean_train.tolist(),
                "std": normalizer.std_train.tolist(),
            },
            "metrics": model.metrics,
            "prediction_artifact": {
                "relative_path": signal_path.name,
                "content_fingerprint": prediction_fingerprint,
                "row_count": len(signal_table),
            },
        }
        manifest_path = output_root / "model_manifest.json"
        _write_json_atomic(manifest, manifest_path)

        catalog.bind_run_inputs(
            graph, run_id, strategy_id, snapshot_list
        )
        processor_audit = {
            "fit_start": pd.Timestamp(normalizer.fit_start_time),
            "fit_end": pd.Timestamp(normalizer.fit_end_time),
            "mean": normalizer.mean_train.copy(),
            "std": normalizer.std_train.copy(),
        }
        return MLResearchResult(
            predictions=predictions,
            prediction_audit=prediction_audit,
            prediction_fingerprint=prediction_fingerprint,
            signal_path=signal_path,
            model_manifest_path=manifest_path,
            model=model,
            dataset=dataset,
            processor_audit=processor_audit,
            effective_segments=effective,
        )


def dataframe_fingerprint(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    digest.update(json.dumps([str(column) for column in frame.columns]).encode())
    return digest.hexdigest()


def _validate_inputs(inputs: MLResearchInputs) -> None:
    frames = {
        "features": inputs.features,
        "labels": inputs.labels,
        "universe": inputs.universe,
    }
    expected_index = inputs.features.index
    if not isinstance(expected_index, pd.MultiIndex) or expected_index.names != [
        "datetime",
        "instrument",
    ]:
        raise ValueError(
            "Qlib ML inputs require MultiIndex named datetime, instrument"
        )
    if not expected_index.is_unique or not expected_index.is_monotonic_increasing:
        raise ValueError("Qlib ML input index must be unique and sorted")
    for name, frame in frames.items():
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError(f"Qlib ML {name} must be a non-empty DataFrame")
        if not frame.index.equals(expected_index):
            raise ValueError(f"Qlib ML {name} index differs from features")
    if inputs.features.columns.empty or inputs.labels.shape[1] != 1:
        raise ValueError("Qlib ML requires features and exactly one label column")
    if list(inputs.universe.columns) != ["eligible"]:
        raise ValueError("Qlib ML universe must have exactly the eligible column")
    if not pd.api.types.is_bool_dtype(inputs.universe["eligible"].dtype):
        raise ValueError("Qlib ML universe eligibility must be boolean")
    if inputs.features.isna().any().any() or not np.isfinite(
        inputs.features.to_numpy(dtype="float64")
    ).all():
        raise ValueError("Qlib ML features must be finite")
    if inputs.labels.isna().any().any() or not np.isfinite(
        inputs.labels.to_numpy(dtype="float64")
    ).all():
        raise ValueError("Qlib ML labels must be finite")
    if inputs.universe.isna().any().any():
        raise ValueError("Qlib ML universe must not contain missing values")
    if not inputs.observation_dates.index.equals(expected_index):
        raise ValueError("Qlib ML observation_dates index differs from features")
    observations = pd.to_datetime(inputs.observation_dates)
    decisions = pd.Series(
        expected_index.get_level_values("datetime"), index=expected_index
    )
    if observations.isna().any() or not (observations < decisions).all():
        raise ValueError(
            "Qlib ML inputs require max_observation_date < decision_date"
        )


def _validate_config(config: QlibMLResearchConfig) -> None:
    if not config.model_id.strip() or not config.code_version.strip():
        raise ValueError("model_id and code_version must be non-empty")
    if not isinstance(config.seed, int):
        raise ValueError("ML seed must be an integer")
    if not isinstance(config.label_horizon, int) or config.label_horizon < 0:
        raise ValueError("label_horizon must be a non-negative integer")
    if not isinstance(config.embargo, int) or config.embargo < 0:
        raise ValueError("embargo must be a non-negative integer")
    if not np.isfinite(config.ridge) or config.ridge < 0:
        raise ValueError("ridge must be finite and non-negative")


def _effective_segments(
    config: QlibMLResearchConfig, calendar: pd.DatetimeIndex
) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    requested = {
        name: tuple(pd.Timestamp(value) for value in getattr(config.segments, name))
        for name in ("train", "valid", "test")
    }
    for name, (start, end) in requested.items():
        if start > end:
            raise ValueError(f"ML {name} segment start is after end")
        if start not in calendar or end not in calendar:
            raise ValueError(f"ML {name} boundaries must exist in dataset calendar")
    if not (
        requested["train"][1]
        < requested["valid"][0]
        <= requested["valid"][1]
        < requested["test"][0]
    ):
        raise ValueError("ML train/valid/test segments must be ordered and disjoint")

    effective = {
        "train": (
            requested["train"][0],
            _calendar_shift(calendar, requested["train"][1], -config.label_horizon),
        ),
        "valid": (
            _calendar_shift(calendar, requested["valid"][0], config.embargo),
            _calendar_shift(calendar, requested["valid"][1], -config.label_horizon),
        ),
        "test": (
            _calendar_shift(calendar, requested["test"][0], config.embargo),
            requested["test"][1],
        ),
    }
    for name, (start, end) in effective.items():
        if start > end:
            raise ValueError(f"purge/embargo leaves empty ML {name} segment")
    return effective


def _calendar_shift(
    calendar: pd.DatetimeIndex, value: pd.Timestamp, offset: int
) -> pd.Timestamp:
    position = int(calendar.get_loc(value)) + offset
    if position < 0 or position >= len(calendar):
        raise ValueError("purge/embargo extends beyond ML dataset calendar")
    return pd.Timestamp(calendar[position])


def _validate_snapshot_content(
    graph: ResearchGraph,
    model_node_id: str,
    inputs: MLResearchInputs,
    snapshots: tuple[DatasetSnapshot, ...],
) -> None:
    dependency_table = graph.tables()["node_dataset_dependencies"]
    dependencies = dependency_table.loc[
        dependency_table["node_id"].eq(model_node_id)
    ]
    role_to_dataset: dict[str, str] = {}
    for role in ("feature", "label", "universe"):
        matches = dependencies.loc[dependencies["role"].eq(role), "dataset_id"]
        if len(matches) != 1:
            raise ValueError(
                f"ML node requires exactly one {role} dataset dependency"
            )
        role_to_dataset[role] = str(matches.iloc[0])
    snapshot_map = {snapshot.dataset_id: snapshot for snapshot in snapshots}
    if len(snapshot_map) != len(snapshots):
        raise ValueError("ML dataset snapshots contain duplicate dataset identities")
    actual_fingerprints = {
        "feature": dataframe_fingerprint(inputs.features),
        "label": dataframe_fingerprint(inputs.labels),
        "universe": dataframe_fingerprint(inputs.universe),
    }
    for role, dataset_id in role_to_dataset.items():
        if dataset_id not in snapshot_map:
            raise ValueError(f"ML input snapshot is missing: {dataset_id}")
        if snapshot_map[dataset_id].content_fingerprint != actual_fingerprints[role]:
            raise ValueError(
                f"ML {role} content differs from dataset snapshot fingerprint"
            )


def _model_arrays(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    if not isinstance(frame.columns, pd.MultiIndex):
        raise ValueError("Qlib ML training columns must use feature/label groups")
    features = frame["feature"].astype("float64")
    labels = frame["label"].iloc[:, 0].astype("float64")
    finite = np.isfinite(features.to_numpy()).all(axis=1) & np.isfinite(
        labels.to_numpy()
    )
    return features.loc[finite], labels.loc[finite]


def _segments_json(segments: Any) -> dict[str, list[str]]:
    return {
        name: [pd.Timestamp(value).isoformat() for value in getattr(segments, name)]
        if hasattr(segments, name)
        else [pd.Timestamp(value).isoformat() for value in segments[name]]
        for name in ("train", "valid", "test")
    }


def _definition_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    frame.to_parquet(temporary)
    os.replace(temporary, path)


def _write_json_atomic(payload: Mapping[str, Any], path: Path) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)
