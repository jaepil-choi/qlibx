"""Turning an authored class into the engine's registered component.

The public declaration carries a class; the engine wants a source location, an object
name and a fingerprint. These tests pin that recovery, and pin the refusals - a class the
framework cannot re-read later is one whose fingerprint cannot be re-verified before a
callback, which is the drift this identity contract exists to prevent.
"""

from __future__ import annotations

import sys
import textwrap

import pytest

from vqapr._internal.registration_bridge import component_ref_for, extension_kind_for
from vqapr.authoring import Constraint
from vqapr.extension.identity import ExtensionKind

MODULE_SOURCE = textwrap.dedent(
    '''
    from decimal import Decimal

    from vqapr.authoring import (
        Constraint,
        ConstraintBounds,
        ConstraintFinding,
        DataModel,
        Output,
        StrategyModel,
        StrategyResult,
        Hold,
    )


    class CapWeights(Constraint):
        def inputs(self):
            return {}

        def project(self, call):
            return ConstraintBounds(
                lower_weights={i: Decimal(0) for i in call.instruments},
                upper_weights={i: Decimal("0.5") for i in call.instruments},
            )

        def validate(self, decision, bounds):
            return ConstraintFinding(
                passed=True, measured=Decimal(0), bound=Decimal("0.5"),
                excess=Decimal(0), details={},
            )

        def monitor(self, call, bounds):
            return ConstraintFinding(
                passed=True, measured=Decimal(0), bound=Decimal("0.5"),
                excess=Decimal(0), details={},
            )


    class Feature(DataModel):
        def inputs(self):
            return {}

        def output(self):
            return Output(semantic_fields=("signal",))

        def compute(self, call):
            return ()


    class Decider(StrategyModel):
        def decide(self, call):
            return StrategyResult(
                decision=Hold(reason="idle"), next_state=None, diagnostics={}
            )
    '''
)


@pytest.fixture
def authored(tmp_path):
    """A real module on disk: the framework must be able to re-read its bytes."""
    module_path = tmp_path / "authored_extensions.py"
    module_path.write_text(MODULE_SOURCE, encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        import authored_extensions

        yield authored_extensions
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("authored_extensions", None)


def test_each_authoring_contract_classifies_to_its_kind(authored):
    assert extension_kind_for(authored.CapWeights) is ExtensionKind.CONSTRAINT
    assert extension_kind_for(authored.Feature) is ExtensionKind.DATA_MODEL
    assert extension_kind_for(authored.Decider) is ExtensionKind.STRATEGY_MODEL


def test_a_class_implementing_no_contract_is_refused():
    class Unrelated:
        pass

    with pytest.raises(TypeError, match="implements no authoring contract"):
        extension_kind_for(Unrelated)


def test_a_component_ref_recovers_the_class_location(authored):
    reference = component_ref_for(
        authored.CapWeights, component_id="cap-weights", config={}
    )
    assert reference.component_id == "cap-weights"
    assert reference.object_name == "CapWeights"
    assert str(reference.kind) == "constraint"


def test_the_fingerprint_is_a_full_digest_of_real_source(authored):
    reference = component_ref_for(authored.CapWeights, component_id="cap", config={})
    assert len(reference.fingerprint) == 64
    assert reference.fingerprint == reference.fingerprint.lower()
    int(reference.fingerprint, 16)  # raises if it is not hex


def test_config_changes_the_fingerprint(authored):
    plain = component_ref_for(authored.CapWeights, component_id="cap", config={})
    tuned = component_ref_for(
        authored.CapWeights, component_id="cap", config={"cap": "0.25"}
    )
    assert plain.fingerprint != tuned.fingerprint


def test_the_component_id_does_not_change_the_fingerprint(authored):
    """Identity comes from source and config, never from what a caller named it."""
    first = component_ref_for(authored.CapWeights, component_id="one", config={})
    second = component_ref_for(authored.CapWeights, component_id="two", config={})
    assert first.fingerprint == second.fingerprint


def test_two_different_classes_fingerprint_differently(authored):
    constraint = component_ref_for(authored.CapWeights, component_id="c", config={})
    model = component_ref_for(authored.Feature, component_id="f", config={})
    assert constraint.fingerprint != model.fingerprint


# --- refusals ------------------------------------------------------------------------------


def test_a_class_defined_inside_a_function_is_refused():
    """No stable import location means the source cannot be re-read before a callback."""

    def make():
        class Nested(Constraint):
            def inputs(self):
                return {}

            def project(self, call): ...

            def validate(self, decision, bounds): ...

            def monitor(self, call, bounds): ...

        return Nested

    with pytest.raises(ValueError, match="defined inside another scope"):
        component_ref_for(make(), component_id="nested")


def test_a_non_class_is_refused():
    with pytest.raises(TypeError, match="cls must be a class"):
        component_ref_for("CapWeights", component_id="cap")


def test_an_empty_component_id_is_refused(authored):
    with pytest.raises(ValueError, match="component_id must be a non-empty string"):
        component_ref_for(authored.CapWeights, component_id="")
