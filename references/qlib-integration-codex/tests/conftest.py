from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


CONTRACT_TEST_ROOT = Path(__file__).resolve().parent
INTEGRATION_ROOT = CONTRACT_TEST_ROOT.parent
RUN_CONTRACTS = os.environ.get("KWAM_RUN_QLIB_CONTRACTS") == "1"

if str(INTEGRATION_ROOT) not in sys.path:
    sys.path.insert(0, str(INTEGRATION_ROOT))


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if RUN_CONTRACTS:
        return
    marker = pytest.mark.skip(
        reason=(
            "Qlib migration contract tests are opt-in until implementation starts. "
            "Set KWAM_RUN_QLIB_CONTRACTS=1 to measure red/green state."
        )
    )
    for item in items:
        item_path = Path(str(item.path)).resolve()
        if item_path == CONTRACT_TEST_ROOT or CONTRACT_TEST_ROOT in item_path.parents:
            item.add_marker(marker)


@pytest.fixture(scope="session")
def backend_harness():
    """Production API가 아니라 test-only capability adapter를 불러옵니다."""

    module_name = os.environ.get(
        "KWAM_QLIB_ACCEPTANCE_ADAPTER",
        "kwam_qlib_backend.acceptance_adapter",
    )
    module = importlib.import_module(module_name)
    return module.build_harness()
