"""Turn an approved binding into the bounded pandas a Strategy is allowed to read.

Everything here narrows: the catalog query is cut at the decision time, the frame is cut to
the manifest's fixed row lookback, and the result is checked against the inherited universe.
A Strategy never reaches the loader itself, so this is the only place data crosses into it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import pandas as pd

from qlibx.catalog import ConfigDrivenDataLoader, require_matrix_axes
from qlibx.errors import QlibxError
from qlibx.project import Project

from .capability import require_strategy_binding
from .contracts import (
    ResolvedStrategyInputs,
    StrategyBinding,
    StrategyInput,
    StrategyManifest,
)


@dataclass(frozen=True, slots=True)
class StrategyInputResolver:
    project: Project
    manifest: StrategyManifest
    binding: StrategyBinding
    loader: ConfigDrivenDataLoader
    effective_config_id: str

    @classmethod
    def from_project(
        cls,
        project: Project,
        manifest: StrategyManifest,
        binding: StrategyBinding,
    ) -> StrategyInputResolver:
        plan = require_strategy_binding(project, manifest, binding)
        return cls(
            project,
            manifest,
            binding,
            ConfigDrivenDataLoader.from_project(project),
            str(plan.parameters["effective_config_id"]),
        )

    def resolve(
        self,
        decision_time: str | pd.Timestamp,
        *,
        tickers: tuple[str, ...] | None = None,
    ) -> ResolvedStrategyInputs:
        return _resolve_inputs(
            self.loader,
            self.manifest,
            self.binding,
            pd.Timestamp(decision_time),
            tickers,
            self.effective_config_id,
        )


def resolve_strategy_inputs(
    project: Project,
    manifest: StrategyManifest,
    binding: StrategyBinding,
    *,
    decision_time: str | pd.Timestamp,
    tickers: tuple[str, ...] | None = None,
) -> ResolvedStrategyInputs:
    return StrategyInputResolver.from_project(project, manifest, binding).resolve(
        decision_time,
        tickers=tickers,
    )


def _resolve_inputs(
    loader: ConfigDrivenDataLoader,
    manifest: StrategyManifest,
    binding: StrategyBinding,
    cutoff: pd.Timestamp,
    tickers: tuple[str, ...] | None,
    effective_config_id: str,
) -> ResolvedStrategyInputs:
    by_role = binding.by_role()
    resolved: dict[str, pd.DataFrame] = {}
    for contract in manifest.all_inputs:
        selected = by_role[contract.role]
        if contract.pandas.kind == "matrix":
            frame = (
                _load_universe_matrix(
                    loader,
                    selected.registered_dataset,
                    cutoff=cutoff,
                    tickers=tickers,
                )
                if contract.role == "universe"
                else loader.load_matrix(
                    selected.registered_dataset,
                    tickers=tickers,
                    as_of=cutoff,
                )
            )
            frame = _tail_periods(frame, manifest.lookback_rows)
            if contract.pandas.dtype is not None:
                try:
                    frame = frame.astype(contract.pandas.dtype)
                except (TypeError, ValueError) as error:
                    raise QlibxError(
                        "QLIBX_INVALID_INPUT_DTYPE",
                        f"Input {contract.role!r} cannot convert to {contract.pandas.dtype}",
                        action="Correct the manifest or bind a compatible registered dataset.",
                    ) from error
            _validate_matrix_cells(contract, frame)
        else:
            frame = loader.load_table(
                selected.registered_dataset,
                tickers=tickers,
                as_of=cutoff,
            )
            source_fields = dict(selected.fields)
            selected_columns = [*contract.pandas.index, *source_fields.values()]
            missing = sorted(set(selected_columns) - set(frame.columns))
            if missing:
                raise QlibxError(
                    "QLIBX_MISSING_BOUND_FIELDS",
                    f"Bound input {contract.role!r} is missing fields: {missing}",
                    action="Correct the binding after inspecting registered fields.",
                )
            frame = frame.loc[:, selected_columns].rename(
                columns={source: canonical for canonical, source in source_fields.items()}
            )
            frame = frame.set_index(list(contract.pandas.index)).sort_index()
            frame = _tail_periods(frame, manifest.lookback_rows)
            _validate_fields(contract, frame)
        resolved[contract.role] = frame.copy(deep=True)
    _validate_universe_alignment(manifest, resolved)
    return ResolvedStrategyInputs(
        strategy_id=manifest.strategy_id,
        strategy_version=manifest.version,
        binding_id=binding.binding_id,
        decision_time=cutoff,
        inputs=MappingProxyType(resolved),
        effective_config_id=effective_config_id,
    )


def _load_universe_matrix(
    loader: ConfigDrivenDataLoader,
    dataset_name: str,
    *,
    cutoff: pd.Timestamp,
    tickers: tuple[str, ...] | None,
) -> pd.DataFrame:
    axes = require_matrix_axes(loader.catalog.datasets[dataset_name])
    table = loader.load_table(dataset_name, as_of=cutoff, tickers=tickers)
    duplicate = table.duplicated([axes.index, axes.columns], keep=False)
    if duplicate.any():
        raise QlibxError(
            "QLIBX_INVALID_UNIVERSE_DUPLICATE",
            f"Universe has {int(duplicate.sum())} duplicate date/ticker rows",
            action="Correct the registered universe query before Strategy execution.",
        )
    matrix = table.pivot(index=axes.index, columns=axes.columns, values=axes.values)
    matrix = matrix.sort_index().sort_index(axis=1)
    if matrix.isna().any().any():
        raise QlibxError(
            "QLIBX_INVALID_UNIVERSE_NULL",
            "Universe membership is missing for one or more registered date/ticker cells",
            action="Provide explicit true/false membership; do not infer membership from absence.",
        )
    return matrix.astype(bool)


def _validate_fields(contract: StrategyInput, frame: pd.DataFrame) -> None:
    for declared_field in contract.fields:
        try:
            converted = frame[declared_field.name].astype(declared_field.dtype)
        except (TypeError, ValueError) as error:
            raise QlibxError(
                "QLIBX_INVALID_INPUT_DTYPE",
                f"Field {contract.role}.{declared_field.name} "
                f"cannot convert to {declared_field.dtype}",
                action="Correct the binding or manifest dtype.",
            ) from error
        if not declared_field.nullable and converted.isna().any():
            raise QlibxError(
                "QLIBX_INVALID_INPUT_NULL",
                f"Field {contract.role}.{declared_field.name} contains null values",
                action="Bind a complete field or declare nullable behavior.",
            )
        frame[declared_field.name] = converted


def _validate_matrix_cells(contract: StrategyInput, frame: pd.DataFrame) -> None:
    """Apply a matrix input's declared nullability to its cells.

    A matrix spreads one semantic field across ticker columns, so the manifest's field
    declaration constrains every cell rather than a named column. Without this the
    `nullable: false` a manifest declares would only ever bind on table inputs.
    """
    for declared_field in contract.fields:
        if declared_field.nullable or not frame.isna().to_numpy().any():
            continue
        raise QlibxError(
            "QLIBX_INVALID_INPUT_NULL",
            f"Field {contract.role}.{declared_field.name} contains null values",
            action="Bind a complete matrix or declare nullable behavior.",
            context={"role": contract.role, "field": declared_field.name},
        )


def _validate_universe_alignment(
    manifest: StrategyManifest,
    inputs: Mapping[str, pd.DataFrame],
) -> None:
    """Reject any bound input carrying a ticker the inherited universe does not declare.

    The ticker axis comes from the manifest's declared pandas kind, never from the shape
    of the data: inferring it from the frame made the check vacuous, because "the columns
    all sit inside the universe" is false in exactly the case worth reporting.
    """
    universe_tickers = set(map(str, inputs["universe"].columns))
    for contract in manifest.all_inputs:
        role = contract.role
        if role == "universe":
            continue
        frame = inputs[role]
        if contract.pandas.kind == "matrix":
            tickers = set(map(str, frame.columns))
        else:
            ticker_level = _ticker_index_level(contract)
            if ticker_level is None:
                continue
            tickers = set(map(str, frame.index.get_level_values(ticker_level)))
        outside = sorted(tickers - universe_tickers)
        if outside:
            raise QlibxError(
                "QLIBX_BOUNDARY_UNIVERSE_MISMATCH",
                f"Input {role!r} contains tickers outside universe axes: {outside}",
                action="Align bound datasets with the inherited universe input.",
                context={"role": role, "outside_universe": outside},
            )


def _ticker_index_level(contract: StrategyInput) -> int | None:
    """Locate the declared ticker level of a table input, or None when it has none."""
    for level, name in enumerate(contract.pandas.index):
        if name == "ticker":
            return level
    return None


def _tail_periods(frame: pd.DataFrame, rows: int) -> pd.DataFrame:
    index = (
        frame.index.get_level_values(0) if isinstance(frame.index, pd.MultiIndex) else frame.index
    )
    periods = pd.Index(index).drop_duplicates().sort_values()
    if len(periods) <= rows:
        return frame.copy(deep=True)
    return frame.loc[pd.Index(index).isin(set(periods[-rows:]))].copy(deep=True)


__all__ = ["StrategyInputResolver", "resolve_strategy_inputs"]
