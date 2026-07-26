from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Mapping, Sequence
from uuid import uuid4

import pandas as pd

from qlib_extended.research.manifest import MemberWeight, MetricValue, RunSpec


ARTIFACT_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class ImmutableArtifactStore:
    """Worker가 catalog write 없이 immutable run directory를 publish합니다."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.staging_root = self.root / ".staging"

    def publish(
        self,
        spec: RunSpec,
        *,
        metrics: Sequence[MetricValue] = (),
        members: Sequence[MemberWeight] = (),
        frames: Mapping[str, pd.DataFrame] | None = None,
        provenance: Mapping[str, Any] | None = None,
    ) -> Path:
        frame_map = dict(frames or {})
        _validate_unique_metrics(metrics)
        _validate_unique_members(members)
        for name, frame in frame_map.items():
            if not ARTIFACT_NAME.fullmatch(name):
                raise ValueError(f"Invalid artifact name: {name!r}")
            if not isinstance(frame, pd.DataFrame):
                raise TypeError(f"Artifact {name} must be a pandas DataFrame.")

        self.staging_root.mkdir(parents=True, exist_ok=True)
        staging = self.staging_root / f"{spec.run_id}-{uuid4().hex}"
        final = self.root / spec.run_id
        staging.mkdir()
        try:
            artifact_manifest: dict[str, dict[str, Any]] = {}
            for name, frame in sorted(frame_map.items()):
                filename = f"{name}.parquet"
                path = staging / filename
                frame.to_parquet(path, index=True)
                artifact_manifest[name] = {
                    "path": filename,
                    "sha256": _file_hash(path),
                    "row_count": int(len(frame)),
                }
            manifest = {
                "schema_version": 1,
                "run": spec.to_dict(),
                "metrics": [item.to_dict() for item in sorted(
                    metrics, key=lambda item: (item.segment, item.metric)
                )],
                "members": [item.to_dict() for item in sorted(
                    members, key=lambda item: item.member_run_id
                )],
                "artifacts": artifact_manifest,
                "provenance": dict(provenance or {}),
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            validate_run_directory(staging, expected_run_id=spec.run_id)
            if final.exists():
                if _comparable_manifest(final) == _comparable_manifest(
                    staging, expected_run_id=spec.run_id
                ):
                    return final
                raise ValueError(
                    f"Immutable run collision with different content: {spec.run_id}"
                )
            os.replace(staging, final)
            return final
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def validate_run_directory(
    run_dir: Path,
    *,
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    resolved = run_dir.resolve()
    manifest_path = resolved / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing run manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError(f"Unsupported run manifest schema: {manifest_path}")
    run = manifest.get("run")
    required_run_id = expected_run_id or resolved.name
    if not isinstance(run, dict) or run.get("run_id") != required_run_id:
        raise ValueError(f"Manifest run_id does not match directory: {resolved}")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError(f"Manifest artifacts must be a mapping: {manifest_path}")
    for name, entry in artifacts.items():
        if not ARTIFACT_NAME.fullmatch(name) or not isinstance(entry, dict):
            raise ValueError(f"Invalid artifact manifest entry: {name!r}")
        relative = entry.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError(f"Artifact path must be relative: {name}")
        path = (resolved / relative).resolve()
        if resolved not in path.parents or not path.is_file():
            raise ValueError(f"Artifact escapes or is missing from run directory: {name}")
        if _file_hash(path) != entry.get("sha256"):
            raise ValueError(f"Artifact hash mismatch: {name}")
    return manifest


def _comparable_manifest(
    run_dir: Path,
    *,
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    manifest = validate_run_directory(run_dir, expected_run_id=expected_run_id)
    comparable = json.loads(json.dumps(manifest))
    comparable["run"].pop("created_at", None)
    return comparable


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_unique_metrics(metrics: Sequence[MetricValue]) -> None:
    keys = [(item.segment, item.metric) for item in metrics]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate metric segment/name in run manifest.")


def _validate_unique_members(members: Sequence[MemberWeight]) -> None:
    keys = [item.member_run_id for item in members]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate member_run_id in run manifest.")
