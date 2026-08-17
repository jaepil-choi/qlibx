"""Constraints this package ships, discoverable by name.

This is **discoverability and path resolution only**. No gate is added to ``load_constraint``:
constraints are a canonically open extension point, and a user-authored constraint must keep
loading exactly as it does today. An identity gate would also be wrong on its own terms, because
``extension/loading.py`` re-executes a component file by path under a fingerprinted module name, so
a path-loaded builtin is a distinct class object from the one exported here and would fail any
``isinstance`` check against it.

Shipped builtins use absolute ``vqapr.`` imports because they execute outside package context.
"""

from __future__ import annotations

from pathlib import Path

from vqapr.constraints.builtin.no_short import NoShort
from vqapr.constraints.builtin.single_name_cap import SingleNameCap

SHIPPED_CONSTRAINTS: dict[str, type] = {
    "no_short": NoShort,
    "single_name_cap": SingleNameCap,
}
"""Builtin constraint classes by shipped name."""


def shipped_constraint_path(name: str) -> Path:
    """Resolve a shipped constraint's source path so it can be registered like any component.

    Builtins enter through the same door as user components: a `ComponentRef` carrying a path, a
    fingerprint and a config. Nothing here bypasses registration.
    """
    if name not in SHIPPED_CONSTRAINTS:
        known = ", ".join(sorted(SHIPPED_CONSTRAINTS))
        raise KeyError(f"unknown shipped constraint {name!r}; known: {known}")
    path = Path(__file__).with_name(f"{name}.py")
    if not path.is_file():
        raise FileNotFoundError(f"shipped constraint source is missing: {path}")
    return path


__all__ = ["SHIPPED_CONSTRAINTS", "NoShort", "SingleNameCap", "shipped_constraint_path"]
