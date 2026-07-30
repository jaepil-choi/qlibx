"""Project ownership and path boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from qlibx.config import read_yaml, require_mapping, require_string
from qlibx.errors import QlibxError

MANIFEST = "qlibx.yaml"


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    config: Path
    source_data: Path
    generated_data: Path
    state: Path
    research: Path
    extensions: Path


@dataclass(frozen=True, slots=True)
class Project:
    root: Path
    paths: ProjectPaths

    @classmethod
    def load(cls, root: str | Path = ".") -> Project:
        selected = Path(root).resolve()
        manifest = read_yaml(selected / MANIFEST)
        if manifest.get("schema_version") != 1:
            raise QlibxError(
                "UNSUPPORTED",
                "qlibx.yaml schema_version must be 1",
                action="Use the installed project schema.",
            )
        raw_paths = require_mapping(manifest.get("paths"), "paths")
        resolved: dict[str, Path] = {}
        defaults = {"research": "qlibx-research", "extensions": "qlibx-custom"}
        for name in ("config", "source_data", "generated_data", "state", "research", "extensions"):
            raw = raw_paths.get(name, defaults.get(name))
            path = (selected / require_string(raw, f"paths.{name}")).resolve()
            if not path.is_relative_to(selected):
                raise QlibxError(
                    "BOUNDARY",
                    f"paths.{name} escapes the project: {path}",
                    action="Use a project-relative contained path.",
                )
            resolved[name] = path
        return cls(selected, ProjectPaths(**resolved))

    @classmethod
    def initialize(cls, root: str | Path = ".") -> Project:
        selected = Path(root).resolve()
        selected.mkdir(parents=True, exist_ok=True)
        path = selected / MANIFEST
        if not path.exists():
            payload = {
                "schema_version": 1,
                "paths": {
                    "config": "config/qlibx",
                    "source_data": "data",
                    "generated_data": "data/qlibx",
                    "state": ".qlibx",
                    "research": "qlibx-research",
                    "extensions": "qlibx-custom",
                },
            }
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        project = cls.load(selected)
        for directory in (
            project.paths.config,
            project.paths.generated_data,
            project.paths.state,
            project.paths.research,
            project.paths.extensions,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return project

    def contained(self, path: str | Path) -> Path:
        selected = (
            (self.root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        )
        if not selected.is_relative_to(self.root):
            raise QlibxError(
                "BOUNDARY",
                f"Path escapes the project: {selected}",
                action="Use a path below the project root.",
            )
        return selected
