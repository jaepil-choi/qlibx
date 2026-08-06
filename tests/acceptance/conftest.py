from pathlib import Path

import pytest

from tests.acceptance.real_dw_support import (
    RealDwProject,
    create_real_dw_project,
    extract_real_dw_rows,
    extract_real_k200_rows,
    register_real_k200_benchmark,
)


@pytest.fixture(scope="session")
def bounded_real_dw_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    destination = tmp_path_factory.mktemp("real-dw") / "dw-real-market.parquet"
    extract_real_dw_rows(destination)
    return destination


@pytest.fixture
def real_dw_case(tmp_path: Path, bounded_real_dw_source: Path) -> RealDwProject:
    return create_real_dw_project(tmp_path / "project", bounded_real_dw_source)


@pytest.fixture(scope="session")
def bounded_real_k200_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    destination = tmp_path_factory.mktemp("real-k200") / "real-k200-benchmark.parquet"
    extract_real_k200_rows(destination)
    return destination


@pytest.fixture
def real_dw_constraint_case(
    tmp_path: Path,
    bounded_real_dw_source: Path,
    bounded_real_k200_source: Path,
) -> RealDwProject:
    case = create_real_dw_project(tmp_path / "constraint-project", bounded_real_dw_source)
    return register_real_k200_benchmark(case, bounded_real_k200_source)
