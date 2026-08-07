"""Bounded loading of trusted project-local Python modules."""

import hashlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType


@dataclass(frozen=True, slots=True)
class LoadedLocalModule:
    module_path: Path
    project_relative_path: str
    source_hash: str
    module: ModuleType


class LocalModuleLoader:
    """Confine one trusted Python file to the configured project extension root."""

    def __init__(self, *, project_root: Path, extension_root: Path) -> None:
        self._project_root = project_root.resolve()
        self._extension_root = extension_root.resolve()
        if not self._extension_root.is_relative_to(self._project_root):
            raise ValueError("extension root must be inside the project root")

    def load(
        self,
        relative: str,
        *,
        module_prefix: str = "_qlibx_local_extension",
    ) -> LoadedLocalModule:
        module_path = self._resolve_module_path(relative)
        source_hash = hashlib.sha256(module_path.read_bytes()).hexdigest()
        name = f"{module_prefix}_{source_hash[:24]}"
        module_spec = importlib.util.spec_from_file_location(name, module_path)
        if module_spec is None or module_spec.loader is None:
            raise ValueError("local extension module cannot be loaded")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return LoadedLocalModule(
            module_path=module_path,
            project_relative_path=module_path.relative_to(self._project_root).as_posix(),
            source_hash=source_hash,
            module=module,
        )

    def registered_source_hash(self, project_relative: str) -> str:
        """Hash registered source without importing it."""

        return hashlib.sha256(
            self._resolve_registered_path(project_relative).read_bytes()
        ).hexdigest()

    def load_registered(
        self,
        project_relative: str,
        *,
        module_prefix: str = "_qlibx_local_extension",
    ) -> LoadedLocalModule:
        """Reload an exact project-relative path recorded in registration evidence."""

        module_path = self._resolve_registered_path(project_relative)
        relative = module_path.relative_to(self._extension_root).as_posix()
        return self.load(relative, module_prefix=module_prefix)

    def _resolve_module_path(self, relative: str) -> Path:
        normalized = PurePosixPath(relative.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts or normalized.suffix != ".py":
            raise ValueError("module_path must be a relative .py path without '..'")
        candidate = (self._extension_root / normalized.as_posix()).resolve()
        if not candidate.is_relative_to(self._extension_root) or not candidate.is_file():
            raise ValueError("module_path must identify a file inside the project extension root")
        return candidate

    def _resolve_registered_path(self, project_relative: str) -> Path:
        normalized = PurePosixPath(project_relative.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts or normalized.suffix != ".py":
            raise ValueError("registered module_path must be a project-relative .py path")
        candidate = (self._project_root / normalized.as_posix()).resolve()
        if not candidate.is_relative_to(self._extension_root) or not candidate.is_file():
            raise ValueError(
                "registered module_path must identify a file inside the extension root"
            )
        return candidate