"""The gap `docs/issues/036` measured, asserted, so that closing it is visible.

**Every assertion in this file states what the package does TODAY, and today is wrong.** The owner
ruled CONVERGE on 2026-08-31: a DataModel and a StrategyModel *"should be substantially similar to
use, and the size of the current difference is itself the defect."* `src/vqapr/agent/skill/
SKILL.md:73` already claims *"Both are authored the same way"*, and the product is what has to be
made to mean it.

So this is a characterization suite, not a specification. It exists because the convergence touches
`authoring.py`, `public.py`, `models/`, `extension/loading.py`, `flow/materialize.py` and two
`_internal` bridges, and a change that big needs the before-state written down where a diff can
show it moving. `tests/characterization/refusal_codes.baseline.json` is the same idea for refusals.

**Each test names the milestone that deletes it.** A test here that starts failing is not a
regression -- it is the milestone landing, and the test goes with it. Do not "fix" one of these by
making the assertion true again; that would be re-opening 036.

Design: `docs/design/the-panel-the-surface-and-the-run.md` §3 (명사 2 - 하나의 저자 표면).
Plan: `.agent/plans/active/one-authoring-surface.md`, M1.
"""

from __future__ import annotations

from abc import ABC
from pathlib import Path

import pytest

import vqapr.authoring as authoring
import vqapr.public as public
from vqapr.domain.errors import VqaprError
from vqapr.extension.loading import load_constraint, load_data_model, load_strategy_model
from vqapr.public import register_constraint, register_data_model, register_strategy_model

# --------------------------------------------------------------------------------------
# One name, two classes.
# --------------------------------------------------------------------------------------

DIVERGENT_NAMES = ("DataModel", "StrategyModel")
"""Names exported by BOTH `vqapr.public` and `vqapr.authoring` as different objects.

`tests/extension/test_the_extension_surface_is_the_implementation.py::
test_the_facade_and_the_module_agree_on_one_object` asserts the opposite for
`ComponentKind`/`ComponentRef`/`fingerprint_component` -- the facade and the module are one object
there, and that is the shape this list is supposed to reach.

**`CalendarLookback` and `RowsLookback` were here and are gone**, which is this file working as
intended. Record `126` made each of them one class re-exported under both names, so the assertion
below stopped being true of them and they left the list in the same commit that closed them.
**`Constraint` left the same way** in record `130`, together with `ConstraintBounds` and
`ConstraintFinding`, which were never on this list because nothing had measured them. Two of the
original five remain, and the inverse assertion below is what stands for the three that went.
"""


CONVERGED_NAMES = ("Constraint", "ConstraintBounds", "ConstraintFinding")
"""Names the facade and the authoring module now export as ONE object.

The goal, asserted so that it cannot quietly come apart again. Each name arrives here by leaving
`DIVERGENT_NAMES` in the milestone that converged it.
"""


@pytest.mark.parametrize("name", CONVERGED_NAMES)
def test_the_facade_and_the_authoring_module_are_one_object(name: str) -> None:
    """An author who imports either name has written against the same contract."""
    assert getattr(public, name) is getattr(authoring, name), (
        f"public.{name} and authoring.{name} came apart again; that is the defect "
        f"docs/issues/036 measured, not a refactor."
    )


@pytest.mark.parametrize("name", DIVERGENT_NAMES)
def test_the_facade_and_the_authoring_module_are_two_objects(name: str) -> None:
    """TODAY: `public.X` and `authoring.X` are different classes under one name.

    An author who writes `from vqapr.public import DataModel` and an author who writes
    `from vqapr import authoring as va` and subclasses `va.DataModel` have written against two
    different contracts, and nothing in either import line says so. `docs/issues/036`:
    *"Nothing says which is canonical."*

    Deleted by: M6 (`DataModel`, `StrategyModel`, `Constraint`) and record `126` (the two
    lookbacks). At that point the parametrized inverse of this test is the assertion that stands.
    """
    facade = getattr(public, name)
    authored = getattr(authoring, name)

    assert facade is not authored, (
        f"public.{name} and authoring.{name} are now one object. That is the goal, not a "
        f"regression: delete this parametrization entry and assert `is` instead."
    )


