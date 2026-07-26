from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
import pandas as pd

from qlib_extended.research.artifacts import validate_run_directory
from qlib_extended.research.manifest import (
    RESEARCH_TRACKS,
    RUN_KINDS,
    RUN_STATUSES,
)


class AlphaPoolCatalog:
    """Immutable run manifest를 index하는 lean DuckDB catalog입니다."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            _create_schema(connection)

    def register_manifest(self, manifest_path: Path) -> str:
        return self.register_manifests([manifest_path])[0]

    def register_manifests(self, manifest_paths: list[Path]) -> list[str]:
        """완료 manifest 묶음을 한 transaction으로 lineage 순서에 맞춰 등록합니다."""

        validated: dict[str, tuple[Path, dict[str, Any]]] = {}
        for manifest_path in manifest_paths:
            run_dir = manifest_path.resolve().parent
            manifest = validate_run_directory(run_dir)
            run = _validate_manifest(manifest)
            run_id = run["run_id"]
            if run_id in validated:
                raise ValueError(f"Duplicate run manifest in registration batch: {run_id}")
            validated[run_id] = (run_dir, manifest)

        registered: list[str] = []
        with self._connect() as connection:
            connection.execute("begin transaction")
            try:
                existing_ids = {
                    row[0] for row in connection.execute("select run_id from runs").fetchall()
                }
                pending = dict(validated)
                while pending:
                    progressed = False
                    for run_id, (run_dir, manifest) in list(pending.items()):
                        required = {
                            item["member_run_id"] for item in manifest["members"]
                        }
                        if not required.issubset(existing_ids):
                            continue
                        _register_one(connection, self.path, run_dir, manifest)
                        existing_ids.add(run_id)
                        registered.append(run_id)
                        pending.pop(run_id)
                        progressed = True
                    if not progressed:
                        unresolved = {
                            run_id: [
                                item["member_run_id"]
                                for item in manifest["members"]
                                if item["member_run_id"] not in existing_ids
                            ]
                            for run_id, (_, manifest) in pending.items()
                        }
                        raise ValueError(
                            f"Unresolved or cyclic ensemble lineage: {unresolved}"
                        )
                connection.execute("commit")
            except Exception:
                connection.execute("rollback")
                raise
        return registered

    def runs(self) -> pd.DataFrame:
        with self._connect(read_only=True) as connection:
            return connection.execute("select * from runs order by created_at, run_id").fetchdf()

    def metrics(self) -> pd.DataFrame:
        with self._connect(read_only=True) as connection:
            return connection.execute(
                "select * from metrics order by run_id, segment, metric"
            ).fetchdf()

    def members(self) -> pd.DataFrame:
        with self._connect(read_only=True) as connection:
            return connection.execute(
                "select * from members order by ensemble_run_id, member_run_id"
            ).fetchdf()

    def _connect(self, *, read_only: bool = False):
        return duckdb.connect(str(self.path), read_only=read_only)


def rebuild_catalog(catalog_path: Path, artifact_root: Path) -> AlphaPoolCatalog:
    """모든 immutable manifest를 topological order로 새 catalog에 등록합니다."""

    target = catalog_path.resolve()
    root = artifact_root.resolve()
    manifests = sorted(
        path
        for path in root.glob("*/manifest.json")
        if path.parent.name != ".staging"
    )
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    catalog = AlphaPoolCatalog(temporary)
    try:
        catalog.register_manifests(manifests)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return AlphaPoolCatalog(target)


def _create_schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        create table if not exists runs (
            run_id varchar primary key,
            alpha_key varchar not null,
            family varchar not null,
            run_kind varchar not null,
            research_track varchar not null,
            order_calendar_key varchar not null,
            rebalance_days integer not null,
            status varchar not null,
            config_hash varchar not null,
            data_fingerprint varchar not null,
            artifact_dir varchar not null,
            created_at timestamp not null
        );
        create table if not exists metrics (
            run_id varchar not null,
            segment varchar not null,
            metric varchar not null,
            value double not null,
            primary key (run_id, segment, metric)
        );
        create table if not exists members (
            ensemble_run_id varchar not null,
            member_run_id varchar not null,
            weight double not null,
            primary key (ensemble_run_id, member_run_id)
        );
        """
    )


def _register_one(
    connection: duckdb.DuckDBPyConnection,
    catalog_path: Path,
    run_dir: Path,
    manifest: dict[str, Any],
) -> None:
    run = manifest["run"]
    relative_dir = os.path.relpath(run_dir, catalog_path.parent).replace("\\", "/")
    record = (
        run["run_id"],
        run["alpha_key"],
        run["family"],
        run["run_kind"],
        run["research_track"],
        run["order_calendar_key"],
        int(run["rebalance_days"]),
        run["status"],
        run["config_hash"],
        run["data_fingerprint"],
        relative_dir,
        run["created_at"],
    )
    existing = connection.execute(
        "select * from runs where run_id = ?", [run["run_id"]]
    ).fetchone()
    if existing is not None:
        if tuple(str(value) for value in existing[:-1]) != tuple(
            str(value) for value in record[:-1]
        ):
            raise ValueError(
                f"Run ID collision with different catalog record: {run['run_id']}"
            )
        return
    for member in manifest["members"]:
        if member["member_run_id"] == run["run_id"]:
            raise ValueError("Ensemble cannot contain itself.")
    connection.execute(
        "insert into runs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", record
    )
    if manifest["metrics"]:
        connection.executemany(
            "insert into metrics values (?, ?, ?, ?)",
            [
                (
                    run["run_id"],
                    item["segment"],
                    item["metric"],
                    float(item["value"]),
                )
                for item in manifest["metrics"]
            ],
        )
    if manifest["members"]:
        connection.executemany(
            "insert into members values (?, ?, ?)",
            [
                (
                    run["run_id"],
                    item["member_run_id"],
                    float(item["weight"]),
                )
                for item in manifest["members"]
            ],
        )


def _validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    run = manifest.get("run")
    metrics = manifest.get("metrics")
    members = manifest.get("members")
    if not isinstance(run, dict) or not isinstance(metrics, list) or not isinstance(members, list):
        raise ValueError("Manifest must contain run mapping and metrics/members lists.")
    if run.get("run_kind") not in RUN_KINDS:
        raise ValueError("Manifest has invalid run_kind.")
    if run.get("research_track") not in RESEARCH_TRACKS:
        raise ValueError("Manifest has invalid research_track.")
    if run.get("status") not in RUN_STATUSES:
        raise ValueError("Manifest has invalid status.")
    if run["research_track"] == "trusted" and int(run["rebalance_days"]) > 63:
        raise ValueError("trusted run rebalance_days must not exceed 63.")
    metric_keys = [(item.get("segment"), item.get("metric")) for item in metrics]
    if len(metric_keys) != len(set(metric_keys)):
        raise ValueError("Manifest contains duplicate metrics.")
    member_keys = [item.get("member_run_id") for item in members]
    if len(member_keys) != len(set(member_keys)):
        raise ValueError("Manifest contains duplicate members.")
    return run
