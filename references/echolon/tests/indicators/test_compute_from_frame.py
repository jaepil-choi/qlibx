"""``compute_indicators_from_frame`` — the injectable-frame indicator entry point.

Callers doing block-bootstrap / synthetic-data analysis need the SAME per-bar
indicator computations ``run_indicator_calculation`` applies to its stitched
main-contract series, but starting from a caller-provided continuous OHLCV
``DataFrame`` instead of the repo's per-contract raw files + roll table.

The load-bearing test in this module (``test_identity_...``) builds a
two-contract SHFE-shaped fixture with one main-contract roll, runs it through
the REAL standard pipeline (``run_indicator_calculation`` — no mocking, real
TA-Lib), extracts the continuous OHLCV the pipeline produced, feeds it through
``compute_indicators_from_frame``, and checks the documented identity
boundary: exact match (modulo float non-associativity) away from the roll,
and a PROVEN divergence in the handful of bars whose lookback window spans
the roll — see ``compute_indicators_from_frame``'s docstring in
``echolon/indicators/run.py`` for why that divergence is inherent (the
standard pipeline used the new contract's own pre-roll price history there;
a bare continuous OHLCV frame does not carry that lineage).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from echolon.config.markets.factory import MarketFactory
from echolon.config.paths_config import PathsConfig
from echolon.errors import IndicatorError
from echolon.indicators.run import compute_indicators_from_frame, run_indicator_calculation

PERIOD = 5
N_DAYS = 30
ROLL_INDEX = 20  # al2402 becomes main at trading_dates[ROLL_INDEX] (day 21)


def _make_frame(n=40):
    return pd.DataFrame({
        "date":  pd.date_range("2024-01-01", periods=n, freq="D"),
        "open":  [100.0 + i * 0.1 for i in range(n)],
        "high":  [101.0 + i * 0.1 for i in range(n)],
        "low":   [99.0 + i * 0.1 for i in range(n)],
        "close": [100.5 + i * 0.1 for i in range(n)],
        "volume": [1000 for _ in range(n)],
    })


def _build_roll_fixture(tmp_path: Path, ctx):
    """Two-contract fixture with one main-contract roll.

    al2401 and al2402 EACH carry a full ``N_DAYS`` OWN price history — a real
    SHFE contract lists well before it becomes the front month and keeps
    trading after it is rolled off, and the standard pipeline computes every
    contract's indicators over that contract's OWN full file (see
    ``IndicatorProcessor.process_single_contract``). al2402's prices are
    al2401's plus a constant +50 offset, modelling a distinct point on the
    futures curve (a real roll: the incoming contract is NOT just a
    continuation of the outgoing one's price level).

    ``main_contract.csv`` rolls from al2401 to al2402 at
    ``trading_dates[ROLL_INDEX]``.
    """
    market_data_dir = tmp_path / "market_data"
    asset_dir = market_data_dir / "SHFE" / "aluminum"
    contract_dir = asset_dir / "sort_by_contract"
    contract_dir.mkdir(parents=True)

    trading_dates = list(pd.bdate_range("2024-01-02", periods=N_DAYS))

    def _contract_frame(offset: float) -> pd.DataFrame:
        return pd.DataFrame({
            "date":   [d.strftime("%Y-%m-%d") for d in trading_dates],
            "open":   [100.0 + i + offset for i in range(N_DAYS)],
            "high":   [101.0 + i + offset for i in range(N_DAYS)],
            "low":    [99.0 + i + offset for i in range(N_DAYS)],
            "close":  [100.5 + i + offset for i in range(N_DAYS)],
            "volume": [1000 + i for i in range(N_DAYS)],
        })

    _contract_frame(0.0).to_csv(contract_dir / "al2401.csv", index=False)
    _contract_frame(50.0).to_csv(contract_dir / "al2402.csv", index=False)

    main_contract = pd.DataFrame({
        "date": [
            trading_dates[0].strftime("%Y-%m-%d"),
            trading_dates[ROLL_INDEX].strftime("%Y-%m-%d"),
        ],
        "main_contract": ["al2401", "al2402"],
    })
    main_contract.to_csv(asset_dir / "main_contract.csv", index=False)

    paths = PathsConfig.from_project_root(tmp_path, market_data_dir=market_data_dir)
    return paths, trading_dates


@pytest.fixture
def roll_fixture(tmp_path, interday_ctx):
    paths, trading_dates = _build_roll_fixture(tmp_path, interday_ctx)
    return interday_ctx, paths, trading_dates


# --------------------------------------------------------------------------- #
# THE IDENTITY TEST (load-bearing)
# --------------------------------------------------------------------------- #
def test_identity_matches_standard_pipeline_away_from_roll_and_diverges_near_it(
    roll_fixture, tmp_path
):
    ctx, paths, trading_dates = roll_fixture
    indicator_list = {"sma": {"timeperiod": [PERIOD]}}

    # 1. Run the REAL standard pipeline end to end (real TA-Lib, no mocking).
    standard = run_indicator_calculation(
        ctx=ctx,
        output_dir=str(tmp_path / "out"),
        indicator_list=indicator_list,
        trading_dates=trading_dates,
        use_parallel=False,
        start_date=trading_dates[0].strftime("%Y-%m-%d"),
        end_date=trading_dates[-1].strftime("%Y-%m-%d"),
        paths=paths,
    )
    assert len(standard) == N_DAYS
    assert "sma_5" in standard.columns
    # Sanity: the fixture really does roll main contract mid-series.
    assert standard["contract"].iloc[0] == "al2401"
    assert standard["contract"].iloc[-1] == "al2402"

    # Derive the roll index from the PIPELINE's own output rather than
    # trusting the fixture constant blindly: exactly one transition, at the
    # position the fixture intended. If fixture and pipeline ever disagree
    # (e.g. a main_contract.csv lookup change shifts the effective roll
    # date), this fails loudly instead of the zones below silently testing
    # the wrong bars.
    contracts = standard["contract"].reset_index(drop=True)
    changes = contracts.ne(contracts.shift()).iloc[1:]  # row 0 is always a "change"
    assert int(changes.sum()) == 1, f"expected exactly one roll, got {int(changes.sum())}"
    roll_index = int(changes.idxmax())
    assert roll_index == ROLL_INDEX, (
        f"fixture says the roll is at index {ROLL_INDEX}, but the pipeline "
        f"output rolls at index {roll_index}"
    )

    # 2. Extract exactly the continuous OHLCV columns the standard pipeline
    #    produced — no contract/trading_date/contract_expiry/sma_5 lineage,
    #    since that's precisely what a caller-provided frame would NOT have.
    continuous_ohlcv = standard.reset_index()[
        ["date", "open", "high", "low", "close", "volume"]
    ].copy()

    # 3. Feed it through the new injectable-frame entry point.
    frame_result = compute_indicators_from_frame(continuous_ohlcv, indicator_list, ctx)

    standard_sma = standard["sma_5"].to_numpy()
    frame_sma = frame_result["sma_5"].to_numpy()

    # Warmup zone: insufficient lookback -> NaN on both sides, same shape.
    assert np.isnan(standard_sma[: PERIOD - 1]).all()
    assert np.isnan(frame_sma[: PERIOD - 1]).all()

    # --- Divergence zone: bars whose PERIOD-bar window spans the roll ----
    # The standard pipeline computed these using al2402's OWN pre-roll price
    # history (which the continuous OHLCV frame does not carry — those dates
    # show al2401's price there instead). Assert the two DO diverge, and by
    # a margin far above the float-precision tolerance used below, so this
    # is a genuine falsifier rather than a masked-away zone that happened to
    # match anyway.
    divergence_zone = slice(roll_index, roll_index + PERIOD - 1)
    divergence = np.abs(standard_sma[divergence_zone] - frame_sma[divergence_zone])
    assert len(divergence) == PERIOD - 1
    assert (divergence > 1.0).all(), (
        f"expected genuine divergence near the roll (documented, excluded "
        f"from the identity claim), got diffs={divergence}"
    )

    # --- Matched zone: everywhere else, identical modulo float non-assoc -
    # TA-Lib's sliding-window wrappers (e.g. SMA) accumulate via an
    # incremental running sum rather than re-summing each window from
    # scratch, so a bar's value can differ at the machine-epsilon level
    # depending on how much history precedes it, even when the trailing
    # window's actual values are bit-identical (verified separately: same
    # inputs, different amount of preceding context -> ~1e-13 relative
    # diff). rtol/atol=1e-9 absorbs exactly that and nothing else — the
    # divergence-zone assertion above proves 1e-9 could never mask a real
    # mismatch (those diffs are >1.0, ten orders of magnitude larger).
    matched_idx = np.array([
        i for i in range(PERIOD - 1, N_DAYS)
        if not (roll_index <= i < roll_index + PERIOD - 1)
    ])
    np.testing.assert_allclose(
        standard_sma[matched_idx], frame_sma[matched_idx], rtol=1e-9, atol=1e-9,
    )

    # Non-indicator OHLCV columns pass through unchanged.
    for col in ("open", "high", "low", "close", "volume"):
        np.testing.assert_array_equal(
            frame_result[col].to_numpy(), continuous_ohlcv[col].to_numpy()
        )


# --------------------------------------------------------------------------- #
# Unit-level contract tests (hermetic — no fixture files)
# --------------------------------------------------------------------------- #
def test_computes_declared_indicator_column(interday_ctx):
    df = _make_frame()
    out = compute_indicators_from_frame(df, {"rsi": {"timeperiod": [14]}}, interday_ctx)
    assert "rsi_14" in out.columns
    assert len(out) == len(df)


def test_does_not_mutate_caller_frame(interday_ctx):
    df = _make_frame()
    before = df.copy()
    compute_indicators_from_frame(df, {"rsi": {"timeperiod": [14]}}, interday_ctx)
    pd.testing.assert_frame_equal(df, before)


def test_invalid_indicator_list_raises_validation_error(interday_ctx):
    """Schema validation runs before any computation — same IndicatorList
    schema run_indicator_calculation validates against."""
    df = _make_frame()
    with pytest.raises(Exception):  # pydantic.ValidationError
        compute_indicators_from_frame(df, {}, interday_ctx)  # empty -> rejected


def test_curve_carry_indicator_raises_ind_009(interday_ctx):
    df = _make_frame()
    with pytest.raises(IndicatorError) as exc:
        compute_indicators_from_frame(
            df, {"atr": {"timeperiod": 14}, "carry_front_back": {}}, interday_ctx
        )
    assert exc.value.code == "IND-009"
    assert "carry_front_back" in exc.value.context["indicators"]


def test_curve_carry_rejection_happens_before_any_compute(interday_ctx):
    """Even a curve_carry-only indicator_list raises IND-009, not some
    downstream compute error — confirms the hard-fail happens at the door."""
    df = _make_frame()
    with pytest.raises(IndicatorError) as exc:
        compute_indicators_from_frame(df, {"carry_z_3m": {}}, interday_ctx)
    assert exc.value.code == "IND-009"


# --------------------------------------------------------------------------- #
# Regime classifier passthrough (out-of-scope-unless-trivial boundary, T3)
# --------------------------------------------------------------------------- #
@pytest.fixture
def stub_classifier():
    from echolon.indicators.registry import register_regime_classifier
    from echolon.indicators.registry.regime_classifiers import _CLASSIFIERS

    class _StubMarketRegime:
        name = "market_regime"
        label_map = {0: "ranging", 1: "trending_up", -1: "trending_down", 2: "volatile"}

        def fit_classify(self, df, params):
            return pd.Series(np.zeros(len(df), dtype=int), index=df.index, name="market_regime")

    register_regime_classifier(_StubMarketRegime())
    yield
    _CLASSIFIERS.pop("market_regime", None)


def test_registered_classifier_column_included_when_regime_params_supplied(
    interday_ctx, stub_classifier
):
    """Regime classifiers are 'trivially includable' — the same dispatch
    _compute_indicators_for_contract already uses handles them, so this
    function does not special-case them out."""
    df = _make_frame()
    regime_params = {
        "fast_ma_period": 20, "slow_ma_period": 50,
        "adx_period": 14, "adx_trend_threshold": 20.0,
        "atr_period": 14, "vol_lookback": 60,
        "vol_high_percentile": 75.0,
        "chop_period": 14, "chop_threshold": 50.0,
        "min_regime_bars": 3,
    }
    out = compute_indicators_from_frame(
        df, {"market_regime": {}}, interday_ctx, regime_params=regime_params,
    )
    assert "market_regime" in out.columns


def test_registered_classifier_without_regime_params_raises(interday_ctx, stub_classifier):
    df = _make_frame()
    with pytest.raises(ValueError, match="regime_params"):
        compute_indicators_from_frame(df, {"market_regime": {}}, interday_ctx)


# --------------------------------------------------------------------------- #
# Intraday regime_params parity guard
# --------------------------------------------------------------------------- #
@pytest.fixture
def intraday_ctx():
    return MarketFactory.create(
        market="SHFE", instrument="al", frequency="intraday", bar_size="15m"
    )


@pytest.fixture
def spy_classifier():
    """Registered classifier that records the params dict it actually receives."""
    from echolon.indicators.registry import register_regime_classifier
    from echolon.indicators.registry.regime_classifiers import _CLASSIFIERS

    received: dict = {}

    class _SpyRegime:
        name = "market_regime"
        label_map = {0: "ranging", 1: "trending_up", -1: "trending_down", 2: "volatile"}

        def fit_classify(self, df, params):
            received["params"] = dict(params)
            return pd.Series(np.zeros(len(df), dtype=int), index=df.index, name="market_regime")

    register_regime_classifier(_SpyRegime())
    yield received
    _CLASSIFIERS.pop("market_regime", None)


def _make_intraday_frame(n=40):
    return pd.DataFrame({
        "datetime": pd.date_range("2024-01-02 09:00", periods=n, freq="15min"),
        "open":  [100.0 + i * 0.1 for i in range(n)],
        "high":  [101.0 + i * 0.1 for i in range(n)],
        "low":   [99.0 + i * 0.1 for i in range(n)],
        "close": [100.5 + i * 0.1 for i in range(n)],
        "volume": [1000 for _ in range(n)],
    })


def test_intraday_ctx_ignores_caller_regime_params(intraday_ctx, spy_classifier):
    """The standard pipeline never forwards regime_params on an intraday ctx
    (IndicatorProcessor.__init__ keeps them only when frequency == 'day';
    intraday sets self.regime_params = None). The frame path mirrors that
    routing so the 'SAME computations' identity claim holds unconditionally:
    a caller-passed dict must be IGNORED — the classifier sees {} exactly as
    it would under run_indicator_calculation."""
    df = _make_intraday_frame()
    caller_params = {"fast_ma_period": 20, "slow_ma_period": 50}
    out = compute_indicators_from_frame(
        df, {"market_regime": {}}, intraday_ctx, regime_params=caller_params,
    )
    assert "market_regime" in out.columns
    # Falsifier: without the intraday guard the spy would have received
    # caller_params verbatim (via _auto_params_for's MARKET_REGIME branch).
    assert spy_classifier["params"] == {}
