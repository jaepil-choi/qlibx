"""Regression: in migrated subsystems, bare raise of generic exceptions is
forbidden at any scope. Tests only the subtrees listed in
MIGRATED_SUBSYSTEMS; add to that list as new subsystems are converted
in subsequent phases."""
import ast
import pathlib

MIGRATED_SUBSYSTEMS = [
    "strategy/parameter_architecture.py",
    "strategy/preflight.py",
    "data/loaders/session_availability_loader.py",
    "data/loaders/ohlcv_loader.py",
    "data/transformers/calendar_generator.py",
    "indicators/calculators/_utils.py",
    "indicators/calculators/intraday/indicators.py",
    "indicators/calculators/intraday/market_context.py",
    "backtest/engine/backtrader_strategy.py",
    "live/trading_slot.py",
    "live/platforms/miniqmt/qmt_client.py",
]
# Note: strategy/schemas.py is NOT in this list. P4B.2 tightened only
# EntrySignalOutput / ExitSignalOutput (VAL-001, VAL-002). The ~22
# bare raises in SizerOutput / RiskOutput / StrategyIndicatorList
# validators remain out of migration scope pending separate conversion.

# Bare raises of these concrete types are what we forbid. Catalog codes use
# raise_error(), which internally raises a subclass of EchelonError — those
# pass because their ast.Call's func is "raise_error", not one of these names.
FORBIDDEN = {
    "ValueError",
    "RuntimeError",
    "TypeError",
    "FileNotFoundError",
    "AttributeError",
    "NotImplementedError",
}


def _raise_node_is_forbidden(node: ast.Raise) -> bool:
    """Return True if the raise explicitly instantiates or re-names one of
    the forbidden generic exceptions."""
    if node.exc is None:  # bare `raise` (re-raise inside except block) — allowed
        return False
    exc = node.exc
    # raise ValueError(...) — ast.Call with Name func
    if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
        return exc.func.id in FORBIDDEN
    # raise ValueError — bare class reference
    if isinstance(exc, ast.Name):
        return exc.id in FORBIDDEN
    return False


def test_migrated_subsystems_use_catalog():
    base = pathlib.Path(__file__).parent.parent / "echolon"
    offenders: list[tuple[str, int]] = []
    for rel in MIGRATED_SUBSYSTEMS:
        path = base / rel
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and _raise_node_is_forbidden(node):
                offenders.append((rel, node.lineno))
    assert not offenders, (
        f"Migrated subsystems must use raise_error(code, ...); "
        f"found bare raises at {offenders}"
    )
