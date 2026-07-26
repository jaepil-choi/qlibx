from __future__ import annotations

import pandas as pd

from qlib_extended.research.catalog import DatasetSpec


def table_to_matrix(table: pd.DataFrame, spec: DatasetSpec) -> pd.DataFrame:
    if spec.kind != "matrix" or not spec.index or not spec.columns or not spec.values:
        raise ValueError(f"Dataset is not a complete matrix spec: {spec.name}")
    required = [spec.index, spec.columns, spec.values]
    missing = [column for column in required if column not in table.columns]
    if missing:
        raise KeyError(f"Matrix dataset is missing required columns {missing}: {spec.name}")
    duplicate = table.duplicated([spec.index, spec.columns], keep=False)
    if duplicate.any():
        sample = table.loc[duplicate, [spec.index, spec.columns]].head(10)
        raise ValueError(
            f"Matrix dataset has duplicate date/ticker rows: {spec.name}, "
            f"samples={sample.to_dict('records')}"
        )
    matrix = table.pivot(index=spec.index, columns=spec.columns, values=spec.values)
    matrix.index = pd.DatetimeIndex(matrix.index, name=spec.index)
    matrix = matrix.sort_index().sort_index(axis=1)
    if spec.dtype is not None:
        matrix = matrix.astype(spec.dtype)
    return matrix


def align_matrix_like(matrix: pd.DataFrame, like: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(like.index, pd.DatetimeIndex):
        raise TypeError("like matrix index must be a DatetimeIndex.")
    return matrix.reindex(index=like.index, columns=like.columns)
