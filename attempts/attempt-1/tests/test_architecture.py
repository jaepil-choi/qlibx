"""Enforce the layering that docs/qlibx-architecture.md describes.

The dependency direction is the only thing that makes the layering real -- Python does
not enforce it, and a directory layout would not either. These tests turn the prose
guardrails in the architecture document into executable contracts.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

import qlibx

PACKAGE_ROOT = pathlib.Path(qlibx.__file__).parent
PACKAGE_NAME = "qlibx"

# Layer 0 is the kernel; a module may import only from strictly lower layers.
LAYERS: tuple[tuple[str, ...], ...] = (
    ("errors", "requirements", "serialization", "optimization", "orthogonality"),
    ("config", "documentation", "alpha", "strategy", "stage_recovery"),
    ("project",),
    ("run_catalog",),
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
    (
        "profiles",
        "extensions",
        "ensemble",
        "reporting",
        "skill",
        "storage",
        "strategy_manifest",
    ),
    ("cli", "data", "agent"),
    # The package facade sits above the entrypoints it re-exports.
    ("__init__",),
)

LAYER_OF = {module: index for index, layer in enumerate(LAYERS) for module in layer}

# `_vendor/` is private. Two modules translate it, and they translate disjoint halves:
# `run_catalog` reads stored runs, `execution` runs them. Keeping the reader separate is
# what stops a presentation-only module from depending on the Qlib runtime.
VENDOR_GATEWAYS = ("execution", "run_catalog")

# `_vendor/` is vendored third-party code. It may lean on the kernel, but nothing above
# it -- an upward import would make the subtree part of the layering it claims to sit
# outside of, and would let a cycle form where the gateway test cannot see it.
VENDOR_ALLOWED_DEPENDENCIES = frozenset(LAYERS[0])


def _top_level(path: pathlib.Path) -> str:
    """Map any file in the package to the top-level module or package it belongs to."""
    relative = path.relative_to(PACKAGE_ROOT)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


def _import_graph() -> dict[str, set[str]]:
    """Resolve intra-package imports to top-level module granularity.

    Every spelling of an intra-package import has to land here, including the bare
    ``from qlibx import x`` form and the vendored subtree. A parser that silently drops
    one of them does not weaken the report -- it makes every test below vacuous for that
    spelling, which is exactly how the layering claims drifted from the code before.
    """
    graph: dict[str, set[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
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
                        else:
                            # `from .. import x` names the modules directly.
                            targets.update(alias.name.split(".")[0] for alias in node.names)
                    continue
                if module == PACKAGE_NAME:
                    # `from qlibx import catalog` imports modules, not attributes of a
                    # module, so each alias names an intra-package dependency.
                    targets.update(alias.name.split(".")[0] for alias in node.names)
                elif module.startswith(f"{PACKAGE_NAME}."):
                    targets.add(module.split(".")[1])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(f"{PACKAGE_NAME}."):
                        targets.add(alias.name.split(".")[1])
        targets.discard(owner)
    return graph


GRAPH = _import_graph()
# The facade resolves its submodules lazily, so its dependencies live in a declared map
# rather than in import statements. Fold them in: a lazy import is still a dependency,
# and leaving it out of the graph would recreate the blind spot this parser just closed.
GRAPH["__init__"] = GRAPH.get("__init__", set()) | set(qlibx._SUBMODULES)


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


def test_vendored_qlib_is_reached_only_through_its_gateways() -> None:
    """`_vendor/` is private; only the declared gateway modules may translate it."""
    importers = sorted(name for name, targets in GRAPH.items() if "_vendor" in targets)
    assert importers == sorted(VENDOR_GATEWAYS), (
        f"only {sorted(VENDOR_GATEWAYS)} may import _vendor, but {importers} do"
    )


def test_reporting_does_not_depend_on_the_execution_engine() -> None:
    """Composing a report must not drag in the runtime that produced the run.

    `reporting` reads stored artifacts and renders them; the PRD forbids it from
    re-running a strategy, optimizer, or backtest. Reaching the run catalog through
    `execution` made the Qlib runtime a transitive import of a module that never uses it.
    """
    assert "execution" not in GRAPH.get("reporting", set()), (
        "reporting must reach stored runs through run_catalog, not execution"
    )


def test_vendored_qlib_depends_only_on_the_kernel() -> None:
    """The gateway rule is only half the boundary: `_vendor/` must not import upward.

    Checking who imports `_vendor` says nothing about what `_vendor` imports, so without
    this the subtree could quietly acquire a dependency on any layer -- including one
    that closes a cycle back through the gateway.
    """
    upward = sorted(GRAPH.get("_vendor", set()) - VENDOR_ALLOWED_DEPENDENCIES)
    assert not upward, (
        f"_vendor may import only kernel modules {sorted(VENDOR_ALLOWED_DEPENDENCIES)}, "
        f"but also imports {upward}"
    )


def test_the_core_cannot_reach_a_repair_path() -> None:
    """PRD 5.6 gives the repair to the skill, so the core must not be able to serve one.

    `documentation` backs `qlibx docs` and `qlibx errors <stage>`. If `stage_recovery` were
    reachable from there, the core would be prescribing a repair again -- just through an
    import instead of through an `expected` string, where the existing wording test cannot
    see it. Reachability, not the direct import, is the property: one hop of indirection
    would otherwise be enough to lose it.
    """
    reachable: set[str] = set()
    frontier = ["documentation", "errors"]
    while frontier:
        module = frontier.pop()
        for target in GRAPH.get(module, ()):
            if target not in reachable:
                reachable.add(target)
                frontier.append(target)
    assert "stage_recovery" not in reachable, (
        "the core documentation surface can reach the skill's repair paths through "
        f"{sorted(reachable)}"
    )


def test_alpha_is_a_pure_domain_package() -> None:
    """Alpha must not learn about projects, catalogs, or storage."""
    assert GRAPH.get("alpha", set()) <= {"errors", "requirements"}, (
        "alpha must depend only on errors and requirements, "
        f"got {sorted(GRAPH.get('alpha', set()))}"
    )


def test_facade_exports_exactly_what_it_can_resolve() -> None:
    """Lazy re-export must stay honest: every advertised name has to load."""
    assert set(qlibx.__all__) == {"Project", "QlibxError", *qlibx._SUBMODULES}
    for name in qlibx.__all__:
        assert getattr(qlibx, name) is not None, f"qlibx.{name} does not resolve"
    with pytest.raises(AttributeError):
        qlibx.not_a_real_submodule  # noqa: B018


def test_importing_the_facade_does_not_load_the_execution_runtime() -> None:
    """`import qlibx` must not cost the Qlib runtime before a capability is named."""
    source = (
        "import sys\n"
        "import qlibx\n"
        "assert 'qlib' not in sys.modules, 'qlib loaded by import qlibx'\n"
        "assert 'cvxpy' not in sys.modules, 'cvxpy loaded by import qlibx'\n"
        "assert 'duckdb' not in sys.modules, 'duckdb loaded by import qlibx'\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", source], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


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
        "strategy_manifest",
    ],
)
def test_public_module_paths_stay_importable(module: str) -> None:
    """Installed examples import these paths directly; splitting a module must not break them."""
    __import__(f"{PACKAGE_NAME}.{module}")
