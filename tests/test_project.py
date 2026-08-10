from datetime import UTC, datetime
from pathlib import Path

import pytest

from qlibx import OutcomeStatus, QlibxProject
from qlibx.config import ChangeAction
from qlibx.contracts import StrategyInvocation
from qlibx.evidence import CatalogSessionConflictError, LocalArtifactBackend


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


def test_project_operation_maps_catalog_session_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "research"
    QlibxProject.init(root, apply=True)
    project = QlibxProject.open(root)

    class BlockedSession:
        def __enter__(self) -> None:
            raise CatalogSessionConflictError(
                root / ".qlibx" / "catalog.duckdb",
                "held by test",
            )

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(LocalArtifactBackend, "session", lambda _backend: BlockedSession())
    outcome = project.invoke(
        object(),
        StrategyInvocation(
            invocation_id="catalog-session-conflict",
            evaluation_time=datetime(2025, 1, 2, tzinfo=UTC),
            config_fingerprint="config-v1",
        ),
    )

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "CATALOG_SESSION_CONFLICT"
    assert outcome.errors[0].retry_preconditions == (
        "retry after the active catalog session completes",
    )


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
