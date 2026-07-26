from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .result import BackendRunResult


SCHEMA_VERSION = "2"
IDENTITY_COLUMNS = ["run_id"]


class ParquetArtifactStore:
    """Content-addressed Parquet run store with atomic run publication."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_run(self, identity: Any, run: BackendRunResult) -> Mapping[str, Any]:
        run_root = self._run_root(identity)
        result_hash = run.result_hash()
        if run_root.exists():
            stored = pd.read_parquet(run_root / "strategy_runs.parquet")
            _validate_existing_identity(identity, stored.iloc[0])
            existing = str(stored.iloc[0]["result_hash"])
            if existing != result_hash:
                raise ValueError(
                    "run identity already exists with different content hash"
                )
            return self._manifest_view(run_root, result_hash)

        self._validate_registry(identity)
        tables = self._build_tables(identity, run, result_hash)
        run_root.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".writing-{uuid.uuid4().hex}"
        temporary.mkdir(parents=True, exist_ok=False)
        try:
            manifest_rows: list[dict[str, Any]] = []
            table_views: dict[str, dict[str, Any]] = {}
            for table_name, table in tables.items():
                _validate_unique(table_name, table)
                file_path = temporary / f"{table_name}.parquet"
                table.to_parquet(file_path, index=False)
                content_hash = _file_hash(file_path)
                manifest_rows.append(
                    {
                        **_identity_values(identity),
                        "table_name": table_name,
                        "schema_version": SCHEMA_VERSION,
                        "relative_path": file_path.name,
                        "row_count": int(len(table)),
                        "content_hash": content_hash,
                    }
                )
                table_views[table_name] = {
                    "file_path": str(run_root / file_path.name),
                    "row_count": int(len(table)),
                    "content_hash": content_hash,
                }
            manifest = pd.DataFrame(manifest_rows)
            _validate_unique("artifact_manifest", manifest)
            manifest.to_parquet(temporary / "artifact_manifest.parquet", index=False)
            temporary.replace(run_root)
            self._publish_registry(identity)
            return {
                "status": "complete",
                "run_id": _run_id(identity),
                "result_hash": result_hash,
                "files": [view["file_path"] for view in table_views.values()]
                + [str(run_root / "artifact_manifest.parquet")],
                "tables": table_views,
            }
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    def load_table(self, identity: Any, table_name: str) -> pd.DataFrame:
        run_root = self._run_root(identity)
        if not run_root.exists():
            raise ValueError("artifact run is incomplete or missing")
        manifest_path = run_root / "artifact_manifest.parquet"
        if not manifest_path.exists():
            raise ValueError("artifact manifest is missing")
        try:
            manifest = pd.read_parquet(manifest_path)
        except Exception as exc:
            raise ValueError("artifact manifest parquet is corrupt") from exc
        run_id = _run_id(identity)
        if "run_id" not in manifest or not manifest["run_id"].eq(run_id).all():
            raise ValueError("artifact manifest run_id does not match requested run")
        stored_runs = self._load_manifest_table(
            run_root, manifest, "strategy_runs", run_id
        )
        if len(stored_runs) != 1:
            raise ValueError("strategy_runs must contain exactly one run identity")
        _validate_existing_identity(identity, stored_runs.iloc[0])
        if table_name == "artifact_manifest":
            return manifest
        if table_name == "strategy_runs":
            return stored_runs
        return self._load_manifest_table(run_root, manifest, table_name, run_id)

    def _load_manifest_table(
        self,
        run_root: Path,
        manifest: pd.DataFrame,
        table_name: str,
        run_id: str,
    ) -> pd.DataFrame:
        match = manifest.loc[manifest["table_name"].eq(table_name)]
        if len(match) != 1:
            raise ValueError(f"manifest does not contain exactly one table: {table_name}")
        row = match.iloc[0]
        file_path = run_root / str(row["relative_path"])
        if not file_path.exists() or _file_hash(file_path) != str(row["content_hash"]):
            raise ValueError(f"artifact hash mismatch or corrupt parquet: {table_name}")
        try:
            table = pd.read_parquet(file_path)
        except Exception as exc:
            raise ValueError(f"artifact parquet is corrupt: {table_name}") from exc
        if len(table) != int(row["row_count"]):
            raise ValueError(f"artifact manifest row count mismatch: {table_name}")
        if table_name != "strategy_registry" and (
            "run_id" not in table or not table["run_id"].eq(run_id).all()
        ):
            raise ValueError(f"artifact table run_id mismatch: {table_name}")
        _validate_unique(table_name, table)
        return table

    def load_reporting_bundle(self, identity: Any) -> Mapping[str, pd.DataFrame]:
        names = (
            "signals",
            "portfolio_targets",
            "orders",
            "fills",
            "positions",
            "account_daily",
        )
        return {name: self.load_table(identity, name) for name in names}

    def load_ensemble_input(self, identity: Any, artifact_name: str) -> pd.DataFrame:
        if artifact_name.startswith("signals/"):
            table = self.load_table(identity, "signals")
            if identity.reuse_scope not in {"portable_signal", "portable_target"}:
                raise ValueError(
                    f"reuse scope {identity.reuse_scope} is not portable for signals"
                )
            signal_name = artifact_name.split("/", 1)[1]
            return table.loc[table["signal_name"].eq(signal_name)].copy()
        if artifact_name == "portfolio_targets":
            table = self.load_table(identity, "portfolio_targets")
            if identity.reuse_scope != "portable_target":
                raise ValueError(
                    f"reuse scope {identity.reuse_scope} does not permit portable targets"
                )
            return table
        raise ValueError(f"unsupported reusable artifact: {artifact_name}")

    def _run_root(self, identity: Any) -> Path:
        digest = hashlib.sha256(_run_id(identity).encode("utf-8")).hexdigest()[:24]
        return self.root / "runs" / digest

    def _registry_path(self, strategy_id: str) -> Path:
        digest = hashlib.sha256(strategy_id.encode("utf-8")).hexdigest()[:24]
        return self.root / "strategy_registry" / f"{digest}.parquet"

    def _validate_registry(self, identity: Any) -> None:
        path = self._registry_path(str(identity.strategy_id))
        if not path.exists():
            return
        row = pd.read_parquet(path).iloc[0]
        if str(row["definition_hash"]) != str(identity.definition_hash):
            raise ValueError("strategy identity is registered with a different definition")

    def _publish_registry(self, identity: Any) -> None:
        path = self._registry_path(str(identity.strategy_id))
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp.parquet")
        registry = self._strategy_registry(identity)
        registry.to_parquet(temporary, index=False)
        try:
            os.replace(temporary, path)
        except FileExistsError:
            temporary.unlink(missing_ok=True)
            self._validate_registry(identity)

    def _manifest_view(self, run_root: Path, result_hash: str) -> Mapping[str, Any]:
        manifest = pd.read_parquet(run_root / "artifact_manifest.parquet")
        tables = {
            str(row.table_name): {
                "file_path": str(run_root / str(row.relative_path)),
                "row_count": int(row.row_count),
                "content_hash": str(row.content_hash),
            }
            for row in manifest.itertuples(index=False)
        }
        return {
            "status": "complete",
            "run_id": str(manifest.iloc[0]["run_id"]),
            "result_hash": result_hash,
            "files": [view["file_path"] for view in tables.values()]
            + [str(run_root / "artifact_manifest.parquet")],
            "tables": tables,
        }

    def _strategy_registry(self, identity: Any) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "strategy_id": identity.strategy_id,
                    "strategy_name": identity.strategy_name,
                    "definition_hash": identity.definition_hash,
                    "code_version": identity.code_version,
                    "created_at": pd.Timestamp.now(tz="UTC"),
                }
            ]
        )

    def _build_tables(
        self, identity: Any, run: BackendRunResult, result_hash: str
    ) -> dict[str, pd.DataFrame]:
        identity_values = _identity_values(identity)
        registry = self._strategy_registry(identity)
        runs = pd.DataFrame(
            [
                {
                    **identity_values,
                    "status": "complete",
                    "definition_hash": identity.definition_hash,
                    "code_version": identity.code_version,
                    "input_fingerprint": identity.input_fingerprint,
                    "run_fingerprint": getattr(identity, "run_fingerprint", None),
                    "reuse_scope": identity.reuse_scope,
                    "result_hash": result_hash,
                    "schema_version": SCHEMA_VERSION,
                    "created_at": pd.Timestamp.now(tz="UTC"),
                    "completed_at": pd.Timestamp.now(tz="UTC"),
                }
            ]
        )
        targets = (
            run.decision_weights.rename_axis("trade_date")
            .rename_axis("instrument_id", axis=1)
            .stack(future_stack=True)
            .rename("target_weight")
            .reset_index()
        )
        signals = _ensure_columns(
            run.signals(),
            [
                "trade_date",
                "signal_name",
                "instrument_id",
                "signal_value",
                "max_observation_date",
            ],
        )
        orders = _ensure_columns(
            run.orders(),
            [
                "trade_date",
                "order_id",
                "instrument_id",
                "direction",
                "requested_quantity",
                "raw_target_quantity",
                "target_quantity",
                "lot_size",
                "lot_rounding_quantity",
            ],
        )
        fills = _ensure_columns(
            run.fills(),
            [
                "trade_date",
                "fill_id",
                "order_id",
                "instrument_id",
                "filled_quantity",
                "trade_price",
                "trade_value",
                "trade_cost",
                "reason",
                "reason_code",
                "blocked_by",
                "quantity_after_tradability",
                "quantity_after_volume",
                "quantity_after_position",
                "quantity_after_cash",
                "quantity_after_lot",
                "asset_class",
                "execution_policy",
                "effective_cost_rate",
                "short_enabled",
            ],
        )
        positions = _ensure_columns(
            run.positions(),
            [
                "trade_date",
                "instrument_id",
                "held_quantity",
                "market_value",
                "asset_class",
            ],
        )
        account = run.account_daily().rename_axis("trade_date").reset_index()
        research = _ensure_columns(
            run.research_evaluations(),
            [
                "trade_date",
                "candidate_id",
                "score",
                "selected",
                "max_observation_date",
                "diagnostics",
            ],
        )
        tables = {
            "strategy_registry": registry,
            "strategy_runs": runs,
            "signals": _stamp(signals, identity_values),
            "portfolio_targets": _stamp(targets, identity_values),
            "orders": _stamp(orders, identity_values),
            "fills": _stamp(fills, identity_values),
            "positions": _stamp(positions, identity_values),
            "account_daily": _stamp(account, identity_values),
            "research_evaluations": _stamp(research, identity_values),
        }
        for column in ("requested_quantity", "target_quantity", "lot_size"):
            tables["orders"][column] = tables["orders"][column].astype("int64")
        tables["fills"]["filled_quantity"] = tables["fills"][
            "filled_quantity"
        ].astype("int64")
        tables["positions"]["held_quantity"] = tables["positions"][
            "held_quantity"
        ].astype("int64")
        return tables


PRIMARY_KEYS = {
    "strategy_registry": ["strategy_id"],
    "strategy_runs": IDENTITY_COLUMNS,
    "signals": IDENTITY_COLUMNS
    + ["trade_date", "signal_name", "instrument_id"],
    "portfolio_targets": IDENTITY_COLUMNS + ["trade_date", "instrument_id"],
    "orders": IDENTITY_COLUMNS + ["trade_date", "order_id"],
    "fills": IDENTITY_COLUMNS + ["trade_date", "fill_id"],
    "positions": IDENTITY_COLUMNS + ["trade_date", "instrument_id"],
    "account_daily": IDENTITY_COLUMNS + ["trade_date"],
    "research_evaluations": IDENTITY_COLUMNS + ["trade_date", "candidate_id"],
    "artifact_manifest": IDENTITY_COLUMNS + ["table_name"],
}


def _validate_unique(table_name: str, table: pd.DataFrame) -> None:
    key = PRIMARY_KEYS[table_name]
    missing = set(key) - set(table.columns)
    if missing:
        raise ValueError(f"{table_name} is missing primary-key columns: {sorted(missing)}")
    if table.duplicated(key).any():
        raise ValueError(f"{table_name} contains duplicate primary keys")


def _identity_values(identity: Any) -> dict[str, Any]:
    return {
        "run_id": _run_id(identity),
        "strategy_id": str(identity.strategy_id),
        "start_date": pd.Timestamp(identity.start_date),
        "end_date": pd.Timestamp(identity.end_date),
    }


def _run_id(identity: Any) -> str:
    value = str(getattr(identity, "run_id", "")).strip()
    if not value:
        raise ValueError("run_id must be a non-empty immutable execution identity")
    return value


def _validate_existing_identity(identity: Any, stored: pd.Series) -> None:
    expected = {
        **_identity_values(identity),
        "definition_hash": str(identity.definition_hash),
        "code_version": str(identity.code_version),
        "input_fingerprint": str(identity.input_fingerprint),
        "reuse_scope": str(identity.reuse_scope),
        "run_fingerprint": getattr(identity, "run_fingerprint", None),
    }
    for column, value in expected.items():
        stored_value = stored[column]
        if column in {"start_date", "end_date"}:
            matches = pd.Timestamp(stored_value) == pd.Timestamp(value)
        elif pd.isna(stored_value) and value is None:
            matches = True
        else:
            matches = str(stored_value) == str(value)
        if not matches:
            raise ValueError(
                f"run_id is already registered with different provenance: {column}"
            )


def _stamp(table: pd.DataFrame, identity_values: Mapping[str, Any]) -> pd.DataFrame:
    stamped = table.copy()
    for column, value in reversed(list(identity_values.items())):
        stamped.insert(0, column, value)
    return stamped


def _ensure_columns(table: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = table.copy()
    for column in columns:
        if column not in result:
            result[column] = pd.Series(dtype="object")
    return result.loc[:, columns]


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
