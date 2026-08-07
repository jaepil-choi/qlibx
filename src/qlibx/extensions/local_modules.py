"""Bounded loading of trusted project-local Python modules."""

import hashlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType


@dataclass(frozen=True, slots=True)
class LoadedLocalModule:
    module_path: Path
    project_relative_path: str
    source_hash: str
    module: ModuleType


class LocalModuleSourceDriftError(ValueError):
    """Raised before execution when source differs from registered evidence."""

    def __init__(self, *, expected_source_hash: str, actual_source_hash: str) -> None:
        self.expected_source_hash = expected_source_hash
        self.actual_source_hash = actual_source_hash
        super().__init__("current local extension source hash differs from registration")


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
        expected_source_hash: str | None = None,
    ) -> LoadedLocalModule:
        module_path = self._resolve_module_path(relative)
        return self._load_path(
            module_path,
            module_prefix=module_prefix,
            expected_source_hash=expected_source_hash,
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
        expected_source_hash: str | None = None,
    ) -> LoadedLocalModule:
        """Load an exact project-relative path recorded in registration evidence."""

        return self._load_path(
            self._resolve_registered_path(project_relative),
            module_prefix=module_prefix,
            expected_source_hash=expected_source_hash,
        )

    def _load_path(
        self,
        module_path: Path,
        *,
        module_prefix: str,
        expected_source_hash: str | None,
    ) -> LoadedLocalModule:
        source = module_path.read_bytes()
        source_hash = hashlib.sha256(source).hexdigest()
        if expected_source_hash is not None and source_hash != expected_source_hash:
            raise LocalModuleSourceDriftError(
                expected_source_hash=expected_source_hash,
                actual_source_hash=source_hash,
            )

        project_relative_path = module_path.relative_to(self._project_root).as_posix()
        name = self._module_name(
            module_prefix=module_prefix,
            project_relative_path=project_relative_path,
            source_hash=source_hash,
        )
        cached = sys.modules.get(name)
        if self._is_matching_cache_entry(
            cached,
            module_path=module_path,
            project_relative_path=project_relative_path,
            source_hash=source_hash,
        ):
            return LoadedLocalModule(
                module_path=module_path,
                project_relative_path=project_relative_path,
                source_hash=source_hash,
                module=cached,
            )

        module_spec = importlib.util.spec_from_file_location(name, module_path)
        if module_spec is None or module_spec.loader is None:
            raise ValueError("local extension module cannot be loaded")
        code = compile(source, str(module_path), "exec")
        module = importlib.util.module_from_spec(module_spec)
        module.__dict__["__qlibx_project_relative_path__"] = project_relative_path
        module.__dict__["__qlibx_source_hash__"] = source_hash
        previous = sys.modules.get(name)
        sys.modules[name] = module
        try:
            exec(code, module.__dict__)
        except BaseException:
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
            raise
        module.__dict__["__qlibx_project_relative_path__"] = project_relative_path
        module.__dict__["__qlibx_source_hash__"] = source_hash
        return LoadedLocalModule(
            module_path=module_path,
            project_relative_path=project_relative_path,
            source_hash=source_hash,
            module=module,
        )

    def _module_name(
        self,
        *,
        module_prefix: str,
        project_relative_path: str,
        source_hash: str,
    ) -> str:
        root_identity = hashlib.sha256(
            self._project_root.as_posix().casefold().encode("utf-8")
        ).hexdigest()[:12]
        path_identity = hashlib.sha256(project_relative_path.encode("utf-8")).hexdigest()[:12]
        return f"{module_prefix}_{root_identity}_{path_identity}_{source_hash[:24]}"

    @staticmethod
    def _is_matching_cache_entry(
        candidate: ModuleType | None,
        *,
        module_path: Path,
        project_relative_path: str,
        source_hash: str,
    ) -> bool:
        if candidate is None:
            return False
        candidate_file = getattr(candidate, "__file__", None)
        return (
            isinstance(candidate_file, str)
            and Path(candidate_file).resolve() == module_path
            and getattr(candidate, "__qlibx_project_relative_path__", None)
            == project_relative_path
            and getattr(candidate, "__qlibx_source_hash__", None) == source_hash
        )

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