"""Opt-in materialization of version-matched, product-owned sample files."""

import hashlib
import os
from pathlib import Path

from qlibx.config import ChangeAction
from qlibx.models import QlibxModel


class SampleChange(QlibxModel):
    path: str
    action: ChangeAction
    expected_fingerprint: str


class SampleMaterializationResult(QlibxModel):
    sample_id: str
    destination: str
    applied: bool
    changes: tuple[SampleChange, ...]
    error: str | None = None


class SampleMaterializer:
    """Preview or copy one bundled sample without overwriting user changes."""

    sample_id = "basic-real-dw-journey-v1"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root.resolve()
        self._source = Path(__file__).parent / "resources" / "samples" / "basic"
        self._destination = self._project_root / "examples" / "qlibx_owned" / "basic"

    def materialize(self, *, apply: bool = False) -> SampleMaterializationResult:
        files = {
            path.relative_to(self._source): path.read_bytes()
            for path in sorted(self._source.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts
        }
        changes = tuple(
            self._change(relative, payload)
            for relative, payload in files.items()
        )
        conflicts = tuple(
            change.path
            for change in changes
            if change.action is ChangeAction.CONFLICT
        )
        if conflicts:
            return SampleMaterializationResult(
                sample_id=self.sample_id,
                destination=str(self._destination),
                applied=False,
                changes=changes,
                error=f"refusing to overwrite modified sample files: {conflicts}",
            )
        if apply:
            for relative, payload in files.items():
                destination = self._destination / relative
                if not destination.exists():
                    self._atomic_write(destination, payload)
        return SampleMaterializationResult(
            sample_id=self.sample_id,
            destination=str(self._destination),
            applied=apply,
            changes=changes,
        )

    def _change(self, relative: Path, payload: bytes) -> SampleChange:
        destination = self._destination / relative
        expected = hashlib.sha256(payload).hexdigest()
        if not destination.exists():
            action = ChangeAction.CREATE
        elif hashlib.sha256(destination.read_bytes()).hexdigest() == expected:
            action = ChangeAction.UNCHANGED
        else:
            action = ChangeAction.CONFLICT
        return SampleChange(
            path=str(destination),
            action=action,
            expected_fingerprint=expected,
        )

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)
