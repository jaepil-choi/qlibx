from pathlib import Path

import pytest

from qlibx import QlibxProject
from qlibx.config import ChangeAction


def test_project_init_is_preview_only_by_default(tmp_path: Path) -> None:
    root = tmp_path / "research"
    result = QlibxProject.init(root)

    assert result.applied is False
    assert result.changes[0].action is ChangeAction.CREATE
    assert not root.exists()


def test_project_init_apply_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "research"
    first = QlibxProject.init(root, apply=True)
    second = QlibxProject.init(root, apply=True)

    assert first.applied is True
    assert second.applied is True
    assert all(change.action is ChangeAction.UNCHANGED for change in second.changes)
    assert QlibxProject.open(root).root == root.resolve()


def test_project_reuses_one_artifact_backend(tmp_path: Path) -> None:
    root = tmp_path / "research"
    QlibxProject.init(root, apply=True)
    project = QlibxProject.open(root)

    assert project.artifacts is project.artifacts


def test_project_init_does_not_overwrite_existing_config(tmp_path: Path) -> None:
    root = tmp_path / "research"
    root.mkdir()
    config = root / "qlibx.yaml"
    config.write_text("user: owned\n", encoding="utf-8")

    preview = QlibxProject.init(root)
    assert preview.changes[0].action is ChangeAction.CONFLICT

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        QlibxProject.init(root, apply=True)
    assert config.read_text(encoding="utf-8") == "user: owned\n"
