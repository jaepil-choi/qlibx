"""Compliance rules this package ships, discoverable by name.

This is **discoverability and path resolution only**. No allowlist gate is added to
``load_compliance``: Compliance is a canonically open extension point, and a user-authored rule
must keep loading exactly as it does today. An allowlist would also be wrong on its own terms,
because ``component/loading.py`` re-executes a component file by path under a fingerprinted module
name, so a path-loaded builtin is a distinct class object from the one exported here and would fail
any ``isinstance`` check against it.

``load_compliance`` does check one thing about identity, and it restricts no class: a rule must
answer to the id it was registered under (`docs/implementations/068`).

Shipped builtins use absolute ``vqapr.`` imports because they execute outside package context.
"""

from __future__ import annotations

from pathlib import Path

from vqapr.component.compliance.no_short import NoShort
from vqapr.component.compliance.single_name_cap import SingleNameCap

__all__ = [
    "SHIPPED_COMPLIANCE",
    "NoShort",
    "SingleNameCap",
    "shipped_compliance_path",
]


SHIPPED_COMPLIANCE: dict[str, type] = {
    "no_short": NoShort,
    "single_name_cap": SingleNameCap,
}
"""Builtin rule classes by shipped name. Each observes what the kit function of the same name in
`vqapr.portfolio.bounds` lets a strategy build inside -- with its own parameters, never the
strategy's."""


def shipped_compliance_path(name: str) -> Path:
    """Resolve a shipped rule's source path so it can be registered like any component.

    Builtins enter through the same door as user components: a `ComponentRef` carrying a path, a
    fingerprint and a config. Nothing here bypasses registration.
    """
    if name not in SHIPPED_COMPLIANCE:
        known = ", ".join(sorted(SHIPPED_COMPLIANCE))
        raise KeyError(f"unknown shipped compliance rule {name!r}; known: {known}")
    path = Path(__file__).with_name(f"{name}.py")
    if not path.is_file():
        raise FileNotFoundError(f"shipped compliance source is missing: {path}")
    return path
