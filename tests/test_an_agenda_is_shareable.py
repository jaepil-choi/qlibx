"""An agenda is a cadence, and cadences are shared: several strategies may name one agenda.

`docs/issues/040`, owner-decided 2026-08-31, implemented in record `138` (campaign Step 6). The
workspace keyed `strategy_configs` by `agenda_id`, so an agenda drove at most one strategy and the
second registration was refused by naming the agenda -- an object the author never touched. A
comparison across factor models (one trading rule, three residual panels, one daily cadence) had
to declare three byte-identical agendas and keep them in step by hand.

The binding is keyed by the strategy now. Two strategies naming one agenda are two bindings; one
strategy naming two agendas is the conflict, and the refusal names the strategy. A document
written before this decodes for one release and is written forward.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest
import yaml

from vqapr.domain.errors import VqaprError
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import StrategyConfig
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.workspace import Workspace

CALLBACK = OperationRole.STRATEGY_CALLBACK


def _component(name: str, root: Path) -> ComponentRef:
    return ComponentRef.of(
        name, ComponentKind.STRATEGY_MODEL, root / f"{name}.py", "Strategy", fingerprint="a" * 64
    )


def _agenda(agenda_id: str) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=agenda_id,
        role=OperationRole.STRATEGY_CALLBACK,
        timezone="Asia/Seoul",
        occurrences=(
            OperationOccurrence(
                f"{agenda_id}-1",
                OperationRole.STRATEGY_CALLBACK,
                LocalInstantDeclaration(date(2024, 3, 5), time(4, 0), "Asia/Seoul", 0, "+09:00"),
            ),
        ),
        provenance="test",
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    space = Workspace.create(tmp_path)
    space.register_agenda(_agenda("krx-rebalance"))
    space.register_agenda(_agenda("krx-weekly"))
    for name in ("ou-k0", "ou-pca5", "ou-ff5"):
        space.register_component(_component(name, tmp_path))
    return space


def test_three_strategies_share_one_agenda(workspace: Workspace) -> None:
    """The comparison the testbed wanted: one cadence, three strategies, three registrations."""
    for name in ("ou-k0", "ou-pca5", "ou-ff5"):
        config = StrategyConfig(
            workspace.component(name), "krx-rebalance", OperationRole.STRATEGY_CALLBACK
        )
        assert workspace.register_strategy_config(config) is True

    reopened = Workspace.open(workspace.project_root)
    assert [str(config.component.component_id) for config in reopened.strategy_configs] == [
        "ou-ff5",
        "ou-k0",
        "ou-pca5",
    ]
    assert {config.agenda_id for config in reopened.strategy_configs} == {"krx-rebalance"}
    assert reopened.strategy_config("ou-ff5").agenda_id == "krx-rebalance"


def test_one_strategy_bound_twice_is_the_conflict_and_it_names_the_strategy(
    workspace: Workspace,
) -> None:
    first = StrategyConfig(workspace.component("ou-k0"), "krx-rebalance", CALLBACK)
    second = StrategyConfig(workspace.component("ou-k0"), "krx-weekly", CALLBACK)
    workspace.register_strategy_config(first)

    with pytest.raises(VqaprError) as refused:
        workspace.register_strategy_config(second)

    payload = refused.value.as_dict()
    failure = payload["failures"][0]
    assert failure["code"] == "workspace.strategy_config.register.conflict"
    assert "'ou-k0'" in failure["requirement"], "the refusal names the strategy the author wrote"
    assert "krx-rebalance" in failure["observed"], "and the agenda it is already bound to"
    assert workspace.register_strategy_config(first) is False, "re-binding the same is idempotent"


def test_a_binding_is_found_by_the_strategy_and_a_missing_one_says_so(workspace: Workspace) -> None:
    with pytest.raises(VqaprError) as refused:
        workspace.strategy_config("ou-k0")
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "workspace.strategy_config.register.missing"
    assert "strategy 'ou-k0'" in failure["requirement"]


def test_a_document_keyed_by_agenda_still_decodes_and_is_written_forward(
    workspace: Workspace,
) -> None:
    """Write-forward, one release decodable: the old shape keyed the binding by agenda."""
    config = StrategyConfig(workspace.component("ou-k0"), "krx-rebalance", CALLBACK)
    workspace.register_strategy_config(config)
    document = yaml.safe_load(workspace.path.read_text(encoding="utf-8"))
    assert document["strategy_configs"] == {
        "ou-k0": {"agenda_id": "krx-rebalance", "agenda_role": "STRATEGY_CALLBACK"}
    }

    # The shape before record 138.
    document["strategy_configs"] = {
        "krx-rebalance": {"component": "ou-k0", "agenda_role": "STRATEGY_CALLBACK"}
    }
    workspace.path.write_text(yaml.safe_dump(document), encoding="utf-8")

    reopened = Workspace.open(workspace.project_root)
    assert reopened.strategy_config("ou-k0") == config
    # A second binding to the same agenda lands beside it, and the write is in the new shape.
    reopened.register_strategy_config(
        StrategyConfig(reopened.component("ou-ff5"), "krx-rebalance", CALLBACK)
    )
    rewritten = yaml.safe_load(workspace.path.read_text(encoding="utf-8"))
    assert set(rewritten["strategy_configs"]) == {"ou-k0", "ou-ff5"}
