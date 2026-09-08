"""`vqapr.extension.*` holds the extension authorities, and behaves as it always did.

**Replaces `test_agent_first_internal_routes.py`, whose premise is discharged.** That file existed
to prove four things about a forwarding shim: that `vqapr.extension.X` handed back the *same object*
as `vqapr._internal.extensions.X`, and that the shim carried no implementation of its own. Record
`110` moved the implementation to the shim's path and deleted `_internal/extensions/`, so there is
no longer a second module to forward to, and "carries no implementation" is now exactly backwards --
these modules ARE the implementation.

What was worth keeping is the part that was never about the shim: the **behaviour** those tests
pinned. `ComponentKind` still constructs a ref, `positional_arity` still answers as before, and the
names callers import still resolve. Those assertions survive here, against the promoted modules,
because a move that quietly changed behaviour would otherwise be invisible.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import vqapr.extension.component as component
import vqapr.extension.fingerprint as fingerprint
import vqapr.extension.loading as loading
import vqapr.extension.registration as registration
import vqapr.public as public


@pytest.mark.parametrize(
    "name",
    ["ComponentKind", "ComponentRef"],
)
def test_the_component_names_callers_import_still_resolve(name: str) -> None:
    """Every caller in `src/` and every emitted scaffold reaches these by name."""
    assert hasattr(component, name)


@pytest.mark.parametrize(
    "name",
    [
        "load_data_model",
        "load_strategy_model",
        "load_constraint",
        "load_exchange",
        "positional_arity",
        "accepts_contract_call",
        "SHIPPED_EXECUTION_PROFILES",
        "as_loaded_fingerprint",
    ],
)
def test_the_loading_names_callers_import_still_resolve(name: str) -> None:
    assert hasattr(loading, name)


def test_the_facade_and_the_module_agree_on_one_object(tmp_path: Path) -> None:
    """`vqapr.public` re-exports these, and the two paths must not become two objects.

    This is the assertion the old file made about the shim, moved to the boundary where it still
    means something: an emitted scaffold writes `from vqapr.public import ...` while `src/` reaches
    `vqapr.extension.*`, so a divergence would be two classes that compare unequal.
    """
    assert public.ComponentKind is component.ComponentKind
    assert public.ComponentRef is component.ComponentRef


def test_a_component_ref_still_constructs_and_fingerprints(tmp_path: Path) -> None:
    """Behaviour pinned by the retired file, kept because a move must not change it."""
    source = tmp_path / "model.py"
    source.write_text("class M:\n    pass\n", encoding="utf-8")

    digest = fingerprint.fingerprint_component(
        source, kind=component.ComponentKind.DATA_MODEL, object_name="M", config={}
    )
    ref = component.ComponentRef.of(
        "m", component.ComponentKind.DATA_MODEL, source, "M", fingerprint=digest
    )

    assert ref.kind is component.ComponentKind.DATA_MODEL
    assert ref.fingerprint == digest
    assert len(digest) == 64


def test_positional_arity_still_answers_as_before() -> None:
    """A behavioural pin from the retired file, unchanged by the relocation.

    It returns a `(minimum, maximum)` pair rather than a single count, which is the distinction a
    contract check needs: a callback taking one required argument and one optional is callable
    both ways, and collapsing that to one number would lose the tolerance.
    """

    def two(a: int, b: int) -> int:
        return a + b

    def one_with_default(a: int, b: int = 1) -> int:
        return a + b

    assert loading.positional_arity(two) == (2, 2)
    assert loading.positional_arity(one_with_default) == (1, 2)


def test_the_modules_define_rather_than_re_export() -> None:
    """The inverse of the assertion the retired file made.

    It asserted these files contained no implementation, because they were shims. They are the
    implementation now, so a file that shrinks back to pure forwarding means the move was undone.
    """
    for module in (component, fingerprint, loading, registration):
        members = [
            name
            for name, value in vars(module).items()
            if not name.startswith("_")
            and (inspect.isclass(value) or inspect.isfunction(value))
            and getattr(value, "__module__", None) == module.__name__
        ]
        assert members, (
            f"{module.__name__} defines nothing of its own and is forwarding again; record 110 "
            "moved the implementation here so the temporary file could stop existing"
        )
