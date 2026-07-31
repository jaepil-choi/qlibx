"""If indicators CSV has a sibling .warnings.json sidecar (written by IND-003
helper in indicators/engine/processor), the loader logs a WARNING naming
the suspect columns."""
import json
from types import SimpleNamespace

import pandas as pd


def _make_ctx(instrument: str) -> SimpleNamespace:
    """Minimal stand-in for TradingContext providing just the attributes the
    loader reads (market_code, instrument_name, instrument_code). Avoids the
    full factory construction since we only need the sidecar WARNING to fire
    before any deeper ctx usage."""
    return SimpleNamespace(
        market_code="SHFE",
        instrument_name=instrument,
        instrument_code="al",
        encode_phase=lambda x: 0,
    )


def test_loader_logs_warning_when_sidecar_present(tmp_path, caplog):
    indicator_dir = tmp_path / "indicators"
    instrument = "aluminum"
    (indicator_dir / instrument).mkdir(parents=True)
    csv_path = indicator_dir / instrument / "strategy_indicators.csv"
    pd.DataFrame({
        "date": ["2024-01-01"],
        "rsi_14": [float("nan")],
    }).to_csv(csv_path, index=False)

    sidecar = csv_path.with_suffix(".csv.warnings.json")
    sidecar.write_text(json.dumps({
        "warnings": {
            "rsi_14": {
                "code": "IND-003",
                "indicator": "rsi_14",
                "rows": 1,
                "nan_rows": 1,
                "nan_ratio": 1.0,
            }
        }
    }))

    from echolon.data.loaders.backtest_data_loader import load_backtest_data

    ctx = _make_ctx(instrument)

    # Provide a market_data_dir with the calendar file so the loader gets past
    # the second half. The sidecar warning fires regardless of what happens
    # after the indicators read.
    md_dir = tmp_path / "md"
    (md_dir / "SHFE" / instrument).mkdir(parents=True)
    (md_dir / "SHFE" / instrument / "trading_calendar.csv").write_text(
        "date,is_trading_day\n2024-01-01,1\n"
    )

    with caplog.at_level("WARNING", logger="echolon.data.loaders.backtest_data_loader"):
        try:
            load_backtest_data(
                ctx,
                indicator_dir=indicator_dir,
                market_data_dir=md_dir,
            )
        except Exception:
            # Any downstream failure (e.g., ctx.encode_phase not set on our
            # hand-constructed TradingContext) is fine — we only need the
            # sidecar WARNING to have fired before that.
            pass

    assert any("IND-003" in r.message for r in caplog.records), \
        "expected IND-003 in a WARNING log from backtest_data_loader"
    assert any("rsi_14" in r.message for r in caplog.records)


def test_no_sidecar_means_no_warning(tmp_path, caplog):
    """When the sidecar is absent, no IND-003 warning fires."""
    indicator_dir = tmp_path / "indicators"
    instrument = "aluminum"
    (indicator_dir / instrument).mkdir(parents=True)
    csv_path = indicator_dir / instrument / "strategy_indicators.csv"
    pd.DataFrame({"date": ["2024-01-01"], "rsi_14": [50.0]}).to_csv(csv_path, index=False)

    from echolon.data.loaders.backtest_data_loader import load_backtest_data

    ctx = _make_ctx(instrument)

    md_dir = tmp_path / "md"
    (md_dir / "SHFE" / instrument).mkdir(parents=True)
    (md_dir / "SHFE" / instrument / "trading_calendar.csv").write_text(
        "date,is_trading_day\n2024-01-01,1\n"
    )

    with caplog.at_level("WARNING", logger="echolon.data.loaders.backtest_data_loader"):
        try:
            load_backtest_data(ctx, indicator_dir=indicator_dir, market_data_dir=md_dir)
        except Exception:
            pass

    assert not any("IND-003" in r.message for r in caplog.records)
