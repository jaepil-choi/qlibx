"""Enforce the layering that docs/qlibx-architecture.md describes.

The dependency direction is the only thing that makes the layering real -- Python does
not enforce it, and a directory layout would not either. These tests turn the prose
guardrails in the architecture document into executable contracts.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

import qlibx

PACKAGE_ROOT = pathlib.Path(qlibx.__file__).parent
PACKAGE_NAME = "qlibx"

# Layer 0 is the kernel; a module may import only from strictly lower layers.
LAYERS: tuple[tuple[str, ...], ...] = (
    ("errors", "requirements", "serialization", "optimization", "orthogonality"),
    ("config", "documentation", "alpha", "strategy"),
    ("project",),
    (
        "catalog",
        "discovery",
        "registration",
        "artifacts",
        "research",
        "execution",
        "portfolio",
        "onboarding",
    ),
    ("profiles", "extensions", "ensemble", "reporting", "skill"),
    ("cli", "data", "agent", "__init__"),
)

LAYER_OF = {module: index for index, layer in enumerate(LAYERS) for module in layer}

# The vendored Qlib subtree is private: exactly one module may reach into it.
VENDOR_GATEWAY = "execution"


def _top_level(path: pathlib.Path) -> str:
    """Map any file in the package to the top-level module or package it belongs to."""
    relative = path.relative_to(PACKAGE_ROOT)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


def _import_graph() -> dict[str, set[str]]:
    """Resolve intra-package imports to top-level module granularity."""
    graph: dict[str, set[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "_vendor" in path.relative_to(PACKAGE_ROOT).parts[:1]:
            continue
        owner = _top_level(path)
        depth = len(path.relative_to(PACKAGE_ROOT).parts) - 1
        targets = graph.setdefault(owner, set())
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    # Relative import: level 1 stays inside the owning package unless it
                    # climbs past the package root.
                    if node.level > depth:
                        target = module.split(".")[0] if module else ""
                        if target:
                            targets.add(target)
                    continue
                if module.startswith(f"{PACKAGE_NAME}."):
                    targets.add(module.split(".")[1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(f"{PACKAGE_NAME}."):
                        targets.add(alias.name.split(".")[1])
        targets.discard(owner)
    return graph


GRAPH = _import_graph()


def test_every_module_is_assigned_to_a_layer() -> None:
    """A new module must be placed deliberately, not left outside the layering."""
    modules = {name for name in GRAPH if name != "__main__"}
    unassigned = sorted(modules - set(LAYER_OF) - {"_vendor"})
    assert not unassigned, f"modules missing from LAYERS: {unassigned}"
    stale = sorted(set(LAYER_OF) - modules)
    assert not stale, f"LAYERS names modules that no longer exist: {stale}"


def test_imports_only_go_downward() -> None:
    """A module may import from strictly lower layers only."""
    violations = []
    for source, targets in GRAPH.items():
        if source not in LAYER_OF:
            continue
        for target in sorted(targets):
            if target not in LAYER_OF:
                continue
            if LAYER_OF[target] >= LAYER_OF[source]:
                violations.append(
                    f"{source} (layer {LAYER_OF[source]}) imports "
                    f"{target} (layer {LAYER_OF[target]})"
                )
    assert not violations, "upward or sideways imports:\n  " + "\n  ".join(violations)


def test_kernel_has_no_intra_package_dependencies() -> None:
    """The kernel is the bottom: it must stay importable from anywhere."""
    for module in LAYERS[0]:
        assert not GRAPH.get(module), f"kernel module {module} imports {sorted(GRAPH[module])}"


def test_import_graph_is_acyclic() -> None:
    colors: dict[str, int] = {}
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        colors[node] = 1
        stack.append(node)
        for target in sorted(GRAPH.get(node, ())):
            if target not in GRAPH:
                continue
            if colors.get(target, 0) == 1:
                cycles.append([*stack[stack.index(target) :], target])
            elif colors.get(target, 0) == 0:
                visit(target)
        stack.pop()
        colors[node] = 2

    for module in sorted(GRAPH):
        if colors.get(module, 0) == 0:
            visit(module)
    assert not cycles, f"import cycles: {cycles}"


def test_vendored_qlib_has_exactly_one_gateway() -> None:
    """`_vendor/` is private; only the execution module may translate it."""
    importers = sorted(name for name, targets in GRAPH.items() if "_vendor" in targets)
    assert importers == [VENDOR_GATEWAY], (
        f"only {VENDOR_GATEWAY} may import _vendor, but {importers} do"
    )


def test_alpha_is_a_pure_domain_package() -> None:
    """Alpha must not learn about projects, catalogs, or storage."""
    assert GRAPH.get("alpha", set()) <= {"errors", "requirements"}, (
        "alpha must depend only on errors and requirements, "
        f"got {sorted(GRAPH.get('alpha', set()))}"
    )


@pytest.mark.parametrize(
    "module",
    [
        "alpha",
        "artifacts",
        "data",
        "ensemble",
        "execution",
        "extensions",
        "reporting",
        "requirements",
        "research",
    ],
)
def test_public_module_paths_stay_importable(module: str) -> None:
    """Installed examples import these paths directly; splitting a module must not break them."""
    __import__(f"{PACKAGE_NAME}.{module}")
