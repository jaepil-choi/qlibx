from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from kwam_qlib_backend.research_graph import (
    DatasetDefinition,
    DatasetSnapshot,
    NodeDatasetDependency,
    ParquetResearchCatalog,
    ResearchEdge,
    ResearchGraph,
    ResearchGraphExecutor,
    NodeExecutionContext,
    ResearchNodeSpec,
    StrategyRootSpec,
)


def _acyclic_graph(*, decay_config: dict[str, float] | None = None) -> ResearchGraph:
    graph_inputs = _graph_inputs(decay_config=decay_config)
    return ResearchGraph.compile(**graph_inputs)


def _graph_inputs(
    *, decay_config: dict[str, float] | None = None
) -> dict[str, object]:
    datasets = [
        DatasetDefinition("returns", "PIT return matrix", "1"),
        DatasetDefinition("peer_groups", "PIT peer classification", "1"),
        DatasetDefinition("universe", "PIT investable universe", "2"),
        DatasetDefinition("risk_model", "risk covariance", "1"),
    ]
    nodes = [
        ResearchNodeSpec("peer", "signal", "peer_momentum"),
        ResearchNodeSpec(
            "top", "mask", "top_pct", {"pct": 0.2}, {"signal": ("signal",)}
        ),
        ResearchNodeSpec(
            "decay",
            "signal",
            "decay",
            decay_config or {"half_life": 5.0},
            {"signal": ("signal",)},
        ),
        ResearchNodeSpec(
            "combine",
            "active_intent",
            "combine",
            {"method": "mean"},
            {"member": ("signal", "active_intent")},
        ),
        ResearchNodeSpec(
            "ensemble",
            "active_intent",
            "combine",
            {"method": "mean"},
            {"member": ("signal", "active_intent")},
        ),
        ResearchNodeSpec(
            "optimizer",
            "physical_target",
            "intent_tracking_optimizer",
            {"constraint_set": "enhanced-index-v1"},
            {"intent": ("active_intent",), "risk_mask": ("mask",)},
        ),
    ]
    edges = [
        ResearchEdge("peer", "top", "signal", 0),
        ResearchEdge("peer", "decay", "signal", 0),
        ResearchEdge("top", "optimizer", "risk_mask", 0),
        ResearchEdge("decay", "combine", "member", 0),
        ResearchEdge("combine", "ensemble", "member", 0),
        ResearchEdge("decay", "ensemble", "member", 1),
        ResearchEdge("ensemble", "optimizer", "intent", 0),
    ]
    dependencies = [
        NodeDatasetDependency("peer", "returns", "feature", 20, "pit_close"),
        NodeDatasetDependency(
            "peer", "peer_groups", "feature", 0, "known_at_decision"
        ),
        NodeDatasetDependency("top", "universe", "universe", 0, "pit_open"),
        NodeDatasetDependency("optimizer", "risk_model", "risk", 60, "pit_close"),
    ]
    return {
        "datasets": datasets,
        "nodes": nodes,
        "edges": edges,
        "dependencies": dependencies,
        "strategy_roots": [StrategyRootSpec("peer-enhanced.v1", "optimizer")],
    }


def _snapshots() -> list[DatasetSnapshot]:
    return [
        DatasetSnapshot("returns", "returns@2024-01-31", "2024-01-31", "r1"),
        DatasetSnapshot("peer_groups", "peers@2024-01-31", "2024-01-31", "p1"),
        DatasetSnapshot("universe", "universe@2024-01-31", "2024-01-31", "u1"),
        DatasetSnapshot("risk_model", "risk@2024-01-31", "2024-01-31", "v1"),
    ]


