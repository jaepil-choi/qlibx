"""The edit loop: change one line, re-run, get a result whose digest moved. Two commands.

Issue 009's stated acceptance criterion for removing the component-fingerprint refusals, written
as a test because the criterion is behavioural: *"change one line of a registered strategy, run,
and get a result with a new `source_digest` -- in TWO commands, with no new component id, no new
config binding and no spec edit."*

Before the change this was impossible in either direction. `loading.py` refused the edited source
with `component.load.fingerprint_drift` and named "re-register the component" as the repair;
`register_component` refused exactly that and demanded a new `component_id`. The refusals pointed
at each other, which `docs/implementations/057` names as worse than a generic error.
"""

from __future__ import annotations

from pathlib import Path

from vqapr.extension.component import ComponentKind
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.extension.component import ComponentRef
from vqapr.project.store import Workspace

SOURCE = "class Model:\n    factor = {value}\n"


def _ref(path: Path) -> ComponentRef:
    return ComponentRef(
        component_id="mom",
        kind=ComponentKind.STRATEGY_MODEL,
        path=path,
        object_name="Model",
        config={},
        fingerprint=fingerprint_component(
            path, kind=ComponentKind.STRATEGY_MODEL, object_name="Model", config={}
        ),
    )


def test_one_edit_one_reregistration_and_the_id_survives(tmp_path: Path) -> None:
    """Step one of the loop, which used to be a dead end."""
    workspace = Workspace.create(tmp_path)
    source = tmp_path / "model.py"
    source.write_text(SOURCE.format(value=1), encoding="utf-8")
    with Workspace.transaction(workspace) as t:
        t.register_component(_ref(source))
    before = workspace.component("mom").fingerprint

    # The edit. One line.
    source.write_text(SOURCE.format(value=2), encoding="utf-8")
    with Workspace.transaction(workspace) as t:
        t.register_component(_ref(source))

    after = workspace.component("mom")
    assert after.fingerprint != before, "the edit must move the registered fingerprint"
    assert str(after.component_id) == "mom", "and it must keep the id it already had"
    assert len(workspace.components) == 1, (
        "one strategy must not accumulate mom, mom-eb04..., mom-91c7... across its edits"
    )


def test_the_as_loaded_digest_follows_the_source_not_the_registration(tmp_path: Path) -> None:
    """Why removing the gate does not cost provenance.

    The fingerprint is still computed on every load; what changed is that it reports instead of
    refusing. A run record stamps the digest of what ACTUALLY loaded, so an edited-but-not-
    re-registered component is still recorded honestly rather than under a stale digest.
    """
    from vqapr.extension.loading import as_loaded_fingerprint

    workspace = Workspace.create(tmp_path)
    source = tmp_path / "model.py"
    source.write_text(SOURCE.format(value=1), encoding="utf-8")
    ref = _ref(source)
    with Workspace.transaction(workspace) as t:
        t.register_component(ref)

    assert as_loaded_fingerprint(ref) == ref.fingerprint, "unedited: the two agree"

    source.write_text(SOURCE.format(value=2), encoding="utf-8")
    drifted = as_loaded_fingerprint(ref)

    assert drifted != ref.fingerprint, (
        "edited: the as-loaded digest must describe the bytes on disk, not the registration"
    )


def test_the_overfitting_signal_is_countable(tmp_path: Path) -> None:
    """What keeping one id buys, stated as the thing it makes possible.

    "This strategy ran 47 times across 12 distinct fingerprints" is a direct overfitting tell.
    Forcing a new component_id per edit scatters that history across twelve ids where nothing
    counts it; keeping the id makes the fingerprints countable under one name.
    """
    workspace = Workspace.create(tmp_path)
    source = tmp_path / "model.py"
    seen: set[str] = set()

    for value in range(1, 6):
        source.write_text(SOURCE.format(value=value), encoding="utf-8")
        ref = _ref(source)
        with Workspace.transaction(workspace) as t:
            t.register_component(ref)
        seen.add(ref.fingerprint)

    assert len(seen) == 5, "five edits must produce five distinct fingerprints"
    assert len(workspace.components) == 1, "under exactly one component id"
