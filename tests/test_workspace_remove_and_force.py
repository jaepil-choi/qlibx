"""Re-registering in place and `remove`: the repair path a refusal used to name and forbid.

Editing a registered component and re-running produced two refusals that pointed at each other.
`loading.py` said *re-register the component*; `register_component` then refused exactly that and
demanded a new `component_id`. A reader following either arrived at the other, which
`docs/implementations/057` names as worse than a generic error.

These pin the way out and the guard that keeps it from becoming a way to break a workspace.

What can still name a component is a run (record `148`): the strategy binding that used to be a
registered `strategy_config` is derived by preflight from the run's own sessions and wall time,
so a run is the one live declaration a removal has to look for.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest

from vqapr.domain.errors import VqaprError
from vqapr.extension.component import ComponentKind
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.extension.registration import ComponentRef
from vqapr.public import AccountMode, AccountSnapshot, RunDefinition, StrategyEntry
from vqapr.workspace import Workspace

ZONE = "Asia/Seoul"


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


def _register_a_run(workspace: Workspace, ref: ComponentRef) -> None:
    with Workspace.transaction(workspace) as t:
        t.register_run(
            RunDefinition(
                run_id="daily",
                strategies=(StrategyEntry(str(ref.component_id)),),
                instruments=("A",),
                timezone=ZONE,
                at=time(9, 0),
                sessions=(date(2026, 4, 1),),
                initial_account_snapshot=AccountSnapshot(0, Decimal("1000"), {}),
                initial_account_mode=AccountMode.LONG_ONLY,
            )
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
    with Workspace.transaction(workspace) as t:
        t.register_component(first)

    source.write_text("class S:\n    value = 1\n", encoding="utf-8")
    second = _ref(source)
    assert second.fingerprint != first.fingerprint

    with Workspace.transaction(workspace) as t:
        assert t.register_component(second) is True
    assert workspace.component("mom").fingerprint == second.fingerprint
    assert len(workspace.components) == 1, "an edit must not mint a second component id"


def test_there_is_no_force_parameter_left_to_promise(tmp_path: Path) -> None:
    """`docs/issues/067`: the method carried a `force` that gated nothing, and the skill kept
    promising `register --force` against it. One contract, replacement by default, and the
    dead spelling is gone so a docstring cannot cite it again."""
    workspace, source = _workspace(tmp_path)
    ref = _ref(source)
    with pytest.raises(TypeError), Workspace.transaction(workspace) as t:
        t.register_component(ref, force=True)  # type: ignore[call-arg]


def test_re_registering_an_unchanged_component_stays_idempotent(tmp_path: Path) -> None:
    """A second registration of the same bytes writes nothing and says so."""
    workspace, source = _workspace(tmp_path)
    ref = _ref(source)
    with Workspace.transaction(workspace) as t:
        t.register_component(ref)

    with Workspace.transaction(workspace) as t:
        assert t.register_component(ref) is False


def test_remove_withdraws_a_registration_and_is_idempotent(tmp_path: Path) -> None:
    workspace, source = _workspace(tmp_path)
    with Workspace.transaction(workspace) as t:
        t.register_component(_ref(source))

    assert workspace.remove("component", "mom") is True
    assert workspace.remove("component", "mom") is False


def test_remove_refuses_while_something_still_references_it(tmp_path: Path) -> None:
    """And the refusal NAMES the blocker, per implementations/057.

    A refusal that says only "something still references this" sends the reader looking through
    the workspace by hand, which is the failure mode that rule exists to prevent.
    """
    workspace, source = _workspace(tmp_path)
    ref = _ref(source)
    with Workspace.transaction(workspace) as t:
        t.register_component(ref)
    _register_a_run(workspace, ref)

    with pytest.raises(VqaprError, match=r"workspace\.remove\.referenced") as error:
        workspace.remove("component", "mom")
    # Asserted on `observed` and `fix` rather than on str(error): those are the fields a reader
    # is shown, and naming the blocker is the whole requirement here.
    observed = " ".join(failure.observed or "" for failure in error.value.failures)
    remedy = " ".join(failure.fix or "" for failure in error.value.failures)
    assert "run 'daily'" in observed, (
        "the refusal must name what blocks it, not merely that something does"
    )
    assert "run 'daily'" in remedy, "and the fix must name what to remove first"
    # Refused means unchanged, not partially applied.
    assert workspace.component("mom").fingerprint == ref.fingerprint


def test_references_to_reports_every_edge_that_blocks_a_removal(tmp_path: Path) -> None:
    """The reverse lookup this workspace did not have.

    `workspace.py`'s existing checks run in the FORWARD direction while decoding -- a run naming
    a component that must exist. Withdrawing asks the opposite question, and nothing answered it
    before.
    """
    workspace, source = _workspace(tmp_path)
    ref = _ref(source)
    with Workspace.transaction(workspace) as t:
        t.register_component(ref)
    _register_a_run(workspace, ref)

    assert workspace.references_to("component", "mom") == ("run 'daily'",)
    # An id nothing points at, and an id that does not exist, are both removable.
    assert workspace.references_to("component", "absent") == ()


def test_a_leaf_declaration_has_no_referents(tmp_path: Path) -> None:
    """A run is the top of the document: nothing names a run, so it is always removable."""
    workspace, source = _workspace(tmp_path)
    ref = _ref(source)
    with Workspace.transaction(workspace) as t:
        t.register_component(ref)
    _register_a_run(workspace, ref)

    assert workspace.references_to("run", "daily") == ()
    assert workspace.remove("run", "daily") is True
    # With the run gone the component it named is free.
    assert workspace.references_to("component", "mom") == ()


def test_a_dataset_is_blocked_by_the_runs_that_take_their_sessions_from_it(
    tmp_path: Path,
) -> None:
    """`docs/issues/060`: a dataset is removable, and what the DOCUMENT knows blocks it.

    A component's reads live in its code and are refused at its next preflight; a registered
    run's `sessions_from` lives here, and is the blocker this walk can name.
    """
    workspace, source = _workspace(tmp_path)
    ref = _ref(source)
    with Workspace.transaction(workspace) as t:
        t.register_component(ref)

    assert workspace.references_to("dataset", "prices") == ()
    assert workspace.remove("dataset", "prices") is False, "absent is idempotent, not an error"

    with Workspace.transaction(workspace) as t:
        t.register_run(
            RunDefinition(
                run_id="daily",
                strategies=(StrategyEntry(str(ref.component_id)),),
                instruments=("A",),
                timezone=ZONE,
                at=time(9, 0),
                sessions=(date(2026, 4, 1),),
                initial_account_snapshot=AccountSnapshot(0, Decimal("1000"), {}),
                initial_account_mode=AccountMode.LONG_ONLY,
            )
        )
    assert workspace.references_to("dataset", "prices") == ()
    # `sessions_from` a dataset that is not registered is refused at `register_run`, so the
    # blocker is asked through the CLI journey in `tests/cli/test_rm_dataset_withdraws_a_registration.py`.


def test_an_unknown_kind_is_refused_with_the_permitted_set(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)

    with pytest.raises(VqaprError, match=r"workspace\.remove\.unsupported_kind"):
        workspace.remove("nonsense", "x")
