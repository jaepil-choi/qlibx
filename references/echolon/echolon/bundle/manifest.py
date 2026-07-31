"""Release bundle manifest support."""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BundleSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_id: str
    family: str
    file: str
    sha256: str
    params_file: str
    gate_record: str


class BundleManifest(BaseModel):
    """P3/S5 release bundle manifest."""

    model_config = ConfigDict(extra="forbid")

    schema: Literal["bundle/v1"] = "bundle/v1"
    bundle_version: str
    created_at: dt.datetime = Field(
        default_factory=lambda: dt.datetime.now(dt.UTC).replace(microsecond=0)
    )
    echolon_version: str
    panel_snapshot: dict[str, str]
    signals: list[BundleSignal]
    blend: dict[str, float]
    constructor: dict
    risk: dict
    expectations: str
    provenance: dict[str, str]
    approval: dict[str, str]
    files: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_blend(self) -> "BundleManifest":
        total = sum(float(value) for value in self.blend.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError("blend weights must sum to 1.0")
        return self


def write_bundle_manifest(bundle_dir: Path, manifest: BundleManifest) -> BundleManifest:
    """Write ``manifest.json`` with total file hash coverage."""
    root = Path(bundle_dir)
    files = _hash_bundle_files(root)
    updated_signals = []
    for signal in manifest.signals:
        if signal.file in files:
            updated_signals.append(signal.model_copy(update={"sha256": files[signal.file]}))
        else:
            updated_signals.append(signal)
    updated = manifest.model_copy(update={"signals": updated_signals, "files": files})
    (root / "manifest.json").write_text(
        updated.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return updated


def load_bundle(bundle_dir: Path) -> BundleManifest:
    """Load and verify all bundle file hashes."""
    root = Path(bundle_dir)
    manifest = BundleManifest.model_validate_json((root / "manifest.json").read_text(encoding="utf-8"))
    actual_files = _hash_bundle_files(root)
    if set(actual_files) != set(manifest.files):
        raise ValueError("bundle file coverage mismatch")
    for relpath, expected in manifest.files.items():
        actual = actual_files[relpath]
        if actual != expected:
            raise ValueError(f"hash mismatch for {relpath}: expected {expected}, got {actual}")
    for signal in manifest.signals:
        expected = manifest.files.get(signal.file)
        if expected is not None and signal.sha256 != expected:
            raise ValueError(f"signal hash mismatch for {signal.signal_id}")
    return manifest


def _hash_bundle_files(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relpath = path.relative_to(root).as_posix()
        if relpath == "manifest.json":
            continue
        files[relpath] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files
