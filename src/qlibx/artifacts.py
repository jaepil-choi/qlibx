"""Portable, hash-verified stage artifacts and intermediate recording."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from qlibx.project import Project
from qlibx.serialization import (
    canonical_bytes,
    digest_document,
    digest_file,
    validate_name,
)
from qlibx.strategy import DecisionResult

ArtifactStatus = Literal["complete", "incomplete", "invalid"]


@dataclass(frozen=True, slots=True)
class ArtifactEnvelope:
    artifact_type: str
    schema_version: int
    artifact_id: str
    run_id: str
    name: str
    producer_id: str
    producer_version: str
    implementation_digest: str
    parent_artifact_ids: tuple[str, ...]
    input_artifact_ids: tuple[str, ...]
    time_range: tuple[str | None, str | None]
    axis: str | None
    index_semantics: str | None
    unit: str | None
    currency: str | None
    timezone: str | None
    data_semantics: str
    payload_format: Literal["parquet", "json"]
    payload_path: Path
    payload_digest: str
    coverage: Mapping[str, Any]
    warnings: tuple[str, ...]
    diagnostics: Mapping[str, Any]
    status: ArtifactStatus


class ArtifactStore:
    """Run-local artifact materialization independent of producer implementation type."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_project(cls, project: Project) -> ArtifactStore:
        return cls(project.paths.state / "artifacts")

    def record(
        self,
        *,
        run_id: str,
        name: str,
        value: Any,
        artifact_type: str,
        producer_id: str,
        producer_version: str,
        implementation_digest: str,
        parent_artifact_ids: Sequence[str] = (),
        input_artifact_ids: Sequence[str] = (),
        time_range: tuple[str | None, str | None] = (None, None),
        axis: str | None = None,
        index_semantics: str | None = None,
        unit: str | None = None,
        currency: str | None = None,
        timezone: str | None = None,
        data_semantics: str,
        coverage: Mapping[str, Any] | None = None,
        warnings: Sequence[str] = (),
        diagnostics: Mapping[str, Any] | None = None,
        status: ArtifactStatus = "complete",
    ) -> ArtifactEnvelope:
        validate_name(name)
        if status not in {"complete", "incomplete", "invalid"}:
            raise ValueError(f"unsupported artifact status: {status}")
        staging = self.root / f".tmp-{uuid.uuid4().hex}"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            payload_format, payload = _write_payload(staging, value)
            payload_digest = digest_file(payload)
            identity = {
                "schema_version": 1,
                "artifact_type": artifact_type,
                "run_id": run_id,
                "name": name,
                "producer_id": producer_id,
                "producer_version": producer_version,
                "implementation_digest": implementation_digest,
                "parents": list(parent_artifact_ids),
                "inputs": list(input_artifact_ids),
                "payload_digest": payload_digest,
                "data_semantics": data_semantics,
                "status": status,
            }
            artifact_id = digest_document(identity)
            final = self.root / run_id / artifact_id
            envelope = ArtifactEnvelope(
                artifact_type=artifact_type,
                schema_version=1,
                artifact_id=artifact_id,
                run_id=run_id,
                name=name,
                producer_id=producer_id,
                producer_version=producer_version,
                implementation_digest=implementation_digest,
                parent_artifact_ids=tuple(parent_artifact_ids),
                input_artifact_ids=tuple(input_artifact_ids),
                time_range=time_range,
                axis=axis,
                index_semantics=index_semantics,
                unit=unit,
                currency=currency,
                timezone=timezone,
                data_semantics=data_semantics,
                payload_format=payload_format,
                payload_path=final / payload.name,
                payload_digest=payload_digest,
                coverage=dict(coverage or {}),
                warnings=tuple(warnings),
                diagnostics=dict(diagnostics or {}),
                status=status,
            )
            (staging / "envelope.json").write_bytes(canonical_bytes(_envelope_json(envelope)))
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists():
                existing = self.load(artifact_id, run_id=run_id)
                if _envelope_json(existing) != _envelope_json(envelope):
                    raise ValueError(f"artifact identity conflict: {artifact_id}")
                return existing
            os.replace(staging, final)
            return envelope
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def load(self, artifact_id: str, *, run_id: str | None = None) -> ArtifactEnvelope:
        candidates = (
            [self.root / run_id / artifact_id]
            if run_id is not None
            else list(self.root.glob(f"*/{artifact_id}"))
        )
        if len(candidates) != 1 or not candidates[0].is_dir():
            raise ValueError(f"unknown or ambiguous artifact: {artifact_id}")
        directory = candidates[0]
        raw = json.loads((directory / "envelope.json").read_text(encoding="utf-8"))
        payload = directory / raw.pop("payload_file")
        for key in ("parent_artifact_ids", "input_artifact_ids", "time_range", "warnings"):
            raw[key] = tuple(raw[key])
        envelope = ArtifactEnvelope(payload_path=payload, **raw)
        if digest_file(payload) != envelope.payload_digest:
            raise ValueError(f"artifact payload is corrupt: {artifact_id}")
        return envelope

    def load_payload(self, artifact_id: str, *, run_id: str | None = None) -> Any:
        envelope = self.load(artifact_id, run_id=run_id)
        if envelope.payload_format == "parquet":
            return pd.read_parquet(envelope.payload_path)
        return json.loads(envelope.payload_path.read_text(encoding="utf-8"))

    def export_bundle(self, artifact_ids: Sequence[str], output: str | Path) -> Path:
        destination = Path(output).resolve()
        if destination.exists() and any(destination.iterdir()):
            raise ValueError(f"export destination is not empty: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        entries: list[Mapping[str, Any]] = []
        for artifact_id in artifact_ids:
            envelope = self.load(artifact_id)
            if envelope.status != "complete":
                raise ValueError(f"only complete artifacts are portable: {artifact_id}")
            artifact_dir = destination / artifact_id
            artifact_dir.mkdir()
            payload = artifact_dir / envelope.payload_path.name
            shutil.copy2(envelope.payload_path, payload)
            envelope_path = artifact_dir / "envelope.json"
            envelope_path.write_bytes(canonical_bytes(_envelope_json(envelope)))
            entries.append(
                {
                    "artifact_id": artifact_id,
                    "run_id": envelope.run_id,
                    "payload_digest": envelope.payload_digest,
                    "envelope_digest": digest_file(envelope_path),
                }
            )
        manifest = {
            "schema_version": 1,
            "portable_formats": ["json", "parquet"],
            "artifacts": entries,
        }
        (destination / "bundle.json").write_bytes(canonical_bytes(manifest))
        return destination

    def import_bundle(self, bundle: str | Path) -> tuple[ArtifactEnvelope, ...]:
        source = Path(bundle).resolve()
        manifest = json.loads((source / "bundle.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1:
            raise ValueError("unsupported artifact bundle schema")
        imported: list[ArtifactEnvelope] = []
        for item in manifest["artifacts"]:
            directory = source / item["artifact_id"]
            envelope_path = directory / "envelope.json"
            if digest_file(envelope_path) != item["envelope_digest"]:
                raise ValueError(f"corrupt artifact envelope: {item['artifact_id']}")
            raw = json.loads(envelope_path.read_text(encoding="utf-8"))
            payload = directory / raw["payload_file"]
            if digest_file(payload) != item["payload_digest"]:
                raise ValueError(f"corrupt artifact payload: {item['artifact_id']}")
            final = self.root / item["run_id"] / item["artifact_id"]
            final.parent.mkdir(parents=True, exist_ok=True)
            if not final.exists():
                temporary = final.parent / f".tmp-{uuid.uuid4().hex}"
                shutil.copytree(directory, temporary)
                os.replace(temporary, final)
            imported.append(self.load(item["artifact_id"], run_id=item["run_id"]))
        return tuple(imported)


def record_decision_intermediates(
    store: ArtifactStore,
    result: DecisionResult,
    *,
    run_id: str,
    producer_id: str,
    producer_version: str,
    implementation_digest: str,
) -> tuple[ArtifactEnvelope, ...]:
    output: list[ArtifactEnvelope] = []
    parent = () if result.primary_result_id is None else (result.primary_result_id,)
    for record in sorted(result.intermediates, key=lambda item: item.sequence):
        output.append(
            store.record(
                run_id=run_id,
                name=record.name,
                value=record.payload,
                artifact_type="strategy_intermediate",
                producer_id=producer_id,
                producer_version=producer_version,
                implementation_digest=implementation_digest,
                parent_artifact_ids=parent,
                data_semantics="strategy-declared intermediate result",
                diagnostics={"sequence": record.sequence, **dict(record.metadata)},
            )
        )
    return tuple(output)


def _write_payload(directory: Path, value: Any) -> tuple[Literal["parquet", "json"], Path]:
    if isinstance(value, pd.Series):
        value = value.to_frame(value.name or "value")
    if isinstance(value, pd.DataFrame):
        path = directory / "payload.parquet"
        value.to_parquet(path, index=True)
        return "parquet", path
    path = directory / "payload.json"
    path.write_bytes(canonical_bytes(value))
    return "json", path


def _envelope_json(envelope: ArtifactEnvelope) -> Mapping[str, Any]:
    raw = asdict(envelope)
    raw.pop("payload_path")
    raw["payload_file"] = envelope.payload_path.name
    return raw
