import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
USE_CASE = re.compile(r"\bUC-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{3}\b")


def ids(path: Path) -> set[str]:
    return set(USE_CASE.findall(path.read_text(encoding="utf-8")))


def test_architecture_traces_every_prd_use_case() -> None:
    prd_ids = ids(ROOT / "docs" / "qlibx-prd.md")
    architecture_ids = ids(ROOT / "docs" / "qlibx-architecture.md")
    assert prd_ids
    assert prd_ids <= architecture_ids, sorted(prd_ids - architecture_ids)
