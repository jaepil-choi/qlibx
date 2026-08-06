from pathlib import Path

import pytest

from tests.acceptance.real_dw_support import (
    RealDwProject,
    create_real_dw_project,
    extract_real_dw_rows,
    extract_real_extension_market_rows,
    extract_real_extension_sector_rows,
    extract_real_k200_rows,
    extract_real_lookthrough_rows,
    register_real_extension_inputs,
    register_real_k200_benchmark,
    register_real_lookthrough_constituents,
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


@pytest.fixture(scope="session")
def bounded_real_lookthrough_source(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    destination = (
        tmp_path_factory.mktemp("real-lookthrough")
        / "real-k200-etf-constituents.parquet"
    )
    extract_real_lookthrough_rows(destination)
    return destination


@pytest.fixture
def real_dw_lookthrough_case(
    real_dw_constraint_case: RealDwProject,
    bounded_real_lookthrough_source: Path,
) -> RealDwProject:
    return register_real_lookthrough_constituents(
        real_dw_constraint_case,
        bounded_real_lookthrough_source,
    )


@pytest.fixture(scope="session")
def bounded_real_extension_sources(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path]:
    directory = tmp_path_factory.mktemp("real-extension")
    market = directory / "real-extension-market.parquet"
    sector = directory / "real-extension-sector.parquet"
    extract_real_extension_market_rows(market)
    extract_real_extension_sector_rows(sector)
    return market, sector


@pytest.fixture
def real_dw_extension_case(
    real_dw_case: RealDwProject,
    bounded_real_extension_sources: tuple[Path, Path],
) -> RealDwProject:
    return register_real_extension_inputs(
        real_dw_case,
        bounded_real_extension_sources[0],
        bounded_real_extension_sources[1],
    )
