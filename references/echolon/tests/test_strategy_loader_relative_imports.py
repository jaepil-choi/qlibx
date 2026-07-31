"""StrategyLoader relative-import enabler tests.

A generated strategy is deploy-self-contained: its ``sizer.py`` imports a vendored
sibling (``from .sizing_kit import ...``) sitting next to it in the strategy dir.
``StrategyLoader`` loads each component as ``{package_base}.{name}`` over a
SYNTHETIC package namespace (``echolon.quant_engine.strategy._dynamic``) that does
not exist on disk. These tests pin the enabler that makes such relative sibling
imports resolve against the strategy dir, the re-point lifecycle across strategy
dirs (the portfolio-backtest scenario: serial loads, fresh loader per slot, NO
``clear_cache`` between them), the in-place ``clear_cache`` eviction, and the
invariant that the real ``echolon`` root is never shadowed.
"""

import textwrap

import echolon  # the REAL root package — must never be shadowed
import pytest

from echolon.strategy.loader import StrategyLoader

_SYNTHETIC_PREFIX = "echolon.quant_engine"


@pytest.fixture(autouse=True)
def _clean_synthetic_namespace():
    """Evict the synthetic ``echolon.quant_engine*`` namespace before + after
    each test so loads don't leak across tests (these tests deliberately
    register/re-point that global namespace)."""
    import sys

    def _sweep():
        for name in [
            m for m in list(sys.modules)
            if m == _SYNTHETIC_PREFIX or m.startswith(_SYNTHETIC_PREFIX + ".")
        ]:
            sys.modules.pop(name, None)

    _sweep()
    yield
    _sweep()


def _write_strategy(dir_path, sizing_kit_value: float):
    """Lay down a minimal sizer.py + sibling sizing_kit.py in ``dir_path``.

    ``sizer.py`` does a RELATIVE sibling import (``from .sizing_kit import f``)
    and re-exposes it as ``size()`` so a caller can observe WHICH dir's
    ``sizing_kit`` was resolved.
    """
    (dir_path / "sizing_kit.py").write_text(textwrap.dedent(f"""\
        def f():
            return {sizing_kit_value}
    """))
    (dir_path / "sizer.py").write_text(textwrap.dedent("""\
        from .sizing_kit import f


        def size():
            return f()
    """))


# ---------------------------------------------------------------------------
# 1. Relative sibling import resolves against the strategy dir
# ---------------------------------------------------------------------------


def test_relative_sibling_import_resolves(tmp_path):
    """A component doing ``from .sizing_kit import f`` resolves the vendored
    sibling in the same strategy dir (the deploy-self-containment mechanism)."""
    _write_strategy(tmp_path, 1.0)
    loader = StrategyLoader(tmp_path)
    mod = loader.load_module("sizer")
    assert mod.size() == 1.0


# ---------------------------------------------------------------------------
# 2. Re-point lifecycle — dir A then dir B, fresh loaders, NO clear_cache
#    (the portfolio-backtest scenario). B must resolve B's sibling, not A's.
# ---------------------------------------------------------------------------


def test_relative_import_re_points_across_dirs_without_clear_cache(tmp_path):
    """Load dir A then dir B with DIFFERENT ``sizing_kit`` content via fresh
    loaders and NO ``clear_cache`` between (exactly how the portfolio runner
    iterates slots). B must resolve B's sibling (the synthetic leaf is re-pointed
    + the stale cached sibling evicted on the dir change); A's already-loaded
    module keeps its own binding."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    _write_strategy(dir_a, 1.0)
    _write_strategy(dir_b, 2.0)

    mod_a = StrategyLoader(dir_a).load_module("sizer")
    assert mod_a.size() == 1.0

    mod_b = StrategyLoader(dir_b).load_module("sizer")
    assert mod_b.size() == 2.0, "loader B resolved loader A's stale sizing_kit"

    # A's module was captured before B loaded; its binding is unchanged.
    assert mod_a.size() == 1.0


# ---------------------------------------------------------------------------
# 3. clear_cache evicts an in-place-rewritten vendored sibling (same dir)
# ---------------------------------------------------------------------------


def test_clear_cache_evicts_in_place_rewritten_sibling(tmp_path):
    """Same dir, sibling rewritten in place (the documented clear_cache trigger):
    the dir-change auto-eviction does NOT fire (dir unchanged), so clear_cache
    must evict the lazily-cached ``..._dynamic.sizing_kit`` for the rewrite to
    take effect on reload."""
    import importlib

    _write_strategy(tmp_path, 1.0)
    loader = StrategyLoader(tmp_path)
    assert loader.load_module("sizer").size() == 1.0

    # Rewrite the sibling in place, then clear + reload. Use a different-LENGTH
    # value (22.0) so the bytecode cache is invalidated by size even on a
    # same-second rewrite (the .pyc header stores source mtime only to the
    # second) — this isolates the test from pyc staleness, leaving clear_cache's
    # sys.modules eviction as the thing under test.
    (tmp_path / "sizing_kit.py").write_text("def f():\n    return 22.0\n")
    importlib.invalidate_caches()
    loader.clear_cache()
    assert loader.load_module("sizer").size() == 22.0


def test_clear_cache_removes_synthetic_package_chain(tmp_path):
    """clear_cache sweeps the synthetic package nodes + sibling submodules out of
    sys.modules so a stale ``__path__`` never persists."""
    import sys

    _write_strategy(tmp_path, 1.0)
    loader = StrategyLoader(tmp_path)
    loader.load_module("sizer")
    assert "echolon.quant_engine.strategy._dynamic" in sys.modules
    assert "echolon.quant_engine.strategy._dynamic.sizing_kit" in sys.modules

    loader.clear_cache()
    for leaked in [
        "echolon.quant_engine",
        "echolon.quant_engine.strategy",
        "echolon.quant_engine.strategy._dynamic",
        "echolon.quant_engine.strategy._dynamic.sizer",
        "echolon.quant_engine.strategy._dynamic.sizing_kit",
    ]:
        assert leaked not in sys.modules, f"{leaked} survived clear_cache"


# ---------------------------------------------------------------------------
# 4. The real echolon root is never shadowed
# ---------------------------------------------------------------------------


def test_real_echolon_root_not_shadowed(tmp_path):
    """Registering the synthetic ``echolon.quant_engine`` chain must NOT replace
    or corrupt the real on-disk ``echolon`` package."""
    import importlib
    import sys

    _write_strategy(tmp_path, 1.0)
    StrategyLoader(tmp_path).load_module("sizer")

    assert sys.modules["echolon"] is echolon
    assert echolon.__file__.endswith("echolon/__init__.py")
    # A real submodule still imports cleanly through the untouched root.
    assert importlib.import_module("echolon.strategy.schemas") is not None
