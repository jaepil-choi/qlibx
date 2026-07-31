"""Item 3 TDD: EnrichedPandasData.from_metadata must fail loud on invalid column names.

Backtrader binds indicator columns as line *attributes*. Names with dashes,
spaces, or dots fail at first attribute access — silently, at bar time — rather
than at construction. This guard moves the failure to construction where the
message is actionable.

Written BEFORE the production change. Tests that expect ValueError will fail
against the current from_metadata which has no such guard.
"""
import pytest

from echolon.backtest.engine.enriched_pandas_data import EnrichedPandasData


def test_dashed_column_fails_at_construction():
    """indicator_columns containing a dash must raise ValueError with the column name."""
    with pytest.raises(ValueError, match="col-with-dashes"):
        EnrichedPandasData.from_metadata({"indicator_columns": ["col-with-dashes"]})


def test_space_column_fails_at_construction():
    """indicator_columns containing a space must raise ValueError with the column name."""
    with pytest.raises(ValueError, match="has space"):
        EnrichedPandasData.from_metadata({"indicator_columns": ["has space"]})


def test_valid_columns_pass():
    """indicator_columns with valid Python identifier names must not raise."""
    # Should not raise
    EnrichedPandasData.from_metadata({"indicator_columns": ["valid_col", "another_col"]})