def test_the_two_authored_kinds_share_no_base() -> None:
    """TODAY: on the authoring side there is no `Model`, so nothing is shared by construction.

    The engine side HAS the common base (`models/model.py`), which is what makes this asymmetry
    easy to miss when reading `src/` -- the base exists, just not on the surface an author
    inherits from. The strategy scaffold emits `va.StrategyModel` and the datamodel scaffold emits
    the engine's `DataModel`, so the two kinds an author actually writes share no ancestor at all.

    Deleted by: M2.
    """
    shared = set(authoring.DataModel.__mro__) & set(authoring.StrategyModel.__mro__)

    # `ABC` and `object` are shared by every abstract class in Python and say nothing about this
    # package. What M2 adds is a base of vqapr's own, and that is what this measures.
    assert shared == {ABC, object}, (
        f"authoring.DataModel and authoring.StrategyModel now share {shared - {ABC, object}}; if "
        f"that is `authoring.Model`, M2 has landed and this test goes with it."
    )


# --------------------------------------------------------------------------------------
# One kind is adapted inward; two are refused.
# --------------------------------------------------------------------------------------

_AUTHORED_STRATEGY = '''\
from vqapr import authoring as va


class Model(va.StrategyModel):
    def inputs(self):
        return {}

    def decide(self, call):
        return va.StrategyResult(decision=va.Hold(reason="probe"))
'''

_AUTHORED_DATA_MODEL = '''\
from vqapr import authoring as va


class Model(va.DataModel):
    def inputs(self):
        return {}

    def output(self):
        return va.Output(semantic_fields=("value",))

    def compute(self, call):
        return ()
'''

_AUTHORED_CONSTRAINT = '''\
from vqapr import authoring as va


class Model(va.Constraint):
    @property
    def constraint_id(self):
        return "authored-constraint"

    def inputs(self):
        return {}

    def project(self, call):
        return va.ConstraintBounds(
            lower_weights={i: 0 for i in call.instruments},
            upper_weights={i: 1 for i in call.instruments},
        )

    def monitor(self, call, account, bounds):
        raise NotImplementedError
'''


_WRONG_TYPE = "component.load.wrong_type"
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


def test_load_strategy_model_adapts_an_authored_strategy_inward(tmp_path: Path) -> None:
    """TODAY, and this one is the TARGET shape rather than the defect.

    `_adapt_authored_strategy` (`extension/loading.py`) wraps an authoring StrategyModel so the
    engine can run it, and its own docstring gives the reason the other two loaders should do the
    same: refusing it *"would mean a model that runs perfectly through `Project.simulate` cannot be
    registered by the CLI that exists to register it."*

    Kept after convergence, as the regression surface for M4/M5. It is here so the two tests below
    read as an inconsistency rather than as a policy.
    """
    path = _written(tmp_path, _AUTHORED_STRATEGY)
    ref = register_strategy_model(tmp_path, "authored-strategy", path, "Model")

    loaded = load_strategy_model(ref, project_root=tmp_path)

    assert loaded is not None


def test_load_data_model_refuses_an_authored_data_model(tmp_path: Path) -> None:
    """TODAY: the same authoring contract that a StrategyModel may use is refused for a DataModel.

    This is the half of `docs/issues/036` that reading the issue does not reveal: the two surfaces
    are not merely both present and undocumented, they are **differently reachable per kind**. A
    DataModel author has no choice to make -- `vqapr new datamodel` emits `from vqapr.public import
    DataModel` because nothing else loads.

    Deleted by: M4.
    """
    path = _written(tmp_path, _AUTHORED_DATA_MODEL)

    # The refusal lands at REGISTRATION, because registration runs conformance, which calls the
    # same `load_*` the run would (`testing/conformance/runner.py`). One door, one verdict -- so
    # an authored DataModel is unreachable from `vqapr register` onward, not merely at run time.
    with pytest.raises(VqaprError) as refusal:
        ref = register_data_model(tmp_path, "authored-datamodel", path, "Model")
        load_data_model(ref, project_root=tmp_path)

    assert _WRONG_TYPE in str(refusal.value), (
        f"expected {_WRONG_TYPE}; an authored DataModel that now loads means M4 has landed and "
        f"this test goes with it. Got: {refusal.value}"
    )


def test_load_constraint_accepts_an_authored_constraint(tmp_path: Path) -> None:
    """WAS: the same authoring contract a StrategyModel may use was refused for a Constraint.

    That asymmetry is what `docs/issues/036` was about at the loader -- two surfaces, and which
    one worked depended on the kind. Record `130` made the constraint contract one class, so the
    refusal has nothing left to refuse and this asserts the inverse.

    `tests/extension/test_all_four_doors.py` pins that all four extension points enter through one
    door; this pins that the door accepts the same thing for this one as for a strategy.
    """
    path = _written(tmp_path, _AUTHORED_CONSTRAINT)
    ref = register_constraint(tmp_path, "authored-constraint", path, "Model")

    loaded = load_constraint(ref, project_root=tmp_path)

    assert loaded.constraint_id == "authored-constraint"
