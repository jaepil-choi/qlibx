from __future__ import annotations

from _acceptance_contract import BackendHarness


def test_test_adapter_exposes_capabilities_without_freezing_production_api(
    backend_harness,
) -> None:
    assert isinstance(backend_harness, BackendHarness)
