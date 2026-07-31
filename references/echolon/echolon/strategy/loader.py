"""
Unified Strategy Module Loader
===============================

Loads strategy modules (strategy.py, entry.py, exit.py, risk.py, sizer.py,
strategy_params.py) from any directory on disk using importlib.

This replaces multiple loading patterns (static imports, importlib.import_module,
spec_from_file_location with manual __package__) with one consistent approach.

Usage:
    loader = StrategyLoader(Path("workspace/strategy/baseline"))
    strategy_main = loader.load_function("strategy", "strategy_main")
    search_space = loader.load_attr("strategy_params", "optuna_search_space")
    EntryRule = loader.load_class("entry", "entry_rule")
"""

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from echolon.strategy.preflight import preflight as _preflight

logger = logging.getLogger(__name__)


# Mapping of strategy module file (without .py) to its required exported class name.
# Used by load_strategy_from_dir() to collect the component classes after
# preflight() has already verified every file/class is present.
_REQUIRED_CLASSES: dict[str, str] = {
    "entry": "entry_rule",
    "exit": "exit_rule",
    "risk": "risk_manager",
    "sizer": "position_sizer",
}


class StrategyLoader:
    """Load strategy modules from any directory on disk.

    Works with: workspace dirs, artifact-store paths, ~/.dolphin/runs/,
    named slot dirs, or any directory containing strategy .py files.

    Parameters
    ----------
    strategy_dir : Path
        Directory containing strategy .py files (strategy.py, entry.py, etc.)
    package_base : str, optional
        Base package name for resolving relative imports inside strategy modules.
        Defaults to "echolon.quant_engine.strategy._dynamic".
        Strategy code may use relative imports like ``from ...core.base...`` --
        the package_base determines how those resolve.
    """

    def __init__(self, strategy_dir: Path, package_base: str = "echolon.quant_engine.strategy._dynamic"):
        self.strategy_dir = Path(strategy_dir)
        self.package_base = package_base
        self._cache: dict[str, ModuleType] = {}

    def load_module(self, module_name: str) -> ModuleType:
        """Load a Python module from the strategy directory.

        Parameters
        ----------
        module_name : str
            Name of the module file without .py extension.
            E.g., "strategy", "entry", "strategy_params".

        Returns
        -------
        ModuleType
            The loaded module.

        Raises
        ------
        FileNotFoundError
            If the .py file doesn't exist in strategy_dir.
        """
        if module_name in self._cache:
            return self._cache[module_name]

        file_path = self.strategy_dir / f"{module_name}.py"
        if not file_path.exists():
            raise FileNotFoundError(
                f"Strategy module not found: {file_path}"
            )

        # Enable RELATIVE imports of vendored siblings (e.g. a generated
        # sizer's ``from .sizing_kit import ...``): register / re-point the
        # synthetic parent-package chain at THIS strategy dir before the
        # module is exec'd. Idempotent; never touches the real echolon root.
        self._register_synthetic_packages()

        fq_name = f"{self.package_base}.{module_name}"

        spec = importlib.util.spec_from_file_location(
            fq_name,
            str(file_path),
            submodule_search_locations=[],
        )
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = self.package_base
        sys.modules[fq_name] = mod

        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop(fq_name, None)
            raise

        self._cache[module_name] = mod
        logger.debug(f"Loaded strategy module: {file_path}")
        return mod

    def load_attr(self, module_name: str, attr_name: str) -> Any:
        """Load a specific attribute from a strategy module."""
        mod = self.load_module(module_name)
        if not hasattr(mod, attr_name):
            raise AttributeError(
                f"Module '{module_name}' in {self.strategy_dir} has no attribute '{attr_name}'"
            )
        return getattr(mod, attr_name)

    def load_function(self, module_name: str, func_name: str) -> Any:
        """Load a function from a strategy module. Alias for load_attr."""
        return self.load_attr(module_name, func_name)

    def load_class(self, module_name: str, class_name: str) -> type:
        """Load a class from a strategy module. Alias for load_attr."""
        return self.load_attr(module_name, class_name)

    def _register_synthetic_packages(self) -> None:
        """Register the synthetic parent-package chain so a component's RELATIVE
        import of a vendored sibling resolves against *this* strategy dir.

        ``package_base`` (default ``echolon.quant_engine.strategy._dynamic``) is
        a SYNTHETIC namespace: only the real ``echolon`` root exists on disk; the
        ``quant_engine.strategy._dynamic`` sub-levels do not. importlib resolves a
        relative import (``from .sizing_kit import f`` in ``sizer.py``) via the
        parent package's ``__path__``. Without the synthetic packages registered
        (with ``__path__`` pointing at the strategy dir) that import raises
        ``ModuleNotFoundError: No module named 'echolon.quant_engine'``.

        The chain is RE-POINTED to ``self.strategy_dir`` on every load because
        ``package_base`` is SHARED across all StrategyLoader instances (no caller
        customizes it): loader B must steal the namespace back from loader A. The
        loader already assumes one-strategy-at-a-time — each fresh-loader load
        re-execs + overwrites its component modules in ``sys.modules``. This
        extends that same per-load overwrite to the lazily-imported vendored
        siblings: those siblings (e.g. ``..._dynamic.sizing_kit``) are loaded by
        the import machinery as a side effect of execing a component and so
        short-circuit on ``sys.modules`` — they would keep serving the PREVIOUS
        strategy dir's copy. So when the leaf's ``__path__`` actually changes
        dirs, evict the previously-cached submodule subtree to force the new
        dir's siblings to re-resolve.

        NEVER shadows the real ``echolon`` root package.
        """
        parts = self.package_base.split(".")
        target = str(self.strategy_dir)
        for i in range(1, len(parts) + 1):
            name = ".".join(parts[:i])
            if name == parts[0]:
                # The real engine package lives on disk — never shadow it.
                continue
            pkg = sys.modules.get(name)
            if pkg is None:
                pkg = ModuleType(name)
            elif list(getattr(pkg, "__path__", []) or []) != [target]:
                # This synthetic package was pointed at a DIFFERENT strategy dir
                # by a prior loader. Evict its cached submodule subtree so this
                # dir's vendored siblings re-resolve (component modules are
                # re-exec'd anyway; this just extends that to the siblings).
                self._evict_synthetic_subtree(name)
                pkg = ModuleType(name)
            pkg.__path__ = [target]
            pkg.__package__ = name
            sys.modules[name] = pkg

    @staticmethod
    def _evict_synthetic_subtree(package_name: str) -> None:
        """Pop ``package_name`` and every cached submodule beneath it from
        ``sys.modules`` (so a stale ``__path__`` / stale sibling never persists).
        """
        prefix = package_name + "."
        for mod_name in [
            m for m in sys.modules
            if m == package_name or m.startswith(prefix)
        ]:
            sys.modules.pop(mod_name, None)

    def clear_cache(self):
        """Clear the module cache and remove from sys.modules.

        Call this when strategy files have been rewritten in place (e.g., by the
        coding agent) and need to be reloaded fresh.

        Removes the component modules this loader loaded AND the synthetic
        parent-package chain (``echolon.quant_engine``,
        ``echolon.quant_engine.strategy``, ``echolon.quant_engine.strategy._dynamic``)
        + any vendored-sibling submodules registered under it (e.g.
        ``..._dynamic.sizing_kit``), so a stale ``__path__`` never persists and a
        rewritten-in-place kit re-execs cleanly. The lazily imported siblings are
        NOT in ``self._cache`` (importlib loads them as a side effect of execing a
        component), so we sweep the whole synthetic namespace from ``sys.modules``.
        The real ``echolon`` root is never touched.
        """
        parts = self.package_base.split(".")
        # Synthetic package nodes = every prefix of package_base EXCEPT the real
        # ``echolon`` root (i >= 2). The leaf == package_base is itself a node.
        synthetic_nodes = {
            ".".join(parts[:i]) for i in range(2, len(parts) + 1)
        }
        prefix = self.package_base + "."  # submodules: ..._dynamic.{sizer,sizing_kit,...}
        for mod_name in [
            m for m in sys.modules
            if m in synthetic_nodes or m.startswith(prefix)
        ]:
            sys.modules.pop(mod_name, None)
        self._cache.clear()
        logger.debug(f"Cleared strategy loader cache for {self.strategy_dir}")

    def has_module(self, module_name: str) -> bool:
        """Check if a strategy module file exists."""
        return (self.strategy_dir / f"{module_name}.py").exists()


