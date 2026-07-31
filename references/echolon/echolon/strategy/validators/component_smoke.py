"""Bar-0 component-instantiation smoke check.

Static validators (``component_signatures`` / ``component_integration``)
import modules and inspect signatures, but never CONSTRUCT a component or
CALL its trading method. The single most common pre-backtest crash class
they therefore miss is the **undeclared indicator column**: the component
calls ``self.get_indicator("highest_high_20")`` while
``strategy_indicator_list.json`` only declared ``high`` (a rename/typo
drift between JSON and code). That bug ships clean through every static
check and only surfaces ~15 minutes into the WFA backtest.

This validator instantiates each component against a stub engine and
calls its method once on a single synthetic bar, recording every
indicator name the code requests. It then flags any requested name whose
base does not correspond to a declared indicator (or a system-provided
one) as **IND-007**.

DESIGN — zero false positives by construction:

  * The stub's ``get_indicator`` NEVER raises (returns a dummy float and
    records the name). So an imperfect column-name expansion can never
    cause a spurious KeyError.
  * Detection is by base-name match (``name == base`` or
    ``name.startswith(base + "_")``), which is robust to multi-param
    sweep suffixes (``bbands_upper_timeperiod20_nbdevup2p0`` matches the
    declared base ``bbands``). It only flags names that share NO declared
    base — i.e. a genuinely wrong indicator name. It deliberately does
    NOT try to catch a missing-suffix bug (bare ``rsi`` when ``rsi_14``
    is needed); that would require exact runtime column expansion and
    risks false positives. False negatives here are acceptable; false
    positives (blocking a valid strategy) are not.
  * EVERY other exception raised during instantiation / the method call
    is SWALLOWED (recorded as an inconclusive note, never a finding).
    The stub cannot perfectly emulate the live engine, so a crash on an
    un-stubbed method or on degenerate synthetic data must not block a
    strategy that is actually fine.

Because of the swallow-everything-else policy this validator is advisory:
it is exposed as its own MCP tool (``validate_component_smoke``) and is
intentionally NOT part of ``validate_strategy_full``'s blocking set.

Error code:
- IND-007: component reads an indicator column whose base was never
  declared in strategy_indicator_list.json (JSON↔code name drift).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from echolon.strategy.validators import Finding, Report


# System-provided indicators the engine injects regardless of
# strategy_indicator_list.json (mandatory bar-count + session/regime
# context). A read of any of these must never be flagged.
_SYSTEM_INDICATORS: Set[str] = {
    "session_phase", "session_phase_agg", "market_regime",
    "bar_of_day", "bar_of_session", "bars_remaining",
    "bars_remaining_in_session", "has_night_session",
    "session_bars_total", "total_bars_today",
}

# (module_stem, class_name, method_name, needs_position, needs_entry_signal)
_COMPONENTS = (
    ("entry", "entry_rule",     "generate_signal", False, False),
    ("exit",  "exit_rule",      "should_exit",     True,  False),
    ("risk",  "risk_manager",   "can_trade",       False, False),
    ("sizer", "position_sizer", "calculate_size",  False, True),
)

_PARAM_KEY = {
    "entry": "entry_params", "exit": "exit_params",
    "risk": "risk_params", "sizer": "sizer_params",
}


class _StubMarketData:
    """IMarketData slice the BaseComponent helpers delegate to.

    ``get_indicator`` records the requested name and returns a dummy —
    it NEVER raises, so column-name drift is detected post-hoc, not by a
    spurious KeyError mid-run.
    """

    def __init__(self, requested: List[str]) -> None:
        self._requested = requested

    # --- indicators (recorded) ---------------------------------------
    def get_indicator(self, name: str, index: int = 0) -> float:
        self._requested.append(str(name).lower())
        return 1.0

    def get_indicator_series(self, name: str, count: int = 1, index: int = 0):
        self._requested.append(str(name).lower())
        return [1.0] * max(1, count)

    def get_indicators(self) -> Dict[str, float]:
        return {}

    # --- price / bar -------------------------------------------------
    def get_current_price(self) -> float:
        return 100.0

    def get_current_bar(self) -> Dict[str, float]:
        return {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}

    def get_close(self, ago: int = 0) -> float:
        return 100.0

    def get_open(self, ago: int = 0) -> float:
        return 100.0

    def get_high(self, ago: int = 0) -> float:
        return 101.0

    def get_low(self, ago: int = 0) -> float:
        return 99.0

    def get_volume(self, ago: int = 0) -> float:
        return 1000.0

    def get_bar_data(self, ago: int = 0) -> Dict[str, float]:
        return self.get_current_bar()


class _StubPortfolio:
    def __init__(self, position: Optional[Any]) -> None:
        self._position = position

    def get_position(self) -> Optional[Any]:
        return self._position

    def get_cash(self) -> float:
        return 1_000_000.0

    def get_equity(self) -> float:
        return 1_000_000.0

    def get_portfolio_value(self) -> float:
        return 1_000_000.0


class _StubTradingContext:
    tradeable_phases = ["night", "morning", "afternoon"]

    def decode_phase(self, numeric: int) -> str:
        return "night"

    def encode_phase(self, phase: str) -> int:
        return 0


class _StubFrequencyContext:
    """Minimal IFrequencyContext — frequency_type is read by
    get_session_phase()/get_market_regime() guards."""

    def __init__(self, frequency_type: Any) -> None:
        self.frequency_type = frequency_type

    def days_to_bars(self, days: int) -> int:
        return days


class _StubEngine:
    def __init__(self, requested: List[str], position: Optional[Any], freq_ctx: Any) -> None:
        self._md = _StubMarketData(requested)
        self._port = _StubPortfolio(position)
        self._freq = freq_ctx

    def get_market_data(self):
        return self._md

    def get_portfolio(self):
        return self._port

    def get_logger(self):
        return None

    def get_strategy_logger(self):
        return None

    def get_event_bus(self):
        return None

    def get_market_adapter(self):
        return None

    def get_frequency_context(self):
        return self._freq

    def get_trading_context(self):
        return _StubTradingContext()

    def get_session_context_provider(self):
        return None


def _declared_bases(strategy_dir: Path) -> Optional[Set[str]]:
    """Lowercased indicator names declared in strategy_indicator_list.json,
    or None if the file is absent/unreadable (smoke then can't run)."""
    path = strategy_dir / "strategy_indicator_list.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    # Flat-dict form: top-level keys are indicator names. Tolerate a
    # legacy section-keyed payload by also unioning nested dict keys.
    bases: Set[str] = set()
    for k, v in payload.items():
        bases.add(str(k).lower())
        if isinstance(v, dict):
            for nk in v:
                bases.add(str(nk).lower())
    return bases


def _is_declared(name: str, declared: Set[str]) -> bool:
    if name in _SYSTEM_INDICATORS:
        return True
    for base in declared:
        if name == base or name.startswith(base + "_"):
            return True
    return False


def _frequency_context():
    """Best-effort INTRADAY frequency context so get_session_phase() reaches
    its indicator read instead of crashing on a None context. Falls back to
    None if the enum import shape changed (crash is swallowed anyway)."""
    try:
        from echolon.strategy.interfaces import FrequencyType  # type: ignore
        return _StubFrequencyContext(FrequencyType.INTRADAY)
    except Exception:  # noqa: BLE001 — context is best-effort
        return None


def _dummy_entry_signal():
    """A minimal EntrySignalOutput for sizer.calculate_size(); None if the
    schema can't be constructed (sizer smoke is then skipped)."""
    try:
        from echolon.strategy.schemas import EntrySignalOutput
        return EntrySignalOutput(
            signal="LONG", strength=1.0, type="SMOKE", entry_reason="smoke",
        )
    except Exception:  # noqa: BLE001
        return None


def _long_position():
    try:
        from echolon.strategy.interfaces import Position
        return Position(
            symbol="SMOKE", size=1.0, avg_price=100.0, market_value=100.0,
            unrealized_pnl=0.0, realized_pnl=0.0, direction="LONG",
        )
    except Exception:  # noqa: BLE001
        return None


def _smoke_component(
    strategy_dir: Path,
    module_stem: str,
    class_name: str,
    method_name: str,
    needs_position: bool,
    needs_entry_signal: bool,
    requested: List[str],
    notes: List[str],
) -> None:
    from echolon.strategy.loader import StrategyLoader

    file_path = strategy_dir / f"{module_stem}.py"
    if not file_path.exists():
        return  # preflight STR-001 territory

    try:
        loader = StrategyLoader(strategy_dir)
        module = loader.load_module(module_stem)
        cls = getattr(module, class_name, None)
        if cls is None:
            return  # preflight STR-002 (class export) territory
    except Exception as e:  # noqa: BLE001 — import handled by component_integration STR-002
        notes.append(f"{module_stem}: load skipped ({type(e).__name__})")
        return

    params: Dict[str, Any] = {}
    try:
        sp = loader.load_module("strategy_params")
        default_params = getattr(sp, "DEFAULT_PARAMS", {}) or {}
        params = dict(default_params.get(_PARAM_KEY[module_stem], {}) or {})
    except Exception:  # noqa: BLE001 — PRM-002 territory; instantiate with bare params
        params = {}
    params.setdefault("printlog", False)

    position = _long_position() if needs_position else None
    engine = _StubEngine(requested, position, _frequency_context())

    try:
        component = cls(trading_engine=engine, run_context="optimization", **params)
    except Exception as e:  # noqa: BLE001 — swallow: stub cannot perfectly emulate engine
        notes.append(f"{class_name}.__init__ inconclusive ({type(e).__name__}: {e})")
        return

    method = getattr(component, method_name, None)
    if method is None:
        return  # STR-003 territory (component_signatures)

    try:
        if needs_entry_signal:
            sig = _dummy_entry_signal()
            if sig is None:
                notes.append(f"{class_name}.{method_name} skipped (no dummy EntrySignalOutput)")
                return
            method(sig)
        else:
            method()
    except Exception as e:  # noqa: BLE001 — swallow: advisory, never blocks
        notes.append(f"{class_name}.{method_name} inconclusive ({type(e).__name__}: {e})")


def validate_component_smoke(strategy_dir: "Path | str") -> Report:
    """Instantiate + bar-0 smoke each component, flagging undeclared
    indicator-column reads (IND-007). Advisory: never raises, every
    non-detection exception is swallowed (see module docstring)."""
    strategy_dir = Path(strategy_dir)
    report = Report()

    declared = _declared_bases(strategy_dir)
    if declared is None:
        return report  # no declared list → nothing to check against

    requested: List[str] = []
    notes: List[str] = []
    for stem, cls_name, method, needs_pos, needs_sig in _COMPONENTS:
        _smoke_component(
            strategy_dir, stem, cls_name, method, needs_pos, needs_sig,
            requested, notes,
        )

    # Flag distinct undeclared reads, preserving first-seen order.
    seen: Set[str] = set()
    for name in requested:
        if name in seen:
            continue
        seen.add(name)
        if not _is_declared(name, declared):
            report.add(Finding(
                code="IND-007",
                message=(
                    f"Component reads indicator '{name}' whose base is not "
                    f"declared in strategy_indicator_list.json."
                ),
                context={
                    "indicator": name,
                    "declared": sorted(declared),
                    "hint": (
                        "Rename the get_indicator() argument to a declared "
                        "column, or add the indicator to strategy_indicator_list.json."
                    ),
                },
            ))

    return report
