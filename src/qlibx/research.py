"""Durable research history, frozen runs, and recoverable publication."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import duckdb
import pandas as pd

from qlibx.errors import QlibxError, unknown_name
from qlibx.orthogonality import AlphaDescriptor, OrthogonalityResult, compare_alpha
from qlibx.project import Project
from qlibx.serialization import (
    PayloadFormat,
    canonical_bytes,
    digest_bytes,
    digest_document,
    read_payload,
    validate_name,
)

RunStatus = Literal["successful", "failed", "invalid", "abandoned"]
DecisionKind = Literal["promote", "reject", "retain_diagnostic", "supersede"]

# Published records name their payload by media type. Everything else in qlibx names the
# same two formats `parquet` and `json`; this is the one place the two vocabularies meet.
_MEDIA_TYPE_FORMATS: Mapping[str, PayloadFormat] = {
    "application/json": "json",
    "application/x-parquet": "parquet",
}


@dataclass(frozen=True, slots=True)
class StagedAttempt:
    session_id: str
    invocation_id: str
    attempt_id: str
    result_key: str
    kind: str
    directory: Path


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    name: str
    media_type: str
    blob_digest: str
    size: int


@dataclass(frozen=True, slots=True)
class PublishedResult:
    result_key: str
    record_id: str
    attempt_id: str
    status: RunStatus
    cached: bool
    artifacts: tuple[ArtifactRecord, ...]


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    plan_path: Path
    manifest: Mapping[str, Any]
    staged_files: tuple[Path, ...]
    artifacts: tuple[ArtifactRecord, ...]


@dataclass(frozen=True, slots=True)
class FrozenRunBundle:
    bundle_id: str
    session_id: str
    path: Path
    config_digests: Mapping[str, str]
    dataset_snapshots: Mapping[str, str]
    component_versions: Mapping[str, str]
    seed: int


@dataclass(frozen=True, slots=True)
class ResearchProposal:
    hypothesis: str
    mechanism: str
    logical_datasets: tuple[str, ...]
    observation_clock: str
    holding_horizon: str
    strategy: str
    transforms: tuple[str, ...]
    parameter_range: Mapping[str, Any]
    evaluation_segment: Mapping[str, str]
    comparison_set: tuple[str, ...]
    cost_assumptions: Mapping[str, Any]
    capacity_assumptions: Mapping[str, Any]
    stopping_condition: str
    search_limit: int


@dataclass(frozen=True, slots=True)
class ProposalRecord:
    proposal_id: str
    session_id: str
    agent_id: str
    proposal: ResearchProposal
    version: int
    status: str


@dataclass(frozen=True, slots=True)
class ResearchDecision:
    target_id: str
    version: int
    decision: DecisionKind
    evidence_run_ids: tuple[str, ...]
    criteria: Mapping[str, Any]
    reviewer: str
    rationale: str


@dataclass(frozen=True, slots=True)
class ResearchContext:
    prior_results: tuple[Mapping[str, Any], ...]
    incomplete_attempts: tuple[Mapping[str, Any], ...]
    searched_parameter_ranges: tuple[Mapping[str, Any], ...]
    active_proposals: tuple[Mapping[str, Any], ...]
    nearest_neighbors: tuple[Mapping[str, Any], ...]
    dataset_snapshots: tuple[Mapping[str, Any], ...]
    required_comparison_set: tuple[str, ...]
    research_gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _EventProjection:
    """Everything the append-only event log answers, folded in a single pass.

    The log only grows, so each question asked of it costs a full scan. Reading it once
    per public operation keeps a catalog query linear in the log rather than linear per
    question, without caching across calls -- a parallel agent may have appended since.
    """

    committed_record_ids: frozenset[str]
    committed_attempt_ids: frozenset[str]
    started_attempts: Mapping[str, Mapping[str, Any]]
    latest_decisions: Mapping[str, Mapping[str, Any]]

    @classmethod
    def build(cls, events: Sequence[Mapping[str, Any]]) -> _EventProjection:
        records: set[str] = set()
        attempts: set[str] = set()
        started: dict[str, Mapping[str, Any]] = {}
        decisions: dict[str, Mapping[str, Any]] = {}
        for event in events:
            payload = event.get("payload", {})
            event_type = event.get("event_type")
            if event_type == "attempt_started":
                started[str(payload["attempt_id"])] = payload
            elif event_type == "publish_commit":
                records.add(str(payload["record_id"]))
                attempts.add(str(payload["attempt_id"]))
            elif event_type == "research_decision":
                target_id = str(payload["target_id"])
                if int(payload["version"]) >= int(decisions.get(target_id, {}).get("version", -1)):
                    decisions[target_id] = payload
        return cls(frozenset(records), frozenset(attempts), started, decisions)


class ResearchCatalog:
    """File authority with append-only events and a rebuildable DuckDB projection."""

    def __init__(self, state: Path) -> None:
        self.state = state
        self.events = state / "events" / "events.jsonl"
        self.blobs = state / "blobs"
        self.records = state / "records"
        self.staging = state / "staging"
        self.prepared = state / "prepared"
        self.frozen = state / "frozen"
        self.proposals = state / "proposals"
        self.locks = state / "locks"
        self.projection = state / "catalog.duckdb"
        for path in (
            self.events.parent,
            self.blobs,
            self.records,
            self.staging,
            self.prepared,
            self.frozen,
            self.proposals,
            self.locks,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_project(cls, project: Project) -> ResearchCatalog:
        return cls(project.paths.research)

    def freeze_run(
        self,
        *,
        session_id: str,
        config_files: Mapping[str, str | Path],
        dataset_snapshots: Mapping[str, str],
        component_versions: Mapping[str, str],
        seed: int,
    ) -> FrozenRunBundle:
        configs: dict[str, Mapping[str, str]] = {}
        for name, raw_path in sorted(config_files.items()):
            path = Path(raw_path).resolve()
            payload = path.read_bytes()
            configs[name] = {
                "source_path": str(path),
                "sha256": digest_bytes(payload),
                "content": payload.decode("utf-8"),
            }
        body = {
            "schema_version": 1,
            "session_id": session_id,
            "configs": configs,
            "dataset_snapshots": dict(dataset_snapshots),
            "component_versions": dict(component_versions),
            "seed": seed,
        }
        bundle_id = digest_document(body)
        path = self.frozen / f"{bundle_id}.json"
        _write_once(path, canonical_bytes({**body, "bundle_id": bundle_id}))
        return FrozenRunBundle(
            bundle_id,
            session_id,
            path,
            {name: value["sha256"] for name, value in configs.items()},
            dict(dataset_snapshots),
            dict(component_versions),
            seed,
        )

    def load_frozen_run(self, bundle_id: str) -> Mapping[str, Any]:
        path = self.frozen / f"{bundle_id}.json"
        if not path.exists():
            raise QlibxError(
                "QLIBX_NOT_FOUND_FROZEN_RUN",
                f"Unknown frozen run bundle: {bundle_id}",
                action="Freeze the run before loading it, or choose an existing bundle ID.",
                context={"bundle_id": bundle_id},
            )
        body = json.loads(path.read_text(encoding="utf-8"))
        expected = body.pop("bundle_id")
        if expected != bundle_id or digest_document(body) != bundle_id:
            raise QlibxError(
                "QLIBX_CORRUPT_FROZEN_RUN",
                f"Frozen run bundle {bundle_id} does not match its recorded digest",
                action="Do not reuse this bundle; freeze the run again from its inputs.",
                context={"bundle_id": bundle_id, "path": str(path)},
            )
        return {**body, "bundle_id": bundle_id}

    def create_proposal(
        self,
        proposal: ResearchProposal,
        *,
        session_id: str,
        agent_id: str,
    ) -> ProposalRecord:
        if proposal.search_limit < 1:
            raise QlibxError(
                "QLIBX_INVALID_LIMIT",
                f"Proposal search_limit must be positive, got {proposal.search_limit}",
                action="Declare how many trials the proposal may spend before it stops.",
                context={"search_limit": proposal.search_limit},
            )
        body = {
            "schema_version": 1,
            "session_id": session_id,
            "agent_id": agent_id,
            "proposal": asdict(proposal),
        }
        proposal_id = digest_document(body)
        payload = {**body, "proposal_id": proposal_id, "version": 0, "status": "active"}
        _write_once(self.proposals / f"{proposal_id}.json", canonical_bytes(payload))
        self._append_event("proposal_created", payload)
        return ProposalRecord(proposal_id, session_id, agent_id, proposal, 0, "active")

    def record_decision(
        self,
        target_id: str,
        *,
        decision: DecisionKind,
        evidence_run_ids: Sequence[str],
        criteria: Mapping[str, Any],
        reviewer: str,
        rationale: str,
        expected_version: int,
    ) -> ResearchDecision:
        allowed = ("promote", "reject", "retain_diagnostic", "supersede")
        if decision not in allowed:
            raise unknown_name(
                "QLIBX_INVALID_RESEARCH_DECISION_KIND", "research decision", decision, allowed
            )
        with self._lock(f"decision-{target_id}"):
            current = self._decision_version(target_id)
            if current != expected_version:
                raise QlibxError(
                    "QLIBX_CONFLICT_STALE_DECISION",
                    f"Decision for {target_id} expected version {expected_version}, "
                    f"but the current version is {current}",
                    action=(
                        "Re-read the latest decision for this target and retry with its "
                        "current version; another agent decided first."
                    ),
                    context={
                        "target_id": target_id,
                        "expected_version": expected_version,
                        "current_version": current,
                    },
                )
            result = ResearchDecision(
                target_id,
                current + 1,
                decision,
                tuple(evidence_run_ids),
                dict(criteria),
                reviewer,
                rationale,
            )
            self._append_event("research_decision", asdict(result))
        return result

    def begin(
        self,
        *,
        session_id: str,
        invocation: Mapping[str, Any],
        kind: str,
        result_key: str | None = None,
    ) -> StagedAttempt:
        invocation_snapshot = json.loads(canonical_bytes(invocation))
        invocation_id = digest_document(invocation_snapshot)
        key = result_key or digest_document({"kind": kind, "invocation": invocation_id})
        attempt_id = f"attempt-{uuid.uuid4().hex}"
        directory = self.staging / session_id / attempt_id
        directory.mkdir(parents=True, exist_ok=False)
        descriptor = {
            "session_id": session_id,
            "invocation_id": invocation_id,
            "attempt_id": attempt_id,
            "result_key": key,
            "kind": kind,
            "invocation": invocation_snapshot,
        }
        (directory / "attempt.json").write_bytes(canonical_bytes(descriptor))
        self._append_event("attempt_started", descriptor)
        return StagedAttempt(session_id, invocation_id, attempt_id, key, kind, directory)

    def stage_frame(self, attempt: StagedAttempt, name: str, frame: pd.DataFrame) -> Path:
        validate_name(name)
        path = attempt.directory / f"{name}.parquet"
        frame.to_parquet(path, index=True)
        return path

    def stage_json(self, attempt: StagedAttempt, name: str, value: Any) -> Path:
        validate_name(name)
        path = attempt.directory / f"{name}.json"
        path.write_bytes(canonical_bytes(value))
        return path

    def prepare_publication(
        self,
        attempt: StagedAttempt,
        *,
        status: RunStatus,
        metadata: Mapping[str, Any],
        parents: tuple[str, ...] = (),
    ) -> PublicationPlan:
        allowed = ("successful", "failed", "invalid", "abandoned")
        if status not in allowed:
            raise unknown_name("QLIBX_INVALID_RUN_STATUS", "run status", status, allowed)
        staged_files = tuple(
            sorted(
                path
                for path in attempt.directory.iterdir()
                if path.name != "attempt.json" and path.is_file()
            )
        )
        if status == "successful" and not staged_files:
            raise QlibxError(
                "QLIBX_MISSING_PUBLICATION_ARTIFACTS",
                "A successful publication must stage at least one artifact",
                action=(
                    "Stage the result with stage_frame/stage_json, or publish with a status "
                    "that reflects what actually happened."
                ),
                context={"attempt_id": attempt.attempt_id, "status": status},
            )
        artifacts = tuple(self._describe(path) for path in staged_files)
        manifest = {
            "schema_version": 1,
            "record_id": digest_document({"result_key": attempt.result_key}),
            "result_key": attempt.result_key,
            "invocation_id": attempt.invocation_id,
            "attempt_id": attempt.attempt_id,
            "session_id": attempt.session_id,
            "kind": attempt.kind,
            "status": status,
            "parents": list(parents),
            "metadata": json.loads(canonical_bytes(metadata)),
            "artifacts": [asdict(artifact) for artifact in artifacts],
        }
        body = {
            "manifest": manifest,
            "staged_files": [str(path.resolve()) for path in staged_files],
        }
        plan_path = self.prepared / f"{attempt.attempt_id}.json"
        _write_once(plan_path, canonical_bytes(body))
        self._append_event(
            "publish_intent",
            {"record_id": manifest["record_id"], "attempt_id": attempt.attempt_id},
        )
        return PublicationPlan(plan_path, manifest, staged_files, artifacts)

    def install_publication(self, plan: PublicationPlan) -> None:
        for path, artifact in zip(plan.staged_files, plan.artifacts, strict=True):
            if not path.exists() or digest_bytes(path.read_bytes()) != artifact.blob_digest:
                raise QlibxError(
                    "QLIBX_CONFLICT_STAGED_ARTIFACT",
                    f"Staged artifact changed after the publication was prepared: {path.name}",
                    action="Prepare the publication again from the current staged files.",
                    context={"path": str(path), "expected_digest": artifact.blob_digest},
                )
            destination = self.blobs / artifact.blob_digest
            if destination.exists():
                if digest_bytes(destination.read_bytes()) != artifact.blob_digest:
                    raise QlibxError(
                        "QLIBX_CORRUPT_RESEARCH_BLOB",
                        f"Stored blob does not match its content address: {artifact.blob_digest}",
                        action=(
                            "Do not overwrite it; investigate the blob store before "
                            "republishing this record."
                        ),
                        context={"blob_digest": artifact.blob_digest, "path": str(destination)},
                    )
            else:
                _write_once(destination, path.read_bytes())
        record_id = str(plan.manifest["record_id"])
        record_path = self.records / f"{record_id}.json"
        if record_path.exists():
            if not self._same_result(record_path.read_bytes(), plan.manifest):
                raise QlibxError(
                    "QLIBX_CONFLICT_RESULT_IDENTITY",
                    f"Different content already claims result key {plan.manifest['result_key']!r}",
                    action=(
                        "Another agent published a different result under this identity. "
                        "Compare both records and publish under a distinct result key."
                    ),
                    context={
                        "record_id": record_id,
                        "result_key": plan.manifest["result_key"],
                        "record_path": str(record_path),
                    },
                )
        else:
            _write_once(record_path, canonical_bytes(plan.manifest))

    def commit_publication(
        self, plan: PublicationPlan, *, recovered: bool = False
    ) -> PublishedResult:
        record_id = str(plan.manifest["record_id"])
        if not self._installed_manifest_valid(plan.manifest):
            raise QlibxError(
                "QLIBX_CONFLICT_PUBLICATION_INCOMPLETE",
                f"Publication {record_id} is not completely installed",
                action=(
                    "Run install_publication (or recover_publications) before committing; "
                    "a directory existing is not evidence of a complete result."
                ),
                context={"record_id": record_id, "attempt_id": plan.manifest["attempt_id"]},
            )
        already_committed = record_id in self._committed_record_ids()
        if not already_committed:
            self._append_event(
                "publish_commit",
                {
                    "record_id": record_id,
                    "attempt_id": plan.manifest["attempt_id"],
                    "recovered": recovered,
                },
            )
        elif not recovered:
            self._append_event("cache_hit", {"record_id": record_id})
        return PublishedResult(
            str(plan.manifest["result_key"]),
            record_id,
            str(plan.manifest["attempt_id"]),
            plan.manifest["status"],
            already_committed,
            plan.artifacts,
        )

    def publish(
        self,
        attempt: StagedAttempt,
        *,
        status: RunStatus,
        metadata: Mapping[str, Any],
        parents: tuple[str, ...] = (),
    ) -> PublishedResult:
        plan = self.prepare_publication(
            attempt,
            status=status,
            metadata=metadata,
            parents=parents,
        )
        self.install_publication(plan)
        return self.commit_publication(plan)

    def recover_publications(self) -> tuple[Mapping[str, Any], ...]:
        outcomes: list[Mapping[str, Any]] = []
        # Local mutable copy: each recovery commits one more record within this loop.
        committed = set(self._committed_record_ids())
        for path in sorted(self.prepared.glob("*.json")):
            plan = self._load_publication_plan(path)
            record_id = str(plan.manifest["record_id"])
            if record_id in committed:
                outcomes.append({"record_id": record_id, "status": "already_committed"})
                continue
            try:
                self.install_publication(plan)
                self.commit_publication(plan, recovered=True)
            except ValueError as error:
                outcomes.append(
                    {"record_id": record_id, "status": "incomplete", "error": str(error)}
                )
            else:
                outcomes.append({"record_id": record_id, "status": "recovered"})
                committed.add(record_id)
        return tuple(outcomes)

    def query_context(
        self,
        *,
        candidate: Mapping[str, Any] | None = None,
        required_comparison_set: Sequence[str] = (),
        research_gaps: Sequence[str] = (),
        limit: int = 10,
    ) -> ResearchContext:
        projection = self._project()
        results = self.list_results(projection=projection)
        proposals = tuple(
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.proposals.glob("*.json"))
        )
        decisions = projection.latest_decisions
        active = tuple(
            item
            for item in proposals
            if decisions.get(item["proposal_id"], {}).get("decision")
            not in {"promote", "reject", "supersede"}
        )
        searched = tuple(item["proposal"]["parameter_range"] for item in proposals)
        nearest = self._nearest(candidate or {}, results, limit=limit)
        snapshots = tuple(
            {
                "bundle_id": path.stem,
                "dataset_snapshots": json.loads(path.read_text(encoding="utf-8"))[
                    "dataset_snapshots"
                ],
            }
            for path in sorted(self.frozen.glob("*.json"))
        )
        return ResearchContext(
            prior_results=results[-limit:],
            incomplete_attempts=self.list_incomplete_attempts(projection=projection),
            searched_parameter_ranges=searched[-limit:],
            active_proposals=active[-limit:],
            nearest_neighbors=nearest,
            dataset_snapshots=snapshots[-limit:],
            required_comparison_set=tuple(required_comparison_set),
            research_gaps=tuple(research_gaps),
        )

    def list_incomplete_attempts(
        self, *, projection: _EventProjection | None = None
    ) -> tuple[Mapping[str, Any], ...]:
        resolved = self._project() if projection is None else projection
        return tuple(
            {**value, "status": "incomplete"}
            for key, value in sorted(resolved.started_attempts.items())
            if key not in resolved.committed_attempt_ids
        )

    def rebuild_projection(self) -> Path:
        rows = list(self._verified_records())
        with duckdb.connect(str(self.projection)) as connection:
            connection.execute("drop table if exists records")
            connection.execute(
                """create table records(
                record_id varchar primary key, result_key varchar, invocation_id varchar,
                attempt_id varchar, session_id varchar, kind varchar, status varchar,
                parents_json varchar, metadata_json varchar, manifest_path varchar
                )"""
            )
            for row in rows:
                connection.execute(
                    "insert into records values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        row["record_id"],
                        row["result_key"],
                        row["invocation_id"],
                        row["attempt_id"],
                        row["session_id"],
                        row["kind"],
                        row["status"],
                        json.dumps(row["parents"]),
                        json.dumps(row["metadata"]),
                        str(self.records / f"{row['record_id']}.json"),
                    ],
                )
        return self.projection

    def list_results(
        self,
        *,
        status: RunStatus | None = None,
        projection: _EventProjection | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        records = tuple(self._verified_records(projection=projection))
        if status is None:
            return records
        return tuple(record for record in records if record["status"] == status)

    def _verified_records(
        self, *, projection: _EventProjection | None = None
    ) -> Iterator[Mapping[str, Any]]:
        """Yield each committed record whose installed artifacts still verify."""
        committed = (self._project() if projection is None else projection).committed_record_ids
        for path in sorted(self.records.glob("*.json")):
            if path.stem not in committed:
                continue
            manifest = _read_manifest(path)
            if manifest is not None and self._installed_manifest_valid(manifest):
                yield manifest

    def load_artifact(self, record_id: str, name: str) -> pd.DataFrame | Any:
        """Load one hash-verified artifact from a committed complete record."""
        if record_id not in self._committed_record_ids():
            raise QlibxError(
                "QLIBX_CONFLICT_RECORD_NOT_COMMITTED",
                f"Record {record_id} has no commit event",
                action=(
                    "Only committed records are readable. Run recover_publications if a "
                    "previous run was interrupted."
                ),
                context={"record_id": record_id},
            )
        manifest = _read_manifest(self.records / f"{record_id}.json")
        if manifest is None or not self._installed_manifest_valid(manifest):
            raise QlibxError(
                "QLIBX_CORRUPT_RESEARCH_RECORD",
                f"Record {record_id} has incomplete or hash-mismatched artifacts",
                action="Do not treat this record as evidence; republish the result.",
                context={"record_id": record_id},
            )
        matches = [artifact for artifact in manifest["artifacts"] if artifact["name"] == name]
        if len(matches) != 1:
            raise unknown_name(
                "QLIBX_NOT_FOUND_RESEARCH_ARTIFACT",
                f"artifact of record {record_id}",
                name,
                (str(item["name"]) for item in manifest["artifacts"]),
            )
        artifact = matches[0]
        media_type = str(artifact["media_type"])
        # Records on disk carry a media type, so it is mapped here rather than stored as a
        # PayloadFormat -- an already-published record must stay readable.
        payload_format = _MEDIA_TYPE_FORMATS.get(media_type)
        if payload_format is None:
            raise unknown_name(
                "QLIBX_UNSUPPORTED_MEDIA_TYPE",
                "artifact media type",
                media_type,
                _MEDIA_TYPE_FORMATS,
            )
        return read_payload(self.blobs / artifact["blob_digest"], payload_format)

    def _load_publication_plan(self, path: Path) -> PublicationPlan:
        body = json.loads(path.read_text(encoding="utf-8"))
        manifest = body["manifest"]
        files = tuple(Path(item) for item in body["staged_files"])
        artifacts = tuple(ArtifactRecord(**item) for item in manifest["artifacts"])
        return PublicationPlan(path, manifest, files, artifacts)

    def _installed_manifest_valid(self, manifest: Mapping[str, Any]) -> bool:
        record_path = self.records / f"{manifest['record_id']}.json"
        if not record_path.exists():
            return False
        try:
            stored = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if not self._same_result(canonical_bytes(stored), manifest):
            return False
        for artifact in manifest["artifacts"]:
            path = self.blobs / artifact["blob_digest"]
            if not path.exists() or digest_bytes(path.read_bytes()) != artifact["blob_digest"]:
                return False
        return True

    def _describe(self, path: Path) -> ArtifactRecord:
        payload = path.read_bytes()
        media_type = "application/x-parquet" if path.suffix == ".parquet" else "application/json"
        return ArtifactRecord(path.stem, media_type, digest_bytes(payload), len(payload))

    def _append_event(self, event_type: str, payload: Mapping[str, Any]) -> None:
        event = {
            "event_id": f"event-{uuid.uuid4().hex}",
            "event_type": event_type,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        line = canonical_bytes(event) + b"\n"
        with self._lock("events"):
            descriptor = os.open(self.events, os.O_CREAT | os.O_APPEND | os.O_WRONLY)
            try:
                os.write(descriptor, line)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _read_events(self) -> tuple[Mapping[str, Any], ...]:
        """Read the append-only log, refusing to interpret a damaged one.

        Skipping an unreadable line would make a committed record silently vanish from
        every projection -- the log claims to be the durable authority, so a hole in it
        has to stop the read rather than quietly shrink the answer.
        """
        if not self.events.exists():
            return ()
        events: list[Mapping[str, Any]] = []
        for number, line in enumerate(self.events.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise QlibxError(
                    "QLIBX_CORRUPT_EVENT_LOG",
                    f"Research event log line {number} is not readable JSON",
                    action=(
                        "Inspect the tail of events/events.jsonl; a crash mid-append can leave "
                        "a partial final line that must be repaired or removed deliberately."
                    ),
                    context={"events": str(self.events), "line_number": number},
                ) from error
        return tuple(events)

    def _project(self) -> _EventProjection:
        return _EventProjection.build(self._read_events())

    def _committed_record_ids(self) -> frozenset[str]:
        return self._project().committed_record_ids

    def _decision_version(self, target_id: str) -> int:
        decision = self._project().latest_decisions.get(target_id)
        return 0 if decision is None else int(decision["version"])

    def _nearest(
        self,
        candidate: Mapping[str, Any],
        results: Sequence[Mapping[str, Any]],
        *,
        limit: int,
    ) -> tuple[Mapping[str, Any], ...]:
        candidate_terms = _semantic_terms(candidate)
        scored: list[Mapping[str, Any]] = []
        for result in results:
            descriptor = result.get("metadata", {}).get("descriptor", {})
            terms = _semantic_terms(descriptor)
            union = candidate_terms | terms
            score = len(candidate_terms & terms) / len(union) if union else 0.0
            scored.append(
                {
                    "record_id": result["record_id"],
                    "result_key": result["result_key"],
                    "score": score,
                    "status": result["status"],
                    "descriptor": descriptor,
                }
            )
        return tuple(
            sorted(scored, key=lambda item: (-float(item["score"]), str(item["record_id"])))[:limit]
        )

    @contextmanager
    def _lock(self, name: str):
        path = self.locks / f"{name}.lock"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR)
        try:
            _ensure_lock_byte(descriptor)
            # Acquire outside the release scope: unlocking a region that was never locked
            # raises OSError on Windows and would mask the original acquisition failure.
            _acquire_file_lock(descriptor, name)
        except BaseException:
            os.close(descriptor)
            raise
        try:
            yield
        finally:
            try:
                _release_file_lock(descriptor)
            finally:
                os.close(descriptor)

    @staticmethod
    def _same_result(existing: bytes, candidate: Mapping[str, Any]) -> bool:
        previous = json.loads(existing)
        stable_fields = (
            "result_key",
            "invocation_id",
            "kind",
            "status",
            "parents",
            "metadata",
            "artifacts",
        )
        return all(previous.get(field) == candidate.get(field) for field in stable_fields)


def _semantic_terms(value: Mapping[str, Any]) -> set[str]:
    output: set[str] = set()
    for key, item in value.items():
        if isinstance(item, Mapping):
            output.update(f"{key}:{term}" for term in _semantic_terms(item))
        elif isinstance(item, (list, tuple, set)):
            output.update(f"{key}:{element}" for element in item)
        else:
            output.add(f"{key}:{item}")
    return output


def _read_manifest(path: Path) -> Mapping[str, Any] | None:
    """Read one stored manifest, treating an unreadable file as absent rather than fatal."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _immutable_conflict(path: Path) -> QlibxError:
    return QlibxError(
        "QLIBX_CONFLICT_IMMUTABLE_CONTENT",
        f"Different content already exists at an immutable path: {path.name}",
        action=(
            "This path is write-once. Publish the differing result under its own identity "
            "instead of overwriting the stored one."
        ),
        context={"path": str(path)},
    )


def _write_once(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise _immutable_conflict(path)
        return
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(payload)
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise _immutable_conflict(path) from None
    finally:
        temporary.unlink(missing_ok=True)


def _ensure_lock_byte(descriptor: int) -> None:
    if os.fstat(descriptor).st_size == 0:
        os.write(descriptor, b"0")
        os.fsync(descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)


def _acquire_file_lock(descriptor: int, name: str) -> None:
    if os.name == "nt":
        import msvcrt

        for _ in range(500):
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.01)
        raise TimeoutError(f"could not acquire catalog lock: {name}")
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX)


def _release_file_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


__all__ = [
    "AlphaDescriptor",
    "ArtifactRecord",
    "FrozenRunBundle",
    "OrthogonalityResult",
    "ProposalRecord",
    "PublicationPlan",
    "PublishedResult",
    "ResearchCatalog",
    "ResearchContext",
    "ResearchDecision",
    "ResearchProposal",
    "StagedAttempt",
    "compare_alpha",
]