def test_definition_hash_is_recursive_deterministic_and_config_sensitive() -> None:
    first = _acyclic_graph(decay_config={"half_life": 5.0, "floor": 0.0})
    reordered = _acyclic_graph(decay_config={"floor": 0.0, "half_life": 5.0})
    changed = _acyclic_graph(decay_config={"half_life": 10.0, "floor": 0.0})

    assert first.node("optimizer").definition_hash == reordered.node(
        "optimizer"
    ).definition_hash
    assert first.node("optimizer").definition_hash != changed.node(
        "optimizer"
    ).definition_hash
    assert first.strategy_root("peer-enhanced.v1").definition_hash == first.node(
        "optimizer"
    ).definition_hash


def test_graph_rejects_cycles_and_parent_input_type_mismatch() -> None:
    inputs = _graph_inputs()
    inputs["edges"] = [
        *inputs["edges"],
        ResearchEdge("optimizer", "peer", "feedback", 0),
    ]
    with pytest.raises(ValueError, match="cycle"):
        ResearchGraph.compile(**inputs)

    inputs = _graph_inputs()
    inputs["edges"] = [
        edge
        for edge in inputs["edges"]
        if not (edge.parent_node_id == "ensemble" and edge.child_node_id == "optimizer")
    ] + [ResearchEdge("peer", "optimizer", "intent", 0)]
    with pytest.raises(ValueError, match="input type|active_intent"):
        ResearchGraph.compile(**inputs)


def test_strategy_has_one_physical_execution_root_and_transitive_dependencies() -> None:
    graph = _acyclic_graph()

    dependencies = graph.strategy_dataset_dependencies("peer-enhanced.v1")

    assert set(dependencies["dataset_id"]) == {
        "returns",
        "peer_groups",
        "universe",
        "risk_model",
    }
    assert set(dependencies["role"]) == {"feature", "universe", "risk"}
    assert graph.node("optimizer").node_type == "physical_target"

    inputs = _graph_inputs()
    inputs["strategy_roots"] = [StrategyRootSpec("bad-root", "ensemble")]
    with pytest.raises(ValueError, match="physical_target"):
        ResearchGraph.compile(**inputs)


def test_run_inputs_resolve_every_logical_dataset_to_immutable_snapshot() -> None:
    graph = _acyclic_graph()
    snapshots = _snapshots()

    resolved = graph.resolve_run_inputs(
        "run-001", "peer-enhanced.v1", snapshots
    )

    assert set(resolved.columns) == {"run_id", "dataset_id", "snapshot_id"}
    assert len(resolved) == 4
    with pytest.raises(ValueError, match="missing.*risk_model"):
        graph.resolve_run_inputs("run-002", "peer-enhanced.v1", snapshots[:-1])
    with pytest.raises(ValueError, match="unexpected"):
        graph.resolve_run_inputs(
            "run-003",
            "peer-enhanced.v1",
            [
                *snapshots,
                DatasetSnapshot("extra", "extra@1", "2024-01-31", "x1"),
            ],
        )


def test_node_cache_key_uses_only_transitive_snapshot_ids() -> None:
    graph = _acyclic_graph()
    first = graph.cache_key("optimizer", _snapshots())
    reordered = graph.cache_key("optimizer", list(reversed(_snapshots())))
    changed = [replace(item, snapshot_id=f"{item.snapshot_id}-v2") for item in _snapshots()]

    assert first == reordered
    assert first != graph.cache_key("optimizer", changed)


def test_parquet_catalog_is_queryable_idempotent_and_immutable(tmp_path) -> None:
    graph = _acyclic_graph()
    catalog = ParquetResearchCatalog(tmp_path / "research-catalog")
    catalog.publish_graph(graph)
    catalog.publish_graph(graph)
    catalog.register_snapshots(_snapshots())
    catalog.bind_run_inputs(
        graph, "run-001", "peer-enhanced.v1", _snapshots()
    )

    expected_tables = {
        "datasets",
        "dataset_snapshots",
        "research_nodes",
        "research_edges",
        "node_dataset_dependencies",
        "strategy_roots",
        "strategy_dataset_dependencies",
        "run_dataset_inputs",
    }
    assert expected_tables <= set(catalog.table_names())
    assert len(catalog.load_table("run_dataset_inputs")) == 4
    assert pd.api.types.is_datetime64_any_dtype(
        catalog.load_table("dataset_snapshots")["as_of"]
    )

    changed = replace(_snapshots()[0], content_fingerprint="tampered")
    with pytest.raises(ValueError, match="immutable|different"):
        catalog.register_snapshots([changed])


