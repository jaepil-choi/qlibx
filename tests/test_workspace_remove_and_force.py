"""`register --force` and `remove`: the repair path a refusal used to name and forbid.

Editing a registered component and re-running produced two refusals that pointed at each other.
`loading.py` said *re-register the component*; `register_component` then refused exactly that and
demanded a new `component_id`. A reader following either arrived at the other, which
`docs/implementations/057` names as worse than a generic error.

These pin the way out and the guard that keeps it from becoming a way to break a workspace.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from vqapr.domain.errors import VqaprError
from vqapr.extension.component import ComponentKind
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.extension.registration import ComponentRef
from vqapr.public import (
    LocalInstantDeclaration,
    OperationAgenda,
    OperationOccurrence,
    OperationRole,
    StrategyConfig,
)
from vqapr.workspace import Workspace

ZONE = "Asia/Seoul"
OFFSET = "+09:00"


def _ref(path: Path, component_id: str = "mom") -> ComponentRef:
    return ComponentRef(
        component_id=component_id,
        kind=ComponentKind.STRATEGY_MODEL,
        path=path,
        object_name="S",
        config={},
        fingerprint=fingerprint_component(
            path, kind=ComponentKind.STRATEGY_MODEL, object_name="S", config={}
        ),
    )


def _workspace(tmp_path: Path) -> tuple[Workspace, Path]:
    workspace = Workspace.create(tmp_path)
    source = tmp_path / "s.py"
    source.write_text("class S:\n    pass\n", encoding="utf-8")
    return workspace, source


def _bind_a_config(workspace: Workspace, ref: ComponentRef) -> None:
    occurrence = OperationOccurrence(
        "a-1",
        OperationRole.STRATEGY_CALLBACK,
        LocalInstantDeclaration(date(2026, 4, 1), time(9, 0), ZONE, 0, OFFSET),
    )
    workspace.register_agenda(
        OperationAgenda.from_occurrences(
            agenda_id="daily",
            role=OperationRole.STRATEGY_CALLBACK,
            timezone=ZONE,
            occurrences=(occurrence,),
            provenance="test",
        )
    )
    workspace.register_strategy_config(
        StrategyConfig(ref, "daily", OperationRole.STRATEGY_CALLBACK)
    )


def test_an_edited_component_re_registers_in_place(tmp_path: Path) -> None:
    """No flag needed: replacement is the default, because editing is the ordinary loop.

    Written first as "refused without force", which was true for one milestone. Issue 009's
    Decision 2 then removed the refusal entirely rather than leaving it behind a flag -- a
    refusal the caller must pass an argument to bypass, on an event that is ordinary, is the same
    friction with an extra step.
    """
    workspace, source = _workspace(tmp_path)
    first = _ref(source)
    workspace.register_component(first)

    source.write_text("class S:\n    value = 1\n", encoding="utf-8")
    second = _ref(source)
    assert second.fingerprint != first.fingerprint

    assert workspace.register_component(second) is True
    assert workspace.component("mom").fingerprint == second.fingerprint
    assert len(workspace.components) == 1, "an edit must not mint a second component id"


def test_force_replaces_the_edited_component_under_the_same_id(tmp_path: Path) -> None:
    """The edit loop, end to end: change a line, re-register, keep the id.

    This is the assertion that separates the fix from the defect. Before it, the only route was a
    new `component_id` plus a new config binding plus a spec edit -- four steps for a one-line
    change, and a workspace that accumulated `mom`, `mom-eb04...`, `mom-91c7...` for one strategy.
    """
    workspace, source = _workspace(tmp_path)
    before = _ref(source)
    workspace.register_component(before)

    source.write_text("class S:\n    value = 1\n", encoding="utf-8")
    after = _ref(source)
    assert after.fingerprint != before.fingerprint, "the edit must move the fingerprint"

    assert workspace.register_component(after, force=True) is True
    assert workspace.component("mom").fingerprint == after.fingerprint
    # One id, not two. The point of the change.
    assert len(workspace.components) == 1


def test_force_on_an_unchanged_component_stays_idempotent(tmp_path: Path) -> None:
    """`force` is permission to replace, not an instruction to write."""
    workspace, source = _workspace(tmp_path)
    ref = _ref(source)
    workspace.register_component(ref)

    assert workspace.register_component(ref, force=True) is False


def test_remove_withdraws_a_registration_and_is_idempotent(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    workspace.register_component(_ref(source))

    assert workspace.remove("component", "mom") is True
    assert workspace.remove("component", "mom") is False


def test_remove_refuses_while_something_still_references_it(tmp_path: Path) -> None:
    """And the refusal NAMES the blocker, per implementations/057.

    A refusal that says only "something still references this" sends the reader looking through
    the workspace by hand, which is the failure mode that rule exists to prevent.
    """
    workspace, source = _workspace(tmp_path)
    ref = _ref(source)
    workspace.register_component(ref)
    _bind_a_config(workspace, ref)

    with pytest.raises(VqaprError, match=r"workspace\.remove\.referenced") as error:
        workspace.remove("component", "mom")
    # Asserted on `observed` and `fix` rather than on str(error): those are the fields a reader
    # is shown, and naming the blocker is the whole requirement here.
    observed = " ".join(failure.observed or "" for failure in error.value.failures)
    remedy = " ".join(failure.fix or "" for failure in error.value.failures)
    assert "strategy config 'daily'" in observed, (
        "the refusal must name what blocks it, not merely that something does"
    )
    assert "strategy config 'daily'" in remedy, "and the fix must name what to remove first"
    # Refused means unchanged, not partially applied.
    assert workspace.component("mom").fingerprint == ref.fingerprint


def test_references_to_reports_every_edge_that_blocks_a_removal(tmp_path: Path) -> None:
    """The reverse lookup this workspace did not have.

    `workspace.py`'s existing checks run in the FORWARD direction while decoding -- a config
    naming a component that must exist. Withdrawing asks the opposite question, and nothing
    answered it before.
    """
    workspace, source = _workspace(tmp_path)
    ref = _ref(source)
    workspace.register_component(ref)
    _bind_a_config(workspace, ref)

    assert workspace.references_to("component", "mom") == ("strategy config 'daily'",)
    assert workspace.references_to("agenda", "daily") == ("strategy config 'daily'",)
    # An id nothing points at, and an id that does not exist, are both removable.
    assert workspace.references_to("component", "absent") == ()


def test_a_leaf_declaration_has_no_referents(tmp_path: Path) -> None:
    """A run definition names a config, and a run definition is not a workspace registration."""
    workspace, source = _workspace(tmp_path)
    ref = _ref(source)
    workspace.register_component(ref)
    _bind_a_config(workspace, ref)

    assert workspace.references_to("strategy_config", "daily") == ()


def test_a_dataset_refuses_rather_than_claiming_it_is_unreferenced(tmp_path: Path) -> None:
    """Returning `()` here would read as "safe to remove", and the workspace cannot know that.

    A dataset's readers are declared inside component requirements, which this document does not
    index. Saying so is honest; an empty tuple would be a guess wearing an answer's clothes.
    """
    workspace, _ = _workspace(tmp_path)

    with pytest.raises(VqaprError, match=r"workspace\.remove\.unsupported_kind"):
        workspace.references_to("dataset", "prices")


def test_an_unknown_kind_is_refused_with_the_permitted_set(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)

    with pytest.raises(VqaprError, match=r"workspace\.remove\.unsupported_kind"):
        workspace.remove("nonsense", "x")
