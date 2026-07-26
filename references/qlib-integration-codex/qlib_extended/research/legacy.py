from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd

from qlib_extended.research.artifacts import ImmutableArtifactStore
from qlib_extended.research.manifest import MemberWeight, MetricValue, RunSpec
from qlib_extended.research.pool import rebuild_catalog


METRIC_TOKENS = (
    "return",
    "sharpe",
    "turnover",
    "cost",
    "volatility",
    "information_ratio",
    "drawdown",
    "excess",
    "coverage",
    "count",
    "exposure",
    "tracking_error",
    "wealth",
    "sum_error",
)
SEGMENTS = (
    "development",
    "validation",
    "holdout",
    "preholdout",
    "early",
    "middle",
    "full",
)


@dataclass(frozen=True)
class LegacyImportSummary:
    ledger_files: int
    ledger_rows: int
    selected_manifests: int
    selected_runs: int
    published_runs: int
    catalog_runs: int
    catalog_metrics: int
    catalog_members: int
    source_rows: dict[str, int]


class LegacyResearchImporter:
    """기존 ledger/selected weight를 immutable legacy run으로 변환합니다."""

    def __init__(
        self,
        research_root: Path,
        artifact_root: Path,
        catalog_path: Path,
    ) -> None:
        self.research_root = research_root.resolve()
        self.store = ImmutableArtifactStore(artifact_root)
        self.catalog_path = catalog_path.resolve()

    def import_all(self, *, summary_path: Path | None = None) -> LegacyImportSummary:
        ledger_paths = sorted(self.research_root.rglob("*ledger*.csv"))
        source_rows: dict[str, int] = {}
        published: list[Path] = []
        for ledger_path in ledger_paths:
            frame = pd.read_csv(ledger_path)
            relative = ledger_path.relative_to(self.research_root).as_posix()
            source_rows[relative] = int(len(frame))
            source_hash = _file_hash(ledger_path)
            for row_index, row in frame.iterrows():
                published.append(
                    self._publish_ledger_row(
                        ledger_path,
                        source_hash,
                        int(row_index),
                        row.to_dict(),
                    )
                )

        selected_paths = [
            path
            for path in (
                self.research_root / "price" / "selected_candidates.json",
                self.research_root / "financial" / "selected_candidates.json",
                self.research_root / "consensus" / "selected_candidates.json",
            )
            if path.is_file()
        ]
        selected_runs = 0
        for selected_path in selected_paths:
            run_dirs = self._import_selected_manifest(selected_path)
            selected_runs += len(run_dirs)
            published.extend(run_dirs)

        catalog = rebuild_catalog(self.catalog_path, self.store.root)
        summary = LegacyImportSummary(
            ledger_files=len(ledger_paths),
            ledger_rows=sum(source_rows.values()),
            selected_manifests=len(selected_paths),
            selected_runs=selected_runs,
            published_runs=len({path.name for path in published}),
            catalog_runs=len(catalog.runs()),
            catalog_metrics=len(catalog.metrics()),
            catalog_members=len(catalog.members()),
            source_rows=source_rows,
        )
        if summary.catalog_runs != summary.published_runs:
            raise RuntimeError(
                "Legacy import catalog/run-directory count mismatch: "
                f"catalog={summary.catalog_runs}, published={summary.published_runs}"
            )
        if summary_path is not None:
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps(asdict(summary), ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        return summary

    def _publish_ledger_row(
        self,
        ledger_path: Path,
        source_hash: str,
        row_index: int,
        raw_row: Mapping[str, Any],
    ) -> Path:
        row = {str(key): _json_safe(value) for key, value in raw_row.items()}
        relative = ledger_path.relative_to(self.research_root).as_posix()
        family = _family_from_path(ledger_path)
        candidate = _candidate_name(row, row_index)
        alpha_key = f"legacy.{_slug(relative.removesuffix('.csv'))}.{_slug(candidate)}"
        status = _status(row)
        rebalance_days = _rebalance_days(row)
        spec = RunSpec(
            alpha_key=alpha_key,
            family=family,
            run_kind=_run_kind(ledger_path),
            research_track="legacy",
            order_calendar_key=_order_calendar(row, relative, rebalance_days),
            rebalance_days=rebalance_days,
            status=status,
            config_hash=_json_hash({"source": relative, "row": row}),
            data_fingerprint=source_hash,
            attempt=row_index,
            created_at="2026-07-24T00:00:00Z",
        )
        return self.store.publish(
            spec,
            metrics=_extract_metrics(row),
            provenance={
                "legacy_import": True,
                "source_path": relative,
                "source_row": row_index,
                "source_record": row,
                "historical_prior_informed": True,
                "holdout_blind": False,
            },
        )

    def _import_selected_manifest(self, path: Path) -> list[Path]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Selected candidate manifest must be a mapping: {path}")
        family = _family_from_path(path)
        source_hash = _file_hash(path)
        name_to_run_id: dict[str, str] = {}
        published: list[Path] = []
        groups = (
            ("candidates", "atomic"),
            ("frequency_ensembles", "family"),
            ("research_comparison_ensembles", "family"),
            ("diagnostic_frequency_ensembles", "family"),
        )
        sequence = 0
        for group_name, run_kind in groups:
            rows = payload.get(group_name, [])
            if rows is None:
                continue
            if not isinstance(rows, list):
                raise ValueError(f"{path}.{group_name} must be a list.")
            for raw in rows:
                if not isinstance(raw, dict):
                    raise ValueError(f"{path}.{group_name} entries must be mappings.")
                row = {str(key): _json_safe(value) for key, value in raw.items()}
                name = str(row.get("name") or row.get("feature") or f"row_{sequence}")
                member_names = row.get("members") or []
                if not isinstance(member_names, list):
                    raise ValueError(f"Selected ensemble members must be a list: {name}")
                missing = [member for member in member_names if member not in name_to_run_id]
                if missing:
                    raise KeyError(f"Selected ensemble {name} references missing members: {missing}")
                rebalance_days = _rebalance_days(row)
                spec = RunSpec(
                    alpha_key=f"legacy.selected.{family}.{_slug(name)}",
                    family=family,
                    run_kind=run_kind,
                    research_track="legacy",
                    order_calendar_key=_order_calendar(
                        row, path.relative_to(self.research_root).as_posix(), rebalance_days
                    ),
                    rebalance_days=rebalance_days,
                    status="complete",
                    config_hash=_json_hash(row),
                    data_fingerprint=source_hash,
                    attempt=sequence,
                    created_at="2026-07-24T00:00:00Z",
                )
                frames: dict[str, pd.DataFrame] = {}
                relative_weight = row.get("path") or row.get("matrix_path")
                if relative_weight:
                    weight_path = (path.parent / str(relative_weight)).resolve()
                    if not weight_path.is_file():
                        raise FileNotFoundError(
                            f"Selected weight artifact is missing: {name} ({weight_path})"
                        )
                    frames["target_weights"] = pd.read_parquet(weight_path)
                members = _member_weights(member_names, name_to_run_id, row)
                run_dir = self.store.publish(
                    spec,
                    metrics=_extract_metrics(_flatten_metrics(row)),
                    members=members,
                    frames=frames,
                    provenance={
                        "legacy_import": True,
                        "selected_manifest": path.relative_to(
                            self.research_root
                        ).as_posix(),
                        "selected_group": group_name,
                        "source_record": row,
                        "historical_prior_informed": True,
                        "holdout_blind": False,
                    },
                )
                name_to_run_id[name] = spec.run_id
                published.append(run_dir)
                sequence += 1
        return published


def _candidate_name(row: Mapping[str, Any], row_index: int) -> str:
    for key in ("trial_id", "name", "candidate", "ensemble", "strategy", "feature"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return f"row_{row_index}"


def _family_from_path(path: Path) -> str:
    lowered = {part.lower() for part in path.parts}
    if "financial" in lowered:
        return "financial"
    if "consensus" in lowered:
        return "consensus"
    if "price" in lowered:
        return "market"
    return "market_consensus"


def _run_kind(path: Path) -> str:
    value = path.as_posix().lower()
    if "/ensemble/" in value or "physical" in path.name.lower():
        return "portfolio"
    if "turnover_control" in path.name.lower():
        return "cohort"
    return "atomic"


def _status(row: Mapping[str, Any]) -> str:
    for key in ("status", "result_status", "solver_status"):
        value = row.get(key)
        if value is None:
            continue
        lowered = str(value).strip().lower()
        if any(token in lowered for token in ("invalid", "infeasible")):
            return "invalid"
        if any(token in lowered for token in ("fail", "error")):
            return "failed"
    for key in ("failure_reason", "error", "exception"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return "failed"
    return "complete"


def _rebalance_days(row: Mapping[str, Any]) -> int:
    for key in (
        "rebalance_days",
        "rebalance_interval",
        "frequency_days",
        "holding_days",
        "decay_days",
    ):
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.lower() == "event":
            return 1
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number >= 1:
            return int(round(number))
    return 1


def _order_calendar(
    row: Mapping[str, Any],
    source: str,
    rebalance_days: int,
) -> str:
    value = row.get("order_calendar_key")
    if value is not None and str(value).strip():
        return str(value)
    return f"legacy_{rebalance_days}d_{sha256(source.encode('utf-8')).hexdigest()[:12]}"


def _extract_metrics(row: Mapping[str, Any]) -> list[MetricValue]:
    metrics: dict[tuple[str, str], float] = {}
    for column, value in row.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        number = float(value)
        if not math.isfinite(number):
            continue
        lowered = column.lower()
        if not any(token in lowered for token in METRIC_TOKENS):
            continue
        segment = "full"
        metric = lowered
        for prefix in SEGMENTS:
            if lowered.startswith(prefix + "_"):
                segment = prefix
                metric = lowered[len(prefix) + 1 :]
                metric = re.sub(r"^[0-9_]+", "", metric)
                break
        metrics[(segment, metric)] = number
    return [
        MetricValue(segment, metric, value)
        for (segment, metric), value in sorted(metrics.items())
    ]


def _flatten_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    flattened = dict(row)
    nested = row.get("metrics")
    if isinstance(nested, dict):
        flattened.update(nested)
    return flattened


def _member_weights(
    names: list[Any],
    name_to_run_id: Mapping[str, str],
    row: Mapping[str, Any],
) -> list[MemberWeight]:
    if not names:
        return []
    raw_weights = row.get("member_weights")
    if isinstance(raw_weights, list) and len(raw_weights) == len(names):
        weights = [float(value) for value in raw_weights]
    else:
        scalar = row.get("member_weight")
        weight = float(scalar) if isinstance(scalar, (int, float)) else 1.0 / len(names)
        weights = [weight] * len(names)
    return [
        MemberWeight(name_to_run_id[str(name)], weight)
        for name, weight in zip(names, weights, strict=True)
    ]


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        value = value.item()
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _json_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "unnamed"
