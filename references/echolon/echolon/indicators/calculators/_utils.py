"""Shared calculator helpers.

Private to the calculators subpackage; exposes the `_require_columns`
helper that raises IND-005 when a DataFrame is missing a required column.
"""
from __future__ import annotations

import pandas as pd

from echolon.errors import raise_error


def _require_columns(df: pd.DataFrame, required: list[str], *, calculator: str) -> None:
    """Raise IND-005 if any `required` column is missing from `df`."""
    present = list(df.columns)
    for col in required:
        if col not in present:
            raise_error(
                "IND-005",
                calculator=calculator,
                missing_column=col,
                required_columns=", ".join(required),
                present_columns=", ".join(present) if present else "<empty>",
            )
