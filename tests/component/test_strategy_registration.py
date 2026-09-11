"""Registering a Strategy must prove its declaration before a run depends on it."""

from __future__ import annotations

from pathlib import Path

import pytest

from vqapr.component.scaffold import render
from vqapr.domain.errors import VqaprError
from vqapr.domain.wiring import Role
from vqapr.workspace.registration import register_strategy_model

_HEAD = """from __future__ import annotations

from vqapr.data.lookback import RowsLookback
from vqapr.public import DataRequirement
from vqapr.authoring import Hold
from vqapr.authoring import StrategyModel


class S(StrategyModel):
    def requirements(self):
        return (
            DataRequirement.of('px', 'close', lookback=RowsLookback(rows=6)),
        )
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / f"{name}.py"
    path.write_text(_HEAD + body, encoding="utf-8")
    return path


def _codes(error: VqaprError) -> set[str]:
    return {failure.code for failure in error.failures}


def test_a_syntax_error_is_refused_at_registration(tmp_path: Path) -> None:
    """A broken file must fail here, not at the first callback of a long run."""
    path = tmp_path / "broken.py"
    path.write_text("class S:\n    def __init__(self)\n        pass\n", encoding="utf-8")
    with pytest.raises(VqaprError) as raised:
        register_strategy_model(tmp_path, "broken", path, "S")
    assert _codes(raised.value) == {"component.construction_failed"}
    assert "SyntaxError" in (raised.value.failures[0].observed or "")


def test_a_source_path_that_is_not_there_is_a_404_not_a_503(tmp_path: Path) -> None:
    """A path that resolved wrongly never clears by retrying (`docs/issues/094`).

    The skills tell an agent that 503 means "retry the same command unchanged"; this refusal used
    to be a 503 whose own `retry_precondition` named an edit. It is `Status.MISSING` now -- "the
    path it names is not there" -- and the fix says how a relative `path` resolves, which is the
    mistake that produced the report.
    """
    with pytest.raises(VqaprError) as raised:
        register_strategy_model(tmp_path, "gone", tmp_path / "declarations" / "gone.py", "S")
    (failure,) = raised.value.failures
    assert failure.code == "component.source_missing"
    assert int(failure.status) == 404
    assert "declaration file's own directory" in failure.fix
    assert raised.value.retry_precondition == "correct the component's `path`, then retry"


def test_an_object_outside_the_contract_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "plain.py"
    path.write_text("class S:\n    pass\n", encoding="utf-8")
    with pytest.raises(VqaprError) as raised:
        register_strategy_model(tmp_path, "plain", path, "S")
    assert _codes(raised.value) == {"component.wrong_type"}


def test_a_renamed_callback_parameter_is_accepted(tmp_path: Path) -> None:
    """Flow calls the callback positionally, so arity is the contract and spelling is not.

    This once asserted the opposite. It was wrong: `decide(self, ctx)` receives exactly
    the call `decide(self, context)` receives, and refusing it punished a legal rename
    while `wrong_return`-shaped mistakes passed. The check now measures what Flow actually does.
    """
    path = _write(
        tmp_path,
        "renamed",
        "    def decide(self, ctx):\n        return Hold(reason='x')\n",
    )

    register_strategy_model(tmp_path, "renamed", path, "S")


def test_an_extra_required_parameter_is_refused(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "extra",
        "    def decide(self, context, extra):\n        return Hold(reason='x')\n",
    )
    with pytest.raises(VqaprError) as raised:
        register_strategy_model(tmp_path, "extra", path, "S")
    assert _codes(raised.value) == {"component.signature_invalid"}


def test_an_unannotated_callback_is_accepted(tmp_path: Path) -> None:
    """Annotations are not the contract; the overwhelming convention omits them."""
    path = _write(
        tmp_path,
        "bare",
        "    def decide(self, context):\n        return Hold(reason='x')\n",
    )
    ref = register_strategy_model(tmp_path, "bare", path, "S")
    assert ref.kind is Role.STRATEGY_MODEL


def test_a_narrower_return_annotation_is_accepted(tmp_path: Path) -> None:
    """A Strategy that always declines may say so; that is more precise, not wrong."""
    path = _write(
        tmp_path,
        "narrow",
        "    def decide(self, context) -> Hold:\n"
        "        return Hold(reason='x')\n",
    )
    assert register_strategy_model(tmp_path, "narrow", path, "S") is not None


def test_a_requirements_declaration_of_the_wrong_shape_is_refused(tmp_path: Path) -> None:
    """Declaring requirements is optional, but declaring them wrongly is not."""
    path = tmp_path / "badreq.py"
    path.write_text(
        "from vqapr.authoring import Hold\n"
        "from vqapr.authoring import StrategyModel\n\n\n"
        "class S(StrategyModel):\n"
        "    def requirements(self):\n"
        "        return ['not-a-requirement']\n\n"
        "    def decide(self, context):\n"
        "        return Hold(reason='x')\n",
        encoding="utf-8",
    )
    with pytest.raises(VqaprError) as raised:
        register_strategy_model(tmp_path, "badreq", path, "S")
    assert _codes(raised.value) == {"component.requirements_invalid"}


@pytest.mark.parametrize(
    ("kind", "object_name"),
    [(Role.STRATEGY_MODEL, "Sample"), (Role.DATA_MODEL, "Sample")],
)
def test_a_generated_template_registers_unedited(
    tmp_path: Path, kind: Role, object_name: str
) -> None:
    """`new` must emit something that already runs, not a stub that raises."""
    source = render(kind, "sample", dataset_id="px")
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    if kind is Role.STRATEGY_MODEL:
        assert register_strategy_model(tmp_path, "sample", path, object_name) is not None
    else:
        from vqapr.workspace.registration import register_data_model

        assert register_data_model(tmp_path, "sample", path, object_name) is not None