def load_strategy_from_dir(
    strategy_dir: Path | str,
    package_base: str = "echolon.quant_engine.strategy._dynamic",
) -> dict[str, Any]:
    """Load a complete strategy from a directory, validating structure.

    This is the public, catalog-aware entry point for loading a strategy.
    It performs up-front structural validation before delegating to
    StrategyLoader, raising typed Echolon errors so an LLM author can
    understand and fix malformed strategies.

    Parameters
    ----------
    strategy_dir : Path | str
        Directory containing the 7 required strategy files.
    package_base : str, optional
        Base package name for resolving relative imports.

    Returns
    -------
    dict[str, Any]
        Dict of loaded component classes keyed by module name:
        {"entry_rule": ..., "exit_rule": ..., "risk_manager": ...,
         "position_sizer": ...}

    Raises
    ------
    EchelonError
        STR-001 if any of the 7 required files are missing.
        STR-002 if a required class is not exported by its module.
        PRM-001 / PRM-002 if strategy_params.DEFAULT_PARAMS is malformed.
        (See ``echolon.strategy.preflight`` for the full check order.)
    """
    strategy_dir = Path(strategy_dir)

    # Delegate structural + param validation to the shared preflight
    # orchestrator so STR-001/002 and PRM-001/002 surface at load time
    # with the richest catalog error.
    _preflight(strategy_dir)

    loader = StrategyLoader(strategy_dir, package_base=package_base)
    components: dict[str, Any] = {}
    for module_name, expected_class_name in _REQUIRED_CLASSES.items():
        module = loader.load_module(module_name)
        components[expected_class_name] = getattr(module, expected_class_name)

    return components
