from __future__ import annotations

from qlibx.execution import open_run_catalog, run_strategy_batch


def test_package_owns_public_qlib_execution_surface() -> None:
    assert run_strategy_batch.__module__.startswith("qlibx._vendor.qlib_engine")
    assert open_run_catalog.__module__ == "qlibx.execution"