def test_graph_executor_runs_nested_ensemble_once_and_reuses_verified_cache(
    tmp_path,
) -> None:
    graph = _acyclic_graph()
    dates = pd.bdate_range("2024-01-02", periods=2)
    columns = ["A", "B"]
    datasets = {
        "returns": pd.DataFrame([[0.1, -0.2], [0.2, 0.1]], index=dates, columns=columns),
        "peer_groups": pd.DataFrame(1, index=dates, columns=columns),
        "universe": pd.DataFrame(True, index=dates, columns=columns),
        "risk_model": pd.DataFrame(1.0, index=dates, columns=columns),
    }
    calls: dict[str, int] = {}

    def operator(context: NodeExecutionContext) -> pd.DataFrame:
        calls[context.node.node_id] = calls.get(context.node.node_id, 0) + 1
        if context.node.operator == "peer_momentum":
            return context.dataset_inputs["returns"]
        if context.node.operator == "top_pct":
            return context.parent_inputs["signal"][0] > 0
        if context.node.operator == "decay":
            return context.parent_inputs["signal"][0] * 0.5
        if context.node.operator == "combine":
            members = context.parent_inputs["member"]
            return sum(members[1:], members[0].copy()) / len(members)
        intent = context.parent_inputs["intent"][0]
        mask = context.parent_inputs["risk_mask"][0]
        return intent.where(mask, 0.0)

    operators = {
        name: operator
        for name in {
            "peer_momentum",
            "top_pct",
            "decay",
            "combine",
            "intent_tracking_optimizer",
        }
    }
    executor = ResearchGraphExecutor(graph, tmp_path / "node-cache", operators)

    first = executor.execute("peer-enhanced.v1", datasets, _snapshots())
    second = executor.execute("peer-enhanced.v1", datasets, _snapshots())

    assert first.executed_node_ids == (
        "peer",
        "decay",
        "combine",
        "ensemble",
        "top",
        "optimizer",
    )
    assert second.executed_node_ids == ()
    assert set(second.cache_hit_node_ids) == set(first.executed_node_ids)
    assert all(count == 1 for count in calls.values())
    assert first.root.node_type == "physical_target"
    pd.testing.assert_frame_equal(first.root.value, second.root.value)


def test_graph_executor_rejects_corrupt_cached_node_artifact(tmp_path) -> None:
    graph = _acyclic_graph()
    dates = pd.bdate_range("2024-01-02", periods=2)
    columns = ["A", "B"]
    datasets = {
        "returns": pd.DataFrame(1.0, index=dates, columns=columns),
        "peer_groups": pd.DataFrame(1, index=dates, columns=columns),
        "universe": pd.DataFrame(True, index=dates, columns=columns),
        "risk_model": pd.DataFrame(1.0, index=dates, columns=columns),
    }

    def identity(context: NodeExecutionContext) -> pd.DataFrame:
        if context.dataset_inputs:
            return next(iter(context.dataset_inputs.values())).copy()
        return next(iter(context.parent_inputs.values()))[0].copy()

    operators = {
        name: identity
        for name in {
            "peer_momentum",
            "top_pct",
            "decay",
            "combine",
            "intent_tracking_optimizer",
        }
    }
    executor = ResearchGraphExecutor(graph, tmp_path / "node-cache", operators)
    result = executor.execute("peer-enhanced.v1", datasets, _snapshots())
    result.node_artifacts["peer"].artifact_path.write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="hash|corrupt"):
        executor.execute("peer-enhanced.v1", datasets, _snapshots())
