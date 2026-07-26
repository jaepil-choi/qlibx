from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


NODE_TYPES = frozenset({"signal", "mask", "active_intent", "physical_target"})
DATASET_ROLES = frozenset(
    {"feature", "label", "universe", "benchmark", "risk", "execution"}
)


@dataclass(frozen=True)
class DatasetDefinition:
    dataset_id: str
    description: str
    schema_version: str


@dataclass(frozen=True)
class DatasetSnapshot:
    dataset_id: str
    snapshot_id: str
    as_of: Any
    content_fingerprint: str


@dataclass(frozen=True)
class ResearchNodeSpec:
    node_id: str
    node_type: str
    operator: str
    config: Mapping[str, Any] = field(default_factory=dict)
    input_types: Mapping[str, Sequence[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ResearchNode:
    node_id: str
    node_type: str
    operator: str
    definition_hash: str
    config: Mapping[str, Any]
    input_types: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class ResearchEdge:
    parent_node_id: str
    child_node_id: str
    input_role: str
    input_order: int


@dataclass(frozen=True)
class NodeDatasetDependency:
    node_id: str
    dataset_id: str
    role: str
    lookback: int
    availability_policy: str


@dataclass(frozen=True)
class StrategyRootSpec:
    strategy_id: str
    root_node_id: str


@dataclass(frozen=True)
class StrategyRoot:
    strategy_id: str
    root_node_id: str
    definition_hash: str


class ResearchGraph:
    """Validated reusable research-node DAG and its logical data dependencies."""

    def __init__(
        self,
        *,
        datasets: Mapping[str, DatasetDefinition],
        nodes: Mapping[str, ResearchNode],
        edges: Sequence[ResearchEdge],
        dependencies: Sequence[NodeDatasetDependency],
        strategy_roots: Mapping[str, StrategyRoot],
        topological_order: Sequence[str],
    ) -> None:
        self._datasets = dict(datasets)
        self._nodes = dict(nodes)
        self._edges = tuple(edges)
        self._dependencies = tuple(dependencies)
        self._strategy_roots = dict(strategy_roots)
        self._topological_order = tuple(topological_order)

    @classmethod
    def compile(
        cls,
        *,
        datasets: Iterable[DatasetDefinition],
        nodes: Iterable[ResearchNodeSpec],
        edges: Iterable[ResearchEdge],
        dependencies: Iterable[NodeDatasetDependency],
        strategy_roots: Iterable[StrategyRootSpec],
    ) -> ResearchGraph:
        dataset_map = _unique_by(datasets, "dataset_id", "dataset")
        node_specs = _unique_by(nodes, "node_id", "research node")
        root_specs = _unique_by(strategy_roots, "strategy_id", "strategy root")
        edge_list = tuple(edges)
        dependency_list = tuple(dependencies)

        _validate_datasets(dataset_map)
        _validate_node_specs(node_specs)
        _validate_edges_exist(node_specs, edge_list)
        topological_order = _topological_sort(node_specs, edge_list)
        _validate_edge_types(node_specs, edge_list)
        _validate_dependencies(node_specs, dataset_map, dependency_list)

        parent_edges = _parent_edges(edge_list)
        dependencies_by_node = _dependencies_by_node(dependency_list)
        compiled: dict[str, ResearchNode] = {}
        for node_id in topological_order:
            spec = node_specs[node_id]
            normalized_contract = {
                role: tuple(sorted(set(allowed_types)))
                for role, allowed_types in sorted(spec.input_types.items())
            }
            definition = {
                "node_type": spec.node_type,
                "operator": spec.operator,
                "config": spec.config,
                "input_types": normalized_contract,
                "parents": [
                    {
                        "definition_hash": compiled[edge.parent_node_id].definition_hash,
                        "input_role": edge.input_role,
                        "input_order": edge.input_order,
                    }
                    for edge in parent_edges.get(node_id, ())
                ],
                "datasets": [
                    {
                        "dataset_id": dependency.dataset_id,
                        "role": dependency.role,
                        "lookback": dependency.lookback,
                        "availability_policy": dependency.availability_policy,
                    }
                    for dependency in dependencies_by_node.get(node_id, ())
                ],
            }
            compiled[node_id] = ResearchNode(
                node_id=node_id,
                node_type=spec.node_type,
                operator=spec.operator,
                definition_hash=_definition_hash(definition),
                config=dict(spec.config),
                input_types=normalized_contract,
            )

        compiled_roots: dict[str, StrategyRoot] = {}
        children = _children(edge_list)
        for strategy_id, root_spec in root_specs.items():
            _require_text(strategy_id, "strategy_id")
            if root_spec.root_node_id not in compiled:
                raise ValueError(
                    f"strategy root references unknown node: {root_spec.root_node_id}"
                )
            root_node = compiled[root_spec.root_node_id]
            if root_node.node_type != "physical_target":
                raise ValueError("strategy root must have node_type physical_target")
            if children.get(root_spec.root_node_id):
                raise ValueError("strategy physical_target root must be an execution sink")
            ancestor_ids = _ancestor_ids(root_spec.root_node_id, parent_edges)
            physical_targets = [
                node_id
                for node_id in ancestor_ids
                if compiled[node_id].node_type == "physical_target"
            ]
            if physical_targets != [root_spec.root_node_id]:
                raise ValueError("strategy must have exactly one physical execution root")
            compiled_roots[strategy_id] = StrategyRoot(
                strategy_id=strategy_id,
                root_node_id=root_spec.root_node_id,
                definition_hash=root_node.definition_hash,
            )

        if not compiled_roots:
            raise ValueError("at least one strategy root is required")
        return cls(
            datasets=dataset_map,
            nodes=compiled,
            edges=edge_list,
            dependencies=dependency_list,
            strategy_roots=compiled_roots,
            topological_order=topological_order,
        )

    def node(self, node_id: str) -> ResearchNode:
        try:
            return self._nodes[node_id]
        except KeyError as exc:
            raise ValueError(f"unknown research node: {node_id}") from exc

    def strategy_root(self, strategy_id: str) -> StrategyRoot:
        try:
            return self._strategy_roots[strategy_id]
        except KeyError as exc:
            raise ValueError(f"unknown strategy: {strategy_id}") from exc

    def strategy_dataset_dependencies(self, strategy_id: str) -> pd.DataFrame:
        root = self.strategy_root(strategy_id)
        node_ids = set(_ancestor_ids(root.root_node_id, _parent_edges(self._edges)))
        rows = [
            {
                "strategy_id": strategy_id,
                "node_id": dependency.node_id,
                "dataset_id": dependency.dataset_id,
                "role": dependency.role,
                "lookback": dependency.lookback,
                "availability_policy": dependency.availability_policy,
            }
            for dependency in self._dependencies
            if dependency.node_id in node_ids
        ]
        return pd.DataFrame(
            rows,
            columns=[
                "strategy_id",
                "node_id",
                "dataset_id",
                "role",
                "lookback",
                "availability_policy",
            ],
        ).sort_values(["dataset_id", "node_id", "role"], ignore_index=True)

    def resolve_run_inputs(
        self,
        run_id: str,
        strategy_id: str,
        snapshots: Iterable[DatasetSnapshot],
    ) -> pd.DataFrame:
        _require_text(run_id, "run_id")
        expected = set(
            self.strategy_dataset_dependencies(strategy_id)["dataset_id"].tolist()
        )
        snapshot_map = _unique_by(snapshots, "dataset_id", "dataset snapshot input")
        provided = set(snapshot_map)
        missing = sorted(expected - provided)
        unexpected = sorted(provided - expected)
        if missing:
            raise ValueError(f"run dataset inputs are missing: {', '.join(missing)}")
        if unexpected:
            raise ValueError(
                f"run dataset inputs contain unexpected datasets: {', '.join(unexpected)}"
            )
        _validate_snapshots(snapshot_map.values(), self._datasets)
        return pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "dataset_id": dataset_id,
                    "snapshot_id": snapshot_map[dataset_id].snapshot_id,
                }
                for dataset_id in sorted(expected)
            ]
        )

    def cache_key(
        self, node_id: str, snapshots: Iterable[DatasetSnapshot]
    ) -> str:
        node = self.node(node_id)
        ancestor_ids = set(_ancestor_ids(node_id, _parent_edges(self._edges)))
        expected = {
            dependency.dataset_id
            for dependency in self._dependencies
            if dependency.node_id in ancestor_ids
        }
        snapshot_map = _unique_by(snapshots, "dataset_id", "dataset snapshot input")
        provided = set(snapshot_map)
        missing = sorted(expected - provided)
        unexpected = sorted(provided - expected)
        if missing:
            raise ValueError(f"node cache inputs are missing: {', '.join(missing)}")
        if unexpected:
            raise ValueError(
                f"node cache inputs contain unexpected datasets: {', '.join(unexpected)}"
            )
        _validate_snapshots(snapshot_map.values(), self._datasets)
        return _definition_hash(
            {
                "definition_hash": node.definition_hash,
                "dataset_snapshots": {
                    dataset_id: snapshot_map[dataset_id].snapshot_id
                    for dataset_id in sorted(expected)
                },
            }
        )

    def tables(self) -> Mapping[str, pd.DataFrame]:
        dataset_rows = [vars(dataset) for dataset in self._datasets.values()]
        node_rows = [
            {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "operator": node.operator,
                "definition_hash": node.definition_hash,
                "config": _canonical_json(node.config),
                "input_types": _canonical_json(node.input_types),
            }
            for node in self._nodes.values()
        ]
        edge_rows = [vars(edge) for edge in self._edges]
        dependency_rows = [vars(dependency) for dependency in self._dependencies]
        root_rows = [vars(root) for root in self._strategy_roots.values()]
        transitive = pd.concat(
            [
                self.strategy_dataset_dependencies(strategy_id)
                for strategy_id in sorted(self._strategy_roots)
            ],
            ignore_index=True,
        )
        return {
            "datasets": pd.DataFrame(
                dataset_rows,
                columns=["dataset_id", "description", "schema_version"],
            ),
            "research_nodes": pd.DataFrame(
                node_rows,
                columns=[
                    "node_id",
                    "node_type",
                    "operator",
                    "definition_hash",
                    "config",
                    "input_types",
                ],
            ),
            "research_edges": pd.DataFrame(
                edge_rows,
                columns=[
                    "parent_node_id",
                    "child_node_id",
                    "input_role",
                    "input_order",
                ],
            ),
            "node_dataset_dependencies": pd.DataFrame(
                dependency_rows,
                columns=[
                    "node_id",
                    "dataset_id",
                    "role",
                    "lookback",
                    "availability_policy",
                ],
            ),
            "strategy_roots": pd.DataFrame(
                root_rows,
                columns=["strategy_id", "root_node_id", "definition_hash"],
            ),
            "strategy_dataset_dependencies": transitive,
        }


