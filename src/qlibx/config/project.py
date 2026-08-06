"""Project-owned configuration and safe initialization."""

import os
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import field_validator

from qlibx.models import QlibxModel


class ProjectConfig(QlibxModel):
    """Portable locations owned by a qlibx user project."""

    schema_version: Literal[1] = 1
    data_dir: str = ".qlibx/data"
    artifact_dir: str = ".qlibx/artifacts"
    catalog_path: str = ".qlibx/catalog.duckdb"
    extension_dir: str = "qlibx_extensions"

    @field_validator("data_dir", "artifact_dir", "catalog_path", "extension_dir")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("project locations must be non-empty relative paths without '..'")
        return path.as_posix()


class ChangeAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"


class PlannedChange(QlibxModel):
    path: str
    action: ChangeAction


class ProjectInitResult(QlibxModel):
    root: str
    applied: bool
    changes: tuple[PlannedChange, ...]


def config_payload(config: ProjectConfig) -> str:
    return yaml.safe_dump(config.model_dump(mode="json"), sort_keys=True, allow_unicode=True)


def preview_project(root: Path, config: ProjectConfig) -> ProjectInitResult:
    root = root.resolve()
    config_path = root / "qlibx.yaml"
    expected = config_payload(config)
    if not config_path.exists():
        config_action = ChangeAction.CREATE
    elif config_path.read_text(encoding="utf-8") == expected:
        config_action = ChangeAction.UNCHANGED
    else:
        config_action = ChangeAction.CONFLICT

    changes = [PlannedChange(path=str(config_path), action=config_action)]
    for relative in (config.data_dir, config.artifact_dir, config.extension_dir):
        path = root / relative
        action = ChangeAction.UNCHANGED if path.is_dir() else ChangeAction.CREATE
        changes.append(PlannedChange(path=str(path), action=action))
    catalog_parent = (root / config.catalog_path).parent
    action = ChangeAction.UNCHANGED if catalog_parent.is_dir() else ChangeAction.CREATE
    changes.append(PlannedChange(path=str(catalog_parent), action=action))
    return ProjectInitResult(root=str(root), applied=False, changes=tuple(changes))


def apply_project(root: Path, config: ProjectConfig) -> ProjectInitResult:
    preview = preview_project(root, config)
    conflicts = [
        change.path for change in preview.changes if change.action is ChangeAction.CONFLICT
    ]
    if conflicts:
        raise FileExistsError(f"refusing to overwrite project-owned files: {conflicts}")

    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for relative in (config.data_dir, config.artifact_dir, config.extension_dir):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / config.catalog_path).parent.mkdir(parents=True, exist_ok=True)

    config_path = root / "qlibx.yaml"
    if not config_path.exists():
        temporary = config_path.with_suffix(".yaml.tmp")
        temporary.write_text(config_payload(config), encoding="utf-8", newline="\n")
        os.replace(temporary, config_path)

    return ProjectInitResult(root=str(root), applied=True, changes=preview.changes)


def load_project_config(root: Path) -> ProjectConfig:
    payload = yaml.safe_load((root.resolve() / "qlibx.yaml").read_text(encoding="utf-8"))
    return ProjectConfig.model_validate(payload)
