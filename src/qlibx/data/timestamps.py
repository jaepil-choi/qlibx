"""Strict timestamp normalization for registered physical sources."""

from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype


class TimestampNormalizationError(ValueError):
    """Raised when a source timestamp cannot be localized without guessing."""

    def __init__(self, code: str, context: dict[str, object]) -> None:
        self.code = code
        self.context = context
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NormalizedTimestamps:
    utc: pd.Series
    was_naive: bool


def normalize_timestamps(
    values: pd.Series,
    *,
    field: str,
    source_timezone: str | None,
) -> NormalizedTimestamps:
    """Return UTC instants while requiring an explicit meaning for naive values."""

    try:
        local = pd.to_datetime(values, errors="coerce", utc=False)
    except (TypeError, ValueError) as exc:
        raise _localization_error(field, exc) from exc
    if not isinstance(local, pd.Series):
        local = pd.Series(local, index=values.index)
    if not is_datetime64_any_dtype(local.dtype):
        raise TimestampNormalizationError(
            "TIMESTAMP_LOCALIZATION_FAILED",
            {
                "field": field,
                "message": "source mixes naive and offset-qualified timestamps",
            },
        )
    if isinstance(local.dtype, pd.DatetimeTZDtype):
        return NormalizedTimestamps(utc=local.dt.tz_convert("UTC"), was_naive=False)
    if source_timezone is None:
        samples = tuple(str(value) for value in values.loc[local.notna()].head(3))
        raise TimestampNormalizationError(
            "TIMESTAMP_TIMEZONE_UNDECLARED",
            {
                "field": field,
                "naive_rows": int(local.notna().sum()),
                "samples": samples,
            },
        )
    try:
        utc = local.dt.tz_localize(
            ZoneInfo(source_timezone),
            ambiguous="raise",
            nonexistent="raise",
        ).dt.tz_convert("UTC")
    except (TypeError, ValueError) as exc:
        raise _localization_error(field, exc) from exc
    return NormalizedTimestamps(utc=utc, was_naive=True)


def _localization_error(field: str, exc: Exception) -> TimestampNormalizationError:
    return TimestampNormalizationError(
        "TIMESTAMP_LOCALIZATION_FAILED",
        {
            "field": field,
            "exception": type(exc).__name__,
            "message": str(exc)[:500],
        },
    )