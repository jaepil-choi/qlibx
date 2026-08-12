from pathlib import Path

import pytest

from tests.acceptance.real_dw_support import (
    RealDwProject,
    create_real_dw_project,
    extract_real_dw_rows,
)


@pytest.fixture(scope="session")
def bounded_characterization_dw_source(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    destination = tmp_path_factory.mktemp("characterization-real-dw") / "dw-real-market.parquet"
    extract_real_dw_rows(destination)
    return destination


@pytest.fixture
def characterization_dw_case(
    tmp_path: Path,
    bounded_characterization_dw_source: Path,
) -> RealDwProject:
    return create_real_dw_project(
        tmp_path / "project",
        bounded_characterization_dw_source,
    )
