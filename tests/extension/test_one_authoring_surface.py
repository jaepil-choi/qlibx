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

from pathlib import Path

import pytest

import vqapr.authoring as authoring
import vqapr.public as public
from vqapr.extension.loading import load_constraint, load_data_model, load_strategy_model
from vqapr.public import register_constraint, register_data_model, register_strategy_model

# --------------------------------------------------------------------------------------
# One name, two classes.
# --------------------------------------------------------------------------------------

CONVERGED_NAMES = (
    "Constraint",
    "ConstraintBounds",
    "ConstraintFinding",
    "DataModel",
    "StrategyModel",
)
"""Names the facade and the authoring module export as ONE object.

The goal, asserted so that it cannot quietly come apart again. This list began as
`DIVERGENT_NAMES` -- five names exported by BOTH `vqapr.public` and `vqapr.authoring` as
different classes, with an inverse test asserting `is not` for each -- and every name crossed
over in the milestone that converged it: the two lookbacks in record `126`, `Constraint` with
`ConstraintBounds` and `ConstraintFinding` in `130`, `DataModel` in `131`, and `StrategyModel`,
the last, in `132`. The inverse test went with the last entry.
"""


@pytest.mark.parametrize("name", CONVERGED_NAMES)
def test_the_facade_and_the_authoring_module_are_one_object(name: str) -> None:
    """An author who imports either name has written against the same contract."""
    assert getattr(public, name) is getattr(authoring, name), (
        f"public.{name} and authoring.{name} came apart again; that is the defect "
        f"docs/issues/036 measured, not a refactor."
    )


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

    This was the half of `docs/issues/036` that reading the issue does not reveal: the two
    surfaces were **differently reachable per kind**. A DataModel author had no choice to make,
    because `vqapr new datamodel` emitted the engine class since nothing else loaded. Record `131`
    made the class one; this asserts the inverse, including that a model declaring no reads loads.
    """
    path = _written(tmp_path, _AUTHORED_DATA_MODEL)
    ref = register_data_model(tmp_path, "authored-datamodel", path, "Model")

    loaded = load_data_model(ref, project_root=tmp_path)

    assert loaded.requirements() == ()


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
