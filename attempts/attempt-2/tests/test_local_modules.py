import hashlib
import sys
from pathlib import Path

import pytest

from qlibx.extensions.local_modules import (
    LocalModuleLoader,
    LocalModuleSourceDriftError,
)


def make_loader(tmp_path: Path) -> tuple[LocalModuleLoader, Path]:
    extension_root = tmp_path / "extensions"
    extension_root.mkdir()
    return (
        LocalModuleLoader(project_root=tmp_path, extension_root=extension_root),
        extension_root,
    )


def test_loader_executes_the_exact_bytes_it_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, extension_root = make_loader(tmp_path)
    module_path = extension_root / "strategy.py"
    original_source = b"VALUE = 'validated'\n"
    module_path.write_bytes(original_source)
    expected_hash = hashlib.sha256(original_source).hexdigest()
    original_read_bytes = Path.read_bytes
    source_reads = 0

    def read_then_swap(path: Path) -> bytes:
        nonlocal source_reads
        payload = original_read_bytes(path)
        if path.resolve() == module_path.resolve():
            source_reads += 1
            module_path.write_text("VALUE = 'swapped'\n", encoding="utf-8")
        return payload

    monkeypatch.setattr(Path, "read_bytes", read_then_swap)

    loaded = loader.load("strategy.py", expected_source_hash=expected_hash)

    assert source_reads == 1
    assert loaded.source_hash == expected_hash
    assert loaded.module.VALUE == "validated"
    assert module_path.read_text(encoding="utf-8") == "VALUE = 'swapped'\n"


def test_loader_rejects_unregistered_bytes_before_execution(tmp_path: Path) -> None:
    loader, extension_root = make_loader(tmp_path)
    module_path = extension_root / "strategy.py"
    module_path.write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")

    with pytest.raises(LocalModuleSourceDriftError) as captured:
        loader.load("strategy.py", expected_source_hash="0" * 64)

    assert captured.value.expected_source_hash == "0" * 64
    assert captured.value.actual_source_hash == hashlib.sha256(module_path.read_bytes()).hexdigest()


def test_loader_registers_deferred_annotation_module_and_reuses_identity(
    tmp_path: Path,
) -> None:
    loader, extension_root = make_loader(tmp_path)
    module_path = extension_root / "models.py"
    module_path.write_text(
        """from __future__ import annotations
from qlibx.models import QlibxModel

class Row(QlibxModel):
    instrument: str

class Payload(QlibxModel):
    rows: tuple[Row, ...]
""",
        encoding="utf-8",
    )

    first = loader.load("models.py")
    second = loader.load("models.py")
    payload = first.module.Payload(rows=({"instrument": "A"},))

    assert sys.modules[first.module.__name__] is first.module
    assert second.module is first.module
    assert second.module.Payload is first.module.Payload
    assert first.module.Payload.model_json_schema()["$defs"]["Row"]["title"] == "Row"
    assert payload.rows[0].instrument == "A"


def test_loader_does_not_share_cached_modules_across_projects(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first_loader, first_extensions = make_loader(first_root)
    second_loader, second_extensions = make_loader(second_root)
    source = "class Marker:\n    pass\n"
    (first_extensions / "same.py").write_text(source, encoding="utf-8")
    (second_extensions / "same.py").write_text(source, encoding="utf-8")

    first = first_loader.load("same.py")
    second = second_loader.load("same.py")

    assert first.module is not second.module
    assert first.module.Marker is not second.module.Marker


def test_failed_import_does_not_leak_sys_modules_entry(tmp_path: Path) -> None:
    loader, extension_root = make_loader(tmp_path)
    (extension_root / "broken.py").write_text(
        "raise RuntimeError('broken import')\n",
        encoding="utf-8",
    )
    before = {
        name for name in sys.modules if name.startswith("_qlibx_failed_import_test_")
    }

    with pytest.raises(RuntimeError, match="broken import"):
        loader.load("broken.py", module_prefix="_qlibx_failed_import_test")

    after = {
        name for name in sys.modules if name.startswith("_qlibx_failed_import_test_")
    }
    assert after == before