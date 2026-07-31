"""run_data_pipeline is file-only; live has its own entry point."""
import inspect


def test_run_data_pipeline_has_no_source_or_client_params():
    from echolon.data.backtest_data import run_data_pipeline
    sig = inspect.signature(run_data_pipeline)
    assert "source" not in sig.parameters
    assert "client" not in sig.parameters
    assert "present_date" not in sig.parameters


def test_run_live_data_update_requires_client():
    from echolon.data.live_data import run_live_data_update
    sig = inspect.signature(run_live_data_update)
    assert "ctx" in sig.parameters
    assert "client" in sig.parameters
    # client should be required (no default)
    assert sig.parameters["client"].default is inspect.Parameter.empty
