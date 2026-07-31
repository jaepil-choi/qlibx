"""Calculator column-contract violations raise IND-005 with full context."""
import pandas as pd
import pytest

from echolon.errors import IndicatorError


def test_require_columns_raises_ind_005_when_missing():
    from echolon.indicators.calculators._utils import _require_columns

    df = pd.DataFrame({"open": [1, 2], "close": [2, 3]})
    with pytest.raises(IndicatorError) as exc:
        _require_columns(df, ["trading_date"], calculator="some_intraday_calc")
    assert exc.value.code == "IND-005"
    assert "trading_date" in str(exc.value)
    assert "some_intraday_calc" in str(exc.value)


def test_require_columns_passes_when_all_present():
    from echolon.indicators.calculators._utils import _require_columns

    df = pd.DataFrame({"datetime": [], "trading_date": []})
    # No raise
    _require_columns(df, ["datetime", "trading_date"], calculator="x")


def test_require_columns_lists_present_columns_in_context():
    from echolon.indicators.calculators._utils import _require_columns

    df = pd.DataFrame({"a": [1], "b": [2]})
    with pytest.raises(IndicatorError) as exc:
        _require_columns(df, ["c"], calculator="x")
    msg = str(exc.value)
    # present_columns list (from context dict) contains a, b
    assert "a" in msg and "b" in msg


def test_require_columns_empty_df():
    """An empty DataFrame still raises IND-005 with '<empty>' in present_columns."""
    from echolon.indicators.calculators._utils import _require_columns

    df = pd.DataFrame()
    with pytest.raises(IndicatorError) as exc:
        _require_columns(df, ["anything"], calculator="x")
    assert exc.value.code == "IND-005"
