"""One author surface: the facade and `vqapr.authoring` name the same objects, and the three
scaffolds teach one grammar.

This began as the characterization suite for `docs/issues/archive/036` -- every assertion stated what the
package did on 2026-09-02 and named the milestone that would delete it. The milestones landed:
records `126` (the two lookbacks), `130` (the observing role), `131` (DataModel) and `132`
(StrategyModel); record `208` renamed that role `Compliance`.
What is left is the specification those tests were counting down to.

Design: `docs/design/the-panel-the-surface-and-the-run.md` §3 (명사 2 - 하나의 저자 표면).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import vqapr.authoring as authoring
import vqapr.public as public
from vqapr.extension.component import ComponentKind
from vqapr.extension.loading import load_compliance, load_data_model, load_strategy_model
from vqapr.extension.scaffold import render
from vqapr.public import register_compliance, register_data_model, register_strategy_model

# --------------------------------------------------------------------------------------
# One name, two classes.
# --------------------------------------------------------------------------------------

CONVERGED_NAMES = (
    "Compliance",
    "ComplianceFinding",
    "DataModel",
    "StrategyModel",
)
"""Names the facade and the authoring module export as ONE object.

The goal, asserted so that it cannot quietly come apart again. This list began as
`DIVERGENT_NAMES` -- five names exported by BOTH `vqapr.public` and `vqapr.authoring` as
different classes, with an inverse test asserting `is not` for each -- and every name crossed
over in the milestone that converged it: the two lookbacks in record `126`, the observing role
with its finding in `130` (`Compliance` since `208`), `DataModel` in `131`, and `StrategyModel`,
the last, in `132`. The inverse test went with the last entry.
"""


@pytest.mark.parametrize("name", CONVERGED_NAMES)
def test_the_facade_and_the_authoring_module_are_one_object(name: str) -> None:
    """An author who imports either name has written against the same contract."""
    assert getattr(public, name) is getattr(authoring, name), (
        f"public.{name} and authoring.{name} came apart again; that is the defect "
        f"docs/issues/archive/036 measured, not a refactor."
    )


# --------------------------------------------------------------------------------------
# Three scaffolds, one grammar.
# --------------------------------------------------------------------------------------

_SCAFFOLDED_KINDS = (
    ComponentKind.STRATEGY_MODEL,
    ComponentKind.DATA_MODEL,
    ComponentKind.COMPLIANCE,
)


def test_the_three_scaffolds_emit_one_import_line() -> None:
    """`from vqapr import authoring as va`, in every kind; nothing imports `vqapr.public`."""
    for kind in _SCAFFOLDED_KINDS:
        source = render(kind, "sample", dataset_id="px")
        assert "from vqapr import authoring as va\n" in source, kind
        assert "vqapr.public" not in source, kind


def test_the_three_scaffolds_declare_and_read_the_same_way() -> None:
    """`inputs()` is the one declaration and `.read(alias)` the one read verb, in every kind."""
    for kind in _SCAFFOLDED_KINDS:
        source = render(kind, "sample", dataset_id="px")
        assert "    def inputs(self):" in source, kind
        assert '.read("' in source, kind


def test_each_scaffold_differs_only_in_its_own_verb() -> None:
    verbs = {
        ComponentKind.STRATEGY_MODEL: ("def decide(self, call)",),
        ComponentKind.DATA_MODEL: ("def compute(self, context)",),
        ComponentKind.COMPLIANCE: ("def observe(self, call",),
    }
    for kind, expected in verbs.items():
        source = render(kind, "sample", dataset_id="px")
        for verb in expected:
            assert verb in source, (kind, verb)


# --------------------------------------------------------------------------------------
# All three authored kinds load.
# --------------------------------------------------------------------------------------

_AUTHORED_STRATEGY = '''\
from vqapr import authoring as va


class Model(va.StrategyModel):
    def inputs(self):
        return {}

    def decide(self, call):
        return va.Hold(reason="probe")
'''

_AUTHORED_DATA_MODEL = '''\
from vqapr import authoring as va


class Model(va.DataModel):
    def inputs(self):
        return {}

    def compute(self, call):
        return ()
'''

_AUTHORED_COMPLIANCE = '''\
from vqapr import authoring as va


class Model(va.Compliance):
    @property
    def compliance_id(self):
        return "authored-rule"

    def inputs(self):
        return {}

    def observe(self, call):
        raise NotImplementedError
'''


_WRONG_TYPE = "component.wrong_type"
"""The code both refusals carry today.

Asserted by name rather than by exception type alone: `VqaprError` covers every refusal this
package makes, so catching it without checking the code would let an unrelated failure -- a broken
fixture, a missing workspace -- read as "the surface is still divergent" and keep this file green
through the very change it exists to detect.
"""


def _written(project: Path, source: str) -> Path:
    path = project / "model.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_load_strategy_model_accepts_an_authored_strategy(tmp_path: Path) -> None:
    """The loader accepts the class the scaffold emits, with no adapter between them.

    Until record `132` `_adapt_authored_strategy` wrapped an authoring StrategyModel in an engine
    subclass so the engine could run it. There is one class now, so the loaded object IS the
    author's, and the two tests below hold for the same reason.
    """
    path = _written(tmp_path, _AUTHORED_STRATEGY)
    ref = register_strategy_model(tmp_path, "authored-strategy", path, "Model")

    loaded = load_strategy_model(ref, project_root=tmp_path)

    assert isinstance(loaded, authoring.StrategyModel)
    assert type(loaded).__name__ == "Model"


def test_load_data_model_accepts_an_authored_data_model(tmp_path: Path) -> None:
    """WAS: the same authoring contract a StrategyModel may use was refused for a DataModel.

    This was the half of `docs/issues/archive/036` that reading the issue does not reveal: the two
    surfaces were **differently reachable per kind**. A DataModel author had no choice to make,
    because `vqapr new datamodel` emitted the engine class since nothing else loaded. Record `131`
    made the class one; this asserts the inverse, including that a model declaring no reads loads.
    """
    path = _written(tmp_path, _AUTHORED_DATA_MODEL)
    ref = register_data_model(tmp_path, "authored-datamodel", path, "Model")

    loaded = load_data_model(ref, project_root=tmp_path)

    assert loaded.requirements() == ()


def test_load_compliance_accepts_an_authored_rule(tmp_path: Path) -> None:
    """WAS: the same authoring contract a StrategyModel may use was refused for the observing role.

    That asymmetry is what `docs/issues/archive/036` was about at the loader -- two surfaces, and which
    one worked depended on the kind. Record `130` made the observing contract one class, so the
    refusal has nothing left to refuse and this asserts the inverse.

    `tests/extension/test_all_four_doors.py` pins that all four extension points enter through one
    door; this pins that the door accepts the same thing for this one as for a strategy.
    """
    path = _written(tmp_path, _AUTHORED_COMPLIANCE)
    ref = register_compliance(tmp_path, "authored-rule", path, "Model")

    loaded = load_compliance(ref, project_root=tmp_path)

    assert loaded.compliance_id == "authored-rule"