@dataclass(frozen=True)
class NodeExecutionContext:
    node: ResearchNode
    parent_inputs: Mapping[str, tuple[pd.DataFrame, ...]]
    dataset_inputs: Mapping[str, pd.DataFrame]


@dataclass(frozen=True)
class NodeArtifact:
    node_id: str
    node_type: str
    definition_hash: str
    cache_key: str
    value: pd.DataFrame
    artifact_path: Path


@dataclass(frozen=True)
class GraphExecutionResult:
    root: NodeArtifact
    node_artifacts: Mapping[str, NodeArtifact]
    executed_node_ids: tuple[str, ...]
    cache_hit_node_ids: tuple[str, ...]


NodeOperator = Callable[[NodeExecutionContext], pd.DataFrame]


class ResearchGraphExecutor:
    """Topological typed-node executor with verified immutable Parquet reuse."""

    def __init__(
        self,
        graph: ResearchGraph,
        cache_root: Path,
        operators: Mapping[str, NodeOperator],
    ) -> None:
        self.graph = graph
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.operators = dict(operators)

    def execute(
        self,
        strategy_id: str,
        datasets: Mapping[str, pd.DataFrame],
        snapshots: Iterable[DatasetSnapshot],
    ) -> GraphExecutionResult:
        root = self.graph.strategy_root(strategy_id)
        parent_edges = _parent_edges(self.graph._edges)
        ancestor_ids = set(_ancestor_ids(root.root_node_id, parent_edges))
        plan = tuple(
            node_id
            for node_id in self.graph._topological_order
            if node_id in ancestor_ids
        )
        expected_datasets = set(
            self.graph.strategy_dataset_dependencies(strategy_id)["dataset_id"]
        )
        provided_datasets = set(datasets)
        missing_datasets = sorted(expected_datasets - provided_datasets)
        unexpected_datasets = sorted(provided_datasets - expected_datasets)
        if missing_datasets:
            raise ValueError(
                f"graph execution datasets are missing: {', '.join(missing_datasets)}"
            )
        if unexpected_datasets:
            raise ValueError(
                "graph execution datasets contain unexpected inputs: "
                f"{', '.join(unexpected_datasets)}"
            )
        for dataset_id, frame in datasets.items():
            if not isinstance(frame, pd.DataFrame):
                raise TypeError(f"graph dataset must be a DataFrame: {dataset_id}")

        snapshot_list = tuple(snapshots)
        self.graph.resolve_run_inputs(
            "research-graph-execution", strategy_id, snapshot_list
        )
        snapshot_map = {snapshot.dataset_id: snapshot for snapshot in snapshot_list}
        artifacts: dict[str, NodeArtifact] = {}
        executed: list[str] = []
        cache_hits: list[str] = []
        direct_dependencies = _dependencies_by_node(self.graph._dependencies)
        for node_id in plan:
            node = self.graph.node(node_id)
            transitive_dataset_ids = {
                dependency.dataset_id
                for dependency in self.graph._dependencies
                if dependency.node_id
                in set(_ancestor_ids(node_id, parent_edges))
            }
            node_snapshots = [
                snapshot_map[dataset_id]
                for dataset_id in sorted(transitive_dataset_ids)
            ]
            cache_key = self.graph.cache_key(node_id, node_snapshots)
            cached = self._load_cached(node, cache_key)
            if cached is not None:
                artifacts[node_id] = cached
                cache_hits.append(node_id)
                continue

            operator = self.operators.get(node.operator)
            if operator is None:
                raise ValueError(f"research node operator is not registered: {node.operator}")
            grouped_parents: dict[str, list[pd.DataFrame]] = {}
            for edge in parent_edges.get(node_id, ()):
                grouped_parents.setdefault(edge.input_role, []).append(
                    artifacts[edge.parent_node_id].value
                )
            context = NodeExecutionContext(
                node=node,
                parent_inputs={
                    role: tuple(values) for role, values in grouped_parents.items()
                },
                dataset_inputs={
                    dependency.dataset_id: datasets[dependency.dataset_id]
                    for dependency in direct_dependencies.get(node_id, ())
                },
            )
            value = operator(context)
            _validate_node_value(node, value)
            artifact = self._publish(node, cache_key, value)
            artifacts[node_id] = artifact
            executed.append(node_id)
        return GraphExecutionResult(
            root=artifacts[root.root_node_id],
            node_artifacts=dict(artifacts),
            executed_node_ids=tuple(executed),
            cache_hit_node_ids=tuple(cache_hits),
        )

    def _artifact_root(self, cache_key: str) -> Path:
        return self.cache_root / cache_key[:2] / cache_key

    def _load_cached(
        self, node: ResearchNode, cache_key: str
    ) -> NodeArtifact | None:
        root = self._artifact_root(cache_key)
        if not root.exists():
            return None
        value_path = root / "value.parquet"
        manifest_path = root / "manifest.json"
        if not value_path.exists() or not manifest_path.exists():
            raise ValueError("research node cache is incomplete or corrupt")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("research node cache manifest is corrupt") from exc
        expected = {
            "cache_key": cache_key,
            "node_type": node.node_type,
            "definition_hash": node.definition_hash,
        }
        if any(str(manifest.get(key)) != value for key, value in expected.items()):
            raise ValueError("research node cache identity is corrupt")
        if _file_sha256(value_path) != str(manifest.get("file_hash")):
            raise ValueError("research node cache file hash mismatch or corrupt")
        try:
            value = pd.read_parquet(value_path)
        except Exception as exc:
            raise ValueError("research node cache parquet is corrupt") from exc
        if len(value) != int(manifest.get("row_count", -1)):
            raise ValueError("research node cache row count mismatch or corrupt")
        _validate_node_value(node, value)
        if _dataframe_hash(value) != str(manifest.get("content_hash")):
            raise ValueError("research node cache content hash mismatch or corrupt")
        return NodeArtifact(
            node_id=node.node_id,
            node_type=node.node_type,
            definition_hash=node.definition_hash,
            cache_key=cache_key,
            value=value,
            artifact_path=value_path,
        )

    def _publish(
        self, node: ResearchNode, cache_key: str, value: pd.DataFrame
    ) -> NodeArtifact:
        root = self._artifact_root(cache_key)
        root.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_root / f".writing-{uuid.uuid4().hex}"
        temporary.mkdir(parents=False, exist_ok=False)
        value_path = temporary / "value.parquet"
        try:
            value.to_parquet(value_path)
            manifest = {
                "cache_key": cache_key,
                "node_type": node.node_type,
                "definition_hash": node.definition_hash,
                "content_hash": _dataframe_hash(value),
                "file_hash": _file_sha256(value_path),
                "row_count": len(value),
            }
            (temporary / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            if root.exists():
                shutil.rmtree(temporary)
                cached = self._load_cached(node, cache_key)
                if cached is None:
                    raise ValueError("research node cache publication failed")
                return cached
            temporary.replace(root)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise
        published = self._load_cached(node, cache_key)
        if published is None:
            raise ValueError("research node cache publication failed")
        return published


CATALOG_KEYS = {
    "datasets": ["dataset_id"],
    "dataset_snapshots": ["dataset_id", "snapshot_id"],
    "research_nodes": ["node_id"],
    "research_edges": [
        "parent_node_id",
        "child_node_id",
        "input_role",
        "input_order",
    ],
    "node_dataset_dependencies": ["node_id", "dataset_id", "role"],
    "strategy_roots": ["strategy_id"],
    "strategy_dataset_dependencies": [
        "strategy_id",
        "node_id",
        "dataset_id",
        "role",
    ],
    "run_dataset_inputs": ["run_id", "dataset_id"],
}

CATALOG_COLUMNS = {
    "dataset_snapshots": [
        "dataset_id",
        "snapshot_id",
        "as_of",
        "content_fingerprint",
    ],
    "run_dataset_inputs": ["run_id", "dataset_id", "snapshot_id"],
}


class ParquetResearchCatalog:
    """Small immutable Parquet catalog for DAG definitions and run data lineage."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def table_names(self) -> tuple[str, ...]:
        return tuple(CATALOG_KEYS)

    def publish_graph(self, graph: ResearchGraph) -> None:
        for table_name, table in graph.tables().items():
            self._merge_immutable(table_name, table)

    def register_snapshots(self, snapshots: Iterable[DatasetSnapshot]) -> None:
        snapshot_list = tuple(snapshots)
        datasets = self.load_table("datasets")
        dataset_map = {
            str(row.dataset_id): DatasetDefinition(
                str(row.dataset_id), str(row.description), str(row.schema_version)
            )
            for row in datasets.itertuples(index=False)
        }
        _validate_snapshots(snapshot_list, dataset_map)
        table = pd.DataFrame(
            [
                {
                    "dataset_id": snapshot.dataset_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "as_of": pd.Timestamp(snapshot.as_of),
                    "content_fingerprint": snapshot.content_fingerprint,
                }
                for snapshot in snapshot_list
            ],
            columns=CATALOG_COLUMNS["dataset_snapshots"],
        )
        self._merge_immutable("dataset_snapshots", table)

    def bind_run_inputs(
        self,
        graph: ResearchGraph,
        run_id: str,
        strategy_id: str,
        snapshots: Iterable[DatasetSnapshot],
    ) -> None:
        snapshot_list = tuple(snapshots)
        resolved = graph.resolve_run_inputs(run_id, strategy_id, snapshot_list)
        registered = self.load_table("dataset_snapshots")
        registered_keys = {
            (str(row.dataset_id), str(row.snapshot_id)): str(row.content_fingerprint)
            for row in registered.itertuples(index=False)
        }
        for snapshot in snapshot_list:
            key = (snapshot.dataset_id, snapshot.snapshot_id)
            if key not in registered_keys:
                raise ValueError(f"dataset snapshot is not registered: {key}")
            if registered_keys[key] != snapshot.content_fingerprint:
                raise ValueError(f"dataset snapshot is immutable and differs: {key}")
        self._merge_immutable("run_dataset_inputs", resolved)

    def load_table(self, table_name: str) -> pd.DataFrame:
        if table_name not in CATALOG_KEYS:
            raise ValueError(f"unknown research catalog table: {table_name}")
        path = self.root / f"{table_name}.parquet"
        if path.exists():
            return pd.read_parquet(path)
        columns = CATALOG_COLUMNS.get(table_name, CATALOG_KEYS[table_name])
        return pd.DataFrame(columns=columns)

    def _merge_immutable(self, table_name: str, incoming: pd.DataFrame) -> None:
        key = CATALOG_KEYS[table_name]
        if incoming.empty:
            return
        if incoming.duplicated(key).any():
            raise ValueError(f"{table_name} contains duplicate primary keys")
        existing = self.load_table(table_name)
        if existing.empty:
            merged = incoming.copy()
        else:
            if set(existing.columns) != set(incoming.columns):
                raise ValueError(f"{table_name} schema is immutable and differs")
            existing_by_key = {
                tuple(getattr(row, column) for column in key): row
                for row in existing.itertuples(index=False)
            }
            new_rows: list[dict[str, Any]] = []
            for row in incoming.itertuples(index=False):
                row_key = tuple(getattr(row, column) for column in key)
                previous = existing_by_key.get(row_key)
                if previous is None:
                    new_rows.append(row._asdict())
                elif _row_hash(previous._asdict()) != _row_hash(row._asdict()):
                    raise ValueError(
                        f"{table_name} identity is immutable and has different content: "
                        f"{row_key}"
                    )
            merged = (
                pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
                if new_rows
                else existing
            )
        merged = merged.sort_values(key, ignore_index=True)
        temporary = self.root / f".{table_name}-{uuid.uuid4().hex}.tmp.parquet"
        merged.to_parquet(temporary, index=False)
        os.replace(temporary, self.root / f"{table_name}.parquet")


def _unique_by(items: Iterable[Any], attribute: str, label: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        value = str(getattr(item, attribute))
        _require_text(value, attribute)
        if value in result:
            raise ValueError(f"duplicate {label} identity: {value}")
        result[value] = item
    return result


def _validate_datasets(datasets: Mapping[str, DatasetDefinition]) -> None:
    for dataset in datasets.values():
        _require_text(dataset.description, "dataset description")
        _require_text(dataset.schema_version, "dataset schema_version")


def _validate_node_specs(nodes: Mapping[str, ResearchNodeSpec]) -> None:
    for node in nodes.values():
        if node.node_type not in NODE_TYPES:
            raise ValueError(f"unsupported research node type: {node.node_type}")
        _require_text(node.operator, "research node operator")
        _canonical_json(node.config)
        for role, allowed_types in node.input_types.items():
            _require_text(role, "node input role")
            if not allowed_types:
                raise ValueError(f"node input role has no allowed input types: {role}")
            invalid = set(allowed_types) - NODE_TYPES
            if invalid:
                raise ValueError(f"unsupported node input types: {sorted(invalid)}")


def _validate_edges_exist(
    nodes: Mapping[str, ResearchNodeSpec], edges: Sequence[ResearchEdge]
) -> None:
    seen_inputs: set[tuple[str, str, int]] = set()
    for edge in edges:
        if edge.parent_node_id not in nodes or edge.child_node_id not in nodes:
            raise ValueError("research edge references an unknown node")
        _require_text(edge.input_role, "edge input_role")
        if not isinstance(edge.input_order, int) or edge.input_order < 0:
            raise ValueError("edge input_order must be a non-negative integer")
        input_key = (edge.child_node_id, edge.input_role, edge.input_order)
        if input_key in seen_inputs:
            raise ValueError(f"duplicate child input position: {input_key}")
        seen_inputs.add(input_key)


def _topological_sort(
    nodes: Mapping[str, ResearchNodeSpec], edges: Sequence[ResearchEdge]
) -> tuple[str, ...]:
    incoming_count = {node_id: 0 for node_id in nodes}
    child_map = _children(edges)
    for edge in edges:
        incoming_count[edge.child_node_id] += 1
    ready = sorted(node_id for node_id, count in incoming_count.items() if count == 0)
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for child_id in sorted(child_map.get(node_id, ())):
            incoming_count[child_id] -= 1
            if incoming_count[child_id] == 0:
                ready.append(child_id)
                ready.sort()
    if len(order) != len(nodes):
        raise ValueError("research graph contains a cycle")
    return tuple(order)


def _validate_edge_types(
    nodes: Mapping[str, ResearchNodeSpec], edges: Sequence[ResearchEdge]
) -> None:
    for edge in edges:
        child = nodes[edge.child_node_id]
        if edge.input_role not in child.input_types:
            raise ValueError(
                f"node input type contract does not declare role: {edge.input_role}"
            )
        allowed = set(child.input_types[edge.input_role])
        parent_type = nodes[edge.parent_node_id].node_type
        if parent_type not in allowed:
            raise ValueError(
                f"node input type for {edge.input_role} requires {sorted(allowed)}, "
                f"got {parent_type}"
            )


def _validate_dependencies(
    nodes: Mapping[str, ResearchNodeSpec],
    datasets: Mapping[str, DatasetDefinition],
    dependencies: Sequence[NodeDatasetDependency],
) -> None:
    seen: set[tuple[str, str, str]] = set()
    for dependency in dependencies:
        if dependency.node_id not in nodes:
            raise ValueError(f"dataset dependency references unknown node: {dependency.node_id}")
        if dependency.dataset_id not in datasets:
            raise ValueError(
                f"dataset dependency references unknown dataset: {dependency.dataset_id}"
            )
        if dependency.role not in DATASET_ROLES:
            raise ValueError(f"unsupported dataset dependency role: {dependency.role}")
        if not isinstance(dependency.lookback, int) or dependency.lookback < 0:
            raise ValueError("dataset dependency lookback must be a non-negative integer")
        _require_text(dependency.availability_policy, "availability_policy")
        key = (dependency.node_id, dependency.dataset_id, dependency.role)
        if key in seen:
            raise ValueError(f"duplicate node dataset dependency: {key}")
        seen.add(key)


def _validate_snapshots(
    snapshots: Iterable[DatasetSnapshot],
    datasets: Mapping[str, DatasetDefinition],
) -> None:
    snapshot_ids: set[tuple[str, str]] = set()
    for snapshot in snapshots:
        if snapshot.dataset_id not in datasets:
            raise ValueError(f"snapshot references unknown dataset: {snapshot.dataset_id}")
        _require_text(snapshot.snapshot_id, "snapshot_id")
        _require_text(snapshot.content_fingerprint, "content_fingerprint")
        timestamp = pd.Timestamp(snapshot.as_of)
        if pd.isna(timestamp):
            raise ValueError("dataset snapshot as_of must be a valid timestamp")
        key = (snapshot.dataset_id, snapshot.snapshot_id)
        if key in snapshot_ids:
            raise ValueError(f"duplicate dataset snapshot identity: {key}")
        snapshot_ids.add(key)


def _parent_edges(edges: Sequence[ResearchEdge]) -> dict[str, tuple[ResearchEdge, ...]]:
    result: dict[str, list[ResearchEdge]] = {}
    for edge in edges:
        result.setdefault(edge.child_node_id, []).append(edge)
    return {
        child: tuple(
            sorted(items, key=lambda edge: (edge.input_role, edge.input_order, edge.parent_node_id))
        )
        for child, items in result.items()
    }


def _children(edges: Sequence[ResearchEdge]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for edge in edges:
        result.setdefault(edge.parent_node_id, set()).add(edge.child_node_id)
    return result


def _dependencies_by_node(
    dependencies: Sequence[NodeDatasetDependency],
) -> dict[str, tuple[NodeDatasetDependency, ...]]:
    result: dict[str, list[NodeDatasetDependency]] = {}
    for dependency in dependencies:
        result.setdefault(dependency.node_id, []).append(dependency)
    return {
        node_id: tuple(
            sorted(
                items,
                key=lambda item: (
                    item.dataset_id,
                    item.role,
                    item.lookback,
                    item.availability_policy,
                ),
            )
        )
        for node_id, items in result.items()
    }


def _ancestor_ids(
    node_id: str, parent_edges: Mapping[str, Sequence[ResearchEdge]]
) -> list[str]:
    visited: set[str] = set()

    def visit(current: str) -> None:
        for edge in parent_edges.get(current, ()):
            visit(edge.parent_node_id)
        visited.add(current)

    visit(node_id)
    return sorted(visited)


def _definition_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _row_hash(row: Mapping[str, Any]) -> str:
    return _definition_hash(dict(row))


def _validate_node_value(node: ResearchNode, value: Any) -> None:
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"research node must return a DataFrame: {node.node_id}")
    if not value.index.is_unique or not value.columns.is_unique:
        raise ValueError(f"research node output axes must be unique: {node.node_id}")
    if node.node_type == "mask":
        if not all(pd.api.types.is_bool_dtype(dtype) for dtype in value.dtypes):
            raise ValueError("mask research node output must contain boolean columns")
        return
    if not all(pd.api.types.is_numeric_dtype(dtype) for dtype in value.dtypes):
        raise ValueError(f"{node.node_type} node output must be numeric")
    numeric = value.to_numpy(dtype="float64")
    if np.isinf(numeric).any():
        raise ValueError(f"{node.node_type} node output must not contain infinity")


def _dataframe_hash(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
    digest.update(
        _canonical_json(
            {
                "columns": [str(column) for column in frame.columns],
                "dtypes": [str(dtype) for dtype in frame.dtypes],
                "index_names": [str(name) for name in frame.index.names],
            }
        ).encode("utf-8")
    )
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=_canonical_json)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        return _json_value(value.item())
    return value


def _require_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
