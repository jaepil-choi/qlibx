"""Indicator-layer errors use catalog codes."""
import json
from pathlib import Path

import pandas as pd
import pytest

from echolon.errors import IndicatorError


def test_all_nan_column_writes_sidecar_warning(tmp_path: Path):
    """_write_nan_warnings_sidecar flags columns with >=80% NaN."""
    from echolon.indicators.engine.processor import _write_nan_warnings_sidecar

    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=10),
        "rsi_14": [float("nan")] * 9 + [50.0],   # 90% NaN
        "macd":   list(range(10)),                # 0% NaN
    })

    output_path = tmp_path / "out.csv"
    _write_nan_warnings_sidecar(df=df, output_path=output_path, nan_threshold=0.8)

    sidecar = output_path.with_suffix(output_path.suffix + ".warnings.json")
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "rsi_14" in payload["warnings"]
    assert payload["warnings"]["rsi_14"]["code"] == "IND-003"
    assert "macd" not in payload["warnings"]


def test_well_populated_columns_write_no_sidecar(tmp_path: Path):
    """No sidecar written when every column is well-populated."""
    from echolon.indicators.engine.processor import _write_nan_warnings_sidecar

    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=10),
        "rsi_14": list(range(10)),
    })
    output_path = tmp_path / "out.csv"
    _write_nan_warnings_sidecar(df=df, output_path=output_path, nan_threshold=0.8)

    sidecar = output_path.with_suffix(output_path.suffix + ".warnings.json")
    assert not sidecar.exists()


def test_unknown_indicator_raises_ind_002():
    """processor raises IND-002 when indicator name is not in the function mapping."""
    # Find the helper that resolves indicator name -> function. Its exact shape
    # depends on the processor's current implementation — the test simply
    # expects that passing an unknown name somewhere in the dispatch flow
    # raises IndicatorError with code="IND-002".
    from unittest.mock import patch

    from echolon.indicators.engine import processor as proc_mod

    # Locate the resolver: either a static method on IndicatorProcessor, a
    # helper function, or inline in a loop. The test uses a best-effort
    # approach that matches the implementer's refactor.
    resolver = None
    for candidate in ("_resolve_function", "_resolve_indicator_function", "resolve_indicator"):
        resolver = getattr(proc_mod, candidate, None) or getattr(proc_mod.IndicatorProcessor, candidate, None)
        if resolver is not None:
            break

    assert resolver is not None, "expected a name-resolution helper after P1.4"

    # The resolver delegates to echolon.indicators.registry.utils.get_function,
    # which in the standalone test env uses legacy ``modules.*`` import paths.
    # Stub it to return None (the "no mapping" contract) so the resolver's own
    # IND-002 branch is what surfaces.
    with patch(
        "echolon.indicators.engine.processor.get_function",
        return_value=None,
    ):
        with pytest.raises(IndicatorError) as exc:
            if hasattr(resolver, "__self__"):  # bound method
                resolver(indicator_name="definitely_not_real")
            else:
                # Unbound — try both call shapes
                try:
                    resolver(indicator_name="definitely_not_real")
                except TypeError:
                    resolver(None, indicator_name="definitely_not_real")
    assert exc.value.code == "IND-002"


def test_derived_column_dispatch_error_names_base_declaration():
    from echolon.indicators.engine import processor as proc_mod

    with pytest.raises(IndicatorError) as exc:
        proc_mod._resolve_function("cmo_pctl_252")

    assert exc.value.code == "IND-002"
    assert "derived/vintage column" in str(exc.value)
    assert "declare the BASE" in str(exc.value)
    assert "cmo" in str(exc.value)


def test_vintage_column_dispatch_error_names_base_declaration():
    from echolon.indicators.engine import processor as proc_mod

    with pytest.raises(IndicatorError) as exc:
        proc_mod._resolve_function("market_regime__fit20240131")

    assert exc.value.code == "IND-002"
    assert "derived/vintage column" in str(exc.value)
    assert "declare the BASE" in str(exc.value)
    assert "market_regime" in str(exc.value)
