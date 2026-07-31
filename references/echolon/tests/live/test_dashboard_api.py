"""Tests for public dashboard aggregator API.

Goingmerry (later task) should be able to:
    from echolon.live import aggregate_portfolio, load_slot_state
without touching any POST/sender helpers.
"""
import inspect


def test_aggregator_is_public_export():
    from echolon.live import aggregate_portfolio  # noqa: F401


def test_load_slot_state_is_public_export():
    from echolon.live import load_slot_state  # noqa: F401


def test_load_equity_curve_is_public_export():
    from echolon.live import load_equity_curve  # noqa: F401


def test_sender_helpers_are_removed():
    """HTTP POST helpers must no longer exist in echolon (moved to goingmerry)."""
    import echolon.live.io.kpi_aggregator as dash
    assert not hasattr(dash, "send_dashboard_data")
    assert not hasattr(dash, "send_portfolio_dashboard_data")
    assert not hasattr(dash, "_post_json")


def test_aggregate_portfolio_signature_takes_workspace_dir():
    from echolon.live import aggregate_portfolio
    sig = inspect.signature(aggregate_portfolio)
    assert "deploy_config" in sig.parameters
    assert "workspace_dir" in sig.parameters
    # portfolio_equity / portfolio_peak must NOT be required (caller shouldn't need them)
    # (Either absent from signature, or have defaults.)
    for name in ("portfolio_equity", "portfolio_peak"):
        if name in sig.parameters:
            assert sig.parameters[name].default is not inspect.Parameter.empty, \
                f"{name} should not be required on aggregate_portfolio"
