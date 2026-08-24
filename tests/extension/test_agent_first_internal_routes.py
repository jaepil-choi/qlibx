"""`vqapr._internal.extensions.{component,fingerprint,loading,registration}` — G002 relocation.

These tests pin the G002 contract for the internal-authority relocation:

* the old `vqapr.extension.*` modules and the new `vqapr._internal.extensions.*` modules expose
  the *same* objects (the adapters forward, they do not copy), so old and new callers share one
  authority;
* behaviour through the old public route is unchanged after the move;
* the internal modules never import back through the old `vqapr.extension.*` route, so the
  dependency direction is internal -> (nothing old), not old <-> internal.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import vqapr._internal.extensions.component as internal_component
import vqapr._internal.extensions.fingerprint as internal_fingerprint
import vqapr._internal.extensions.loading as internal_loading
import vqapr._internal.extensions.registration as internal_registration
import vqapr.extension.component as old_component
import vqapr.extension.fingerprint as old_fingerprint
import vqapr.extension.loading as old_loading
import vqapr.extension.registration as old_registration

_INTERNAL_MODULES = (
    internal_component,
    internal_fingerprint,
    internal_loading,
    internal_registration,
)


# --------------------------------------------------------------------------------------
# old and internal objects are identical authorities
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["ComponentKind", "ComponentRef"],
)
def test_component_adapter_forwards_the_same_objects(name: str) -> None:
    assert getattr(old_component, name) is getattr(internal_component, name)


def test_fingerprint_adapter_forwards_the_same_function() -> None:
    assert old_fingerprint.fingerprint_component is internal_fingerprint.fingerprint_component


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
    ],
)
def test_loading_adapter_forwards_the_same_objects(name: str) -> None:
    assert getattr(old_loading, name) is getattr(internal_loading, name)


@pytest.mark.parametrize(
    "name",
    [
        "register_data_model",
        "register_strategy_model",
        "register_constraint",
        "register_exchange",
    ],
)
def test_registration_adapter_forwards_the_same_objects(name: str) -> None:
    assert getattr(old_registration, name) is getattr(internal_registration, name)


# --------------------------------------------------------------------------------------
# behaviour is unchanged through the old public route
# --------------------------------------------------------------------------------------


def test_old_component_kind_still_constructs_a_ref(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("class Sample:\n    pass\n", encoding="utf-8")
    fingerprint = old_fingerprint.fingerprint_component(
        source, kind=old_component.ComponentKind.DATA_MODEL, object_name="Sample"
    )
    ref = old_component.ComponentRef.of(
        "sample",
        old_component.ComponentKind.DATA_MODEL,
        source,
        "Sample",
        fingerprint=fingerprint,
    )
    assert ref.kind is old_component.ComponentKind.DATA_MODEL
    assert ref.fingerprint == fingerprint

    # And the internal fingerprint function, given the same inputs, agrees exactly.
    internal_fingerprint_value = internal_fingerprint.fingerprint_component(
        source, kind=internal_component.ComponentKind.DATA_MODEL, object_name="Sample"
    )
    assert internal_fingerprint_value == fingerprint


def test_old_positional_arity_behaves_exactly_as_before() -> None:
    def two_required(a: int, b: int) -> None:
        return None

    def variadic(*args: int) -> None:
        return None

    assert old_loading.positional_arity(two_required) == (2, 2)
    assert old_loading.positional_arity(variadic) == (0, -1)
    assert old_loading.positional_arity(two_required) == internal_loading.positional_arity(
        two_required
    )


# --------------------------------------------------------------------------------------
# internal modules do not import old routes
# --------------------------------------------------------------------------------------


def _imported_module_names(module: object) -> set[str]:
    source_path = Path(module.__file__)  # type: ignore[arg-type]
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
    return names


@pytest.mark.parametrize("module", _INTERNAL_MODULES, ids=lambda m: m.__name__)
def test_internal_module_does_not_import_the_old_extension_route(module: object) -> None:
    imported = _imported_module_names(module)
    assert not any(
        name == "vqapr.extension" or name.startswith("vqapr.extension.") for name in imported
    )


def test_old_adapters_carry_no_duplicate_implementation_logic() -> None:
    """Each old module is a thin re-export: only imports, `__all__`, and a docstring."""
    for module, expected_names in (
        (old_component, {"ComponentKind", "ComponentRef"}),
        (old_fingerprint, {"fingerprint_component"}),
        (
            old_loading,
            {
                "SHIPPED_EXECUTION_PROFILES",
                "accepts_contract_call",
                "load_constraint",
                "load_data_model",
                "load_exchange",
                "load_strategy_model",
                "positional_arity",
            },
        ),
        (
            old_registration,
            {
                "register_constraint",
                "register_data_model",
                "register_exchange",
                "register_strategy_model",
            },
        ),
    ):
        source_path = Path(module.__file__)  # type: ignore[arg-type]
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        body = tree.body
        # First statement is the module docstring.
        assert isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
        remaining = body[1:]
        # Everything else is either an import or the `__all__` assignment: no function or class
        # definitions, i.e. no reimplemented logic.
        for node in remaining:
            assert isinstance(node, (ast.ImportFrom, ast.Import, ast.Assign)), (
                f"{module.__name__} contains non-forwarding statement: {ast.dump(node)}"
            )
            if isinstance(node, ast.Assign):
                assert [target.id for target in node.targets if isinstance(target, ast.Name)] == [
                    "__all__"
                ]
        assert set(module.__all__) == expected_names  # type: ignore[attr-defined]
