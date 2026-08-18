"""Time-series operations that cannot reach outside the window they were handed.

The point-in-time boundary elsewhere in this package stops a strategy *reading* data it could not
have seen. It cannot stop a computation *reaching* — a rolling statistic handed a legitimate window
can still centre itself, or read one element past the step it is producing, and the access boundary
never sees it because the data was already given.

This module closes that second path the only way a rule cannot be forgotten: **there is no index to
reach with.** ``apply_causal`` receives sequences and a length, slices the trailing window itself,
and hands the callable nothing but values. A callable that wanted the future would have to be given
it, and it never is.

That is what canon calls a causal primitive: a pure function where not reaching outside the window
is guaranteed by the implementation rather than promised by a docstring.

Everything here is exact. No sample is dropped, no window is padded, and no missing value is
invented — a step that cannot be computed reports ``None`` rather than a number that looks real.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation

__all__ = [
    "apply_causal",
    "window_beta",
    "window_maximum",
    "window_mean",
    "window_skewness",
    "window_stdev",
]


def apply_causal(
    series: tuple[Sequence[Decimal], ...],
    *,
    length: int,
    fn: Callable[[tuple[tuple[Decimal, ...], ...]], Decimal],
) -> tuple[Decimal | None, ...]:
    """Drive ``fn`` across every trailing window of ``length``, one step at a time.

    ``series`` is a tuple of equally long sequences read in lockstep — one entry for a single
    series, two for a statistic relating an asset to a market. At step ``i`` the callable receives
    one window per series, each being exactly the elements at positions ``i - length + 1`` through
    ``i`` inclusive. It receives no position, no date and no access to the sequences themselves, so
    a future element is not merely forbidden, it is absent.

    Steps before the first full window report ``None``. That is warm-up, not failure: the window
    genuinely does not exist yet, and reporting a number computed from a short window would be the
    quiet lie this module exists to prevent.

    Alignment is refused here, before any step runs, so a callable never has to check it.
    """
    if not isinstance(series, tuple) or not series:
        raise ValueError("series must be a non-empty tuple of sequences")
    if isinstance(length, bool) or not isinstance(length, int) or length < 1:
        raise ValueError("length must be a positive integer")
    if not callable(fn):
        raise TypeError("fn must be callable")

    checked: list[tuple[Decimal, ...]] = []
    for index, entry in enumerate(series):
        if not isinstance(entry, Sequence) or isinstance(entry, (str, bytes)):
            raise TypeError(f"series[{index}] must be a sequence of Decimal")
        values = tuple(entry)
        for position, value in enumerate(values):
            if not isinstance(value, Decimal):
                raise TypeError(
                    f"series[{index}][{position}] must be a Decimal; got {type(value).__name__}"
                )
            if not value.is_finite():
                raise ValueError(f"series[{index}][{position}] must be finite")
        checked.append(values)

    span = len(checked[0])
    mismatched = [index for index, values in enumerate(checked) if len(values) != span]
    if mismatched:
        # Refused before any step, so a statistic never has to defend itself against ragged input.
        raise ValueError(
            f"series must be equally long; series[0] has {span} and "
            f"{[f'series[{i}] has {len(checked[i])}' for i in mismatched]}"
        )
    if span < length:
        return tuple(None for _ in range(span))

    results: list[Decimal | None] = [None] * (length - 1)
    for stop in range(length, span + 1):
        window = tuple(values[stop - length : stop] for values in checked)
        produced = fn(window)
        if not isinstance(produced, Decimal):
            raise TypeError(f"fn must return a Decimal; got {type(produced).__name__}")
        if not produced.is_finite():
            raise ValueError("fn must return a finite Decimal")
        results.append(produced)
    return tuple(results)


def _single(windows: tuple[tuple[Decimal, ...], ...], name: str) -> tuple[Decimal, ...]:
    if len(windows) != 1:
        raise ValueError(f"{name} takes one series; received {len(windows)}")
    values = windows[0]
    if not values:
        raise ValueError(f"{name} needs a non-empty window")
    return values


def window_mean(windows: tuple[tuple[Decimal, ...], ...]) -> Decimal:
    """Arithmetic mean of one window."""
    values = _single(windows, "window_mean")
    return sum(values, Decimal(0)) / len(values)


def window_stdev(windows: tuple[tuple[Decimal, ...], ...]) -> Decimal:
    """Sample standard deviation of one window.

    Sample rather than population, because a rolling window is a sample of a longer process. Needs
    at least two observations; one observation has no spread to report and saying zero would claim
    certainty the window does not have.
    """
    values = _single(windows, "window_stdev")
    if len(values) < 2:
        raise ValueError("window_stdev needs at least two observations")
    centre = sum(values, Decimal(0)) / len(values)
    variance = sum(((value - centre) ** 2 for value in values), Decimal(0)) / (len(values) - 1)
    return variance.sqrt()


def window_skewness(windows: tuple[tuple[Decimal, ...], ...]) -> Decimal:
    """Sample skewness of one window, on the same spread convention as `window_stdev`.

    Refuses on a flat window rather than reporting zero: a window with no spread has undefined
    skewness, and zero is a specific claim about symmetry.
    """
    values = _single(windows, "window_skewness")
    if len(values) < 3:
        raise ValueError("window_skewness needs at least three observations")
    count = len(values)
    centre = sum(values, Decimal(0)) / count
    variance = sum(((value - centre) ** 2 for value in values), Decimal(0)) / (count - 1)
    if variance == 0:
        raise ValueError("window_skewness is undefined on a window with no spread")
    spread = variance.sqrt()
    try:
        cubed = sum((((value - centre) / spread) ** 3 for value in values), Decimal(0))
    except InvalidOperation as error:  # pragma: no cover - guarded by the spread check above
        raise ValueError("window_skewness could not be computed") from error
    return Decimal(count) / (Decimal(count - 1) * Decimal(count - 2)) * cubed


def window_maximum(windows: tuple[tuple[Decimal, ...], ...]) -> Decimal:
    """Largest value in one window."""
    return max(_single(windows, "window_maximum"))


def window_beta(windows: tuple[tuple[Decimal, ...], ...]) -> Decimal:
    """Sensitivity of the first series to the second across one window.

    Covariance over the second series' variance, both on the sample convention. Refuses when the
    market window has no variance, because the ratio is undefined and any number returned there
    would be an invention.
    """
    if len(windows) != 2:
        raise ValueError(f"window_beta takes two series; received {len(windows)}")
    asset, market = windows
    if len(asset) != len(market):
        raise ValueError("window_beta needs equally long windows")
    if len(asset) < 2:
        raise ValueError("window_beta needs at least two observations")
    asset_centre = sum(asset, Decimal(0)) / len(asset)
    market_centre = sum(market, Decimal(0)) / len(market)
    covariance = sum(
        ((a - asset_centre) * (m - market_centre) for a, m in zip(asset, market, strict=True)),
        Decimal(0),
    )
    variance = sum(((m - market_centre) ** 2 for m in market), Decimal(0))
    if variance == 0:
        raise ValueError("window_beta is undefined when the market window has no variance")
    return covariance / variance
