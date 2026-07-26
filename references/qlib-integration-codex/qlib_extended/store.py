from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import duckdb
import pandas as pd

from .hashing import file_hash
from .models import RunRecord


@dataclass(frozen=True)
class ParentLink:
    run_id: str
    role: str
    weight: float | None = None


class RunCatalog:
    """DuckDB run index with immutable, hash-verified Parquet artifacts."""

    def __init__(self, catalog_path: Path, artifact_root: Path) -> None:
        self.catalog_path = catalog_path.resolve()
        self.artifact_root = artifact_root.resolve()

    @classmethod
    def initialize(cls, catalog_path: Path, artifact_root: Path) -> RunCatalog:
        catalog_path = catalog_path.resolve()
        artifact_root = artifact_root.resolve()
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_root.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(catalog_path)) as connection:
            _create_schema(connection)
            rows = connection.execute(
                "SELECT value FROM settings WHERE key = 'artifact_root'"
            ).fetchall()
            if rows and Path(rows[0][0]).resolve() != artifact_root:
                raise ValueError("catalog is already bound to a different artifact root")
            if not rows:
                connection.execute(
                    "INSERT INTO settings VALUES ('artifact_root', ?)",
                    [str(artifact_root)],
                )
        return cls(catalog_path, artifact_root)

    @classmethod
    def open(cls, catalog_path: str | Path) -> RunCatalog:
        path = Path(catalog_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"run catalog does not exist: {path}")
        with duckdb.connect(str(path), read_only=True) as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = 'artifact_root'"
            ).fetchone()
        if row is None:
            raise ValueError("run catalog is missing artifact_root setting")
        return cls(path, Path(row[0]))

    def has_complete(self, run_id: str) -> bool:
        try:
            record = self.get_run(run_id)
        except KeyError:
            return False
        if record.status != "complete":
            return False
        with self._connect(read_only=True) as connection:
            rows = connection.execute(
                "SELECT relative_path, content_hash FROM artifacts WHERE run_id = ?",
                [run_id],
            ).fetchall()
        if not rows:
            return False
        return all(
            (path := self.artifact_root / relative_path).exists()
            and file_hash(path) == content_hash
            for relative_path, content_hash in rows
        )

    def publish(
        self,
        record: RunRecord,
        artifacts: Mapping[str, pd.DataFrame],
        *,
        parents: Iterable[ParentLink] = (),
    ) -> RunRecord:
        if record.status != "complete":
            raise ValueError("only complete immutable runs can be published")
        if self.has_complete(record.run_id):
            existing = self.get_run(record.run_id)
            _validate_same_identity(existing, record)
            return existing
        final_dir = self.artifact_root / record.run_id
        temporary = self.artifact_root / f".tmp-{record.run_id}-{uuid.uuid4().hex}"
        temporary.mkdir(parents=True, exist_ok=False)
        rows: list[tuple[str, str, str, int]] = []
        try:
            for name, frame in artifacts.items():
                _validate_artifact_name(name)
                if not isinstance(frame, pd.DataFrame):
                    raise TypeError(f"artifact {name} must be a pandas DataFrame")
                path = temporary / f"{name}.parquet"
                frame.to_parquet(path)
                relative = Path(record.run_id) / path.name
                rows.append((name, str(relative), file_hash(path), len(frame)))
            if not rows:
                raise ValueError("a complete run must contain at least one artifact")
            if final_dir.exists():
                raise ValueError(f"artifact directory already exists without complete run: {final_dir}")
            os.replace(temporary, final_dir)
            with self._connect() as connection:
                connection.begin()
                try:
                    connection.execute(
                        """
                        INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """,
                        [
                            record.run_id,
                            record.run_kind,
                            record.strategy_id,
                            record.status,
                            record.config_fingerprint,
                            record.dataset_fingerprint,
                            record.strategy_fingerprint,
                            json.dumps(record.metadata, sort_keys=True),
                        ],
                    )
                    connection.executemany(
                        "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?)",
                        [
                            (record.run_id, name, relative, digest, row_count)
                            for name, relative, digest, row_count in rows
                        ],
                    )
                    parent_rows = [
                        (record.run_id, parent.run_id, parent.role, parent.weight)
                        for parent in parents
                    ]
                    if parent_rows:
                        connection.executemany(
                            "INSERT INTO run_parents VALUES (?, ?, ?, ?)",
                            parent_rows,
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            if final_dir.exists() and not self._run_exists(record.run_id):
                shutil.rmtree(final_dir)
            raise
        return self.get_run(record.run_id)

    def get_run(self, run_id: str) -> RunRecord:
        with self._connect(read_only=True) as connection:
            row = connection.execute(
                """
                SELECT run_id, run_kind, strategy_id, status, config_fingerprint,
                       dataset_fingerprint, strategy_fingerprint, metadata_json
                FROM runs WHERE run_id = ?
                """,
                [run_id],
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown run_id: {run_id}")
            parents = connection.execute(
                "SELECT parent_run_id FROM run_parents WHERE run_id = ? ORDER BY parent_run_id",
                [run_id],
            ).fetchall()
        return RunRecord(
            run_id=row[0],
            run_kind=row[1],
            strategy_id=row[2],
            status=row[3],
            config_fingerprint=row[4],
            dataset_fingerprint=row[5],
            strategy_fingerprint=row[6],
            parent_run_ids=tuple(parent[0] for parent in parents),
            metadata=json.loads(row[7]),
        )

    def list_runs(self) -> tuple[RunRecord, ...]:
        with self._connect(read_only=True) as connection:
            run_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT run_id FROM runs ORDER BY run_id"
                ).fetchall()
            ]
        return tuple(self.get_run(run_id) for run_id in run_ids)

    def get_parent_links(self, run_id: str) -> tuple[ParentLink, ...]:
        self.get_run(run_id)
        with self._connect(read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT parent_run_id, role, weight
                FROM run_parents
                WHERE run_id = ?
                ORDER BY role, parent_run_id
                """,
                [run_id],
            ).fetchall()
        return tuple(
            ParentLink(
                run_id=str(parent_run_id),
                role=str(role),
                weight=None if weight is None else float(weight),
            )
            for parent_run_id, role, weight in rows
        )

    def load_alpha(self, run_id: str) -> pd.DataFrame:
        record = self.get_run(run_id)
        if record.run_kind != "alpha":
            raise ValueError(f"run is not an alpha run: {run_id}")
        return self.load_table(run_id, "alpha")

    def load_table(self, run_id: str, name: str) -> pd.DataFrame:
        self.get_run(run_id)
        with self._connect(read_only=True) as connection:
            row = connection.execute(
                """
                SELECT relative_path, content_hash FROM artifacts
                WHERE run_id = ? AND artifact_name = ?
                """,
                [run_id, name],
            ).fetchone()
        if row is None:
            raise KeyError(f"run {run_id} has no artifact named {name}")
        path = self.artifact_root / row[0]
        if not path.exists() or file_hash(path) != row[1]:
            raise ValueError(f"artifact is missing or corrupt: {run_id}/{name}")
        return pd.read_parquet(path)

    def find_backtests(self, alpha_run_id: str) -> tuple[RunRecord, ...]:
        with self._connect(read_only=True) as connection:
            rows = connection.execute(
                """
                SELECT child.run_id
                FROM run_parents AS link
                JOIN runs AS child ON child.run_id = link.run_id
                WHERE link.parent_run_id = ? AND child.run_kind = 'backtest'
                  AND child.status = 'complete'
                ORDER BY child.run_id
                """,
                [alpha_run_id],
            ).fetchall()
        return tuple(self.get_run(row[0]) for row in rows)

    def _run_exists(self, run_id: str) -> bool:
        with self._connect(read_only=True) as connection:
            return (
                connection.execute(
                    "SELECT COUNT(*) FROM runs WHERE run_id = ?", [run_id]
                ).fetchone()[0]
                > 0
            )

    def _connect(self, *, read_only: bool = False):
        return duckdb.connect(str(self.catalog_path), read_only=read_only)


def _create_schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id VARCHAR PRIMARY KEY,
            run_kind VARCHAR NOT NULL,
            strategy_id VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            config_fingerprint VARCHAR NOT NULL,
            dataset_fingerprint VARCHAR NOT NULL,
            strategy_fingerprint VARCHAR NOT NULL,
            metadata_json VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            run_id VARCHAR NOT NULL,
            artifact_name VARCHAR NOT NULL,
            relative_path VARCHAR NOT NULL,
            content_hash VARCHAR NOT NULL,
            row_count BIGINT NOT NULL,
            PRIMARY KEY (run_id, artifact_name)
        );
        CREATE TABLE IF NOT EXISTS run_parents (
            run_id VARCHAR NOT NULL,
            parent_run_id VARCHAR NOT NULL,
            role VARCHAR NOT NULL,
            weight DOUBLE,
            PRIMARY KEY (run_id, parent_run_id, role)
        );
        """
    )


def _validate_artifact_name(name: str) -> None:
    if not name or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in name):
        raise ValueError(f"invalid artifact name: {name}")


def _validate_same_identity(existing: RunRecord, requested: RunRecord) -> None:
    fields = (
        "run_kind",
        "strategy_id",
        "config_fingerprint",
        "dataset_fingerprint",
        "strategy_fingerprint",
    )
    changed = [field for field in fields if getattr(existing, field) != getattr(requested, field)]
    if changed:
        raise ValueError(f"deterministic run_id collision with different identity: {changed}")
