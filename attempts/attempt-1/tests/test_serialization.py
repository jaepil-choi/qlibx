from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from qlibx.serialization import read_payload, write_payload


def test_payload_round_trip_chooses_the_format_the_value_implies(tmp_path: Path) -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0]}, index=pd.date_range("2025-01-01", periods=2))
    payload_format, path = write_payload(tmp_path, frame)
    restored = read_payload(path, payload_format)

    assert payload_format == "parquet"
    assert path.name == "payload.parquet"
    # Values, dtypes and index labels survive; `freq` does not, because Parquet stores the
    # timestamps and not the rule that generated them. Pinned rather than hidden: code that
    # relies on a stored frame still being a regular series would be wrong.
    pd.testing.assert_frame_equal(restored, frame, check_freq=False)
    assert frame.index.freq is not None
    assert restored.index.freq is None


def test_a_series_is_framed_so_it_reads_back_identifiably(tmp_path: Path) -> None:
    """Parquet has no bare-Series form, so the name has to survive as a column."""
    series = pd.Series([1.0, 2.0], name="signal")
    payload_format, path = write_payload(tmp_path, series, stem="staged")

    restored = read_payload(path, payload_format)
    assert path.name == "staged.parquet"
    assert list(restored.columns) == ["signal"]

    unnamed = pd.Series([1.0], name=None)
    _, fallback = write_payload(tmp_path, unnamed, stem="unnamed")
    assert list(read_payload(fallback, "parquet").columns) == ["value"]


def test_non_pandas_values_round_trip_as_canonical_json(tmp_path: Path) -> None:
    value = {"b": 1, "a": [True, None]}
    payload_format, path = write_payload(tmp_path, value, stem="meta")

    assert payload_format == "json"
    assert path.read_bytes() == b'{"a":[true,null],"b":1}'
    assert read_payload(path, payload_format) == value


def test_an_unknown_format_refuses_rather_than_guessing(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported payload format"):
        read_payload(path, "csv")  # type: ignore[arg-type]
