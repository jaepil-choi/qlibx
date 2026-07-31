"""Every code in ERROR_CATALOG has a corresponding markdown page.

Phase F-9a: error markdown pages moved from ``docs/errors/`` (repo root,
invisible to pip-installed users) into ``echolon/native/errors/codes/``
(package data, ships in wheel).
"""
from pathlib import Path

import echolon.native.errors as _native_errors
from echolon.errors import ERROR_CATALOG


_CODES_DIR = Path(_native_errors.__file__).parent / "codes"


def test_every_code_has_docs_page():
    missing = [code for code in ERROR_CATALOG if not (_CODES_DIR / f"{code}.md").exists()]
    assert not missing, f"Catalog codes missing docs pages: {missing}"


def test_index_references_every_code():
    """README.md inside the codes/ dir must mention every catalog code so a
    reader browsing the index sees the full catalog."""
    index = (_CODES_DIR / "README.md").read_text(encoding="utf-8")
    missing = [code for code in ERROR_CATALOG if code not in index]
    assert not missing, f"Index README missing catalog codes: {missing}"
