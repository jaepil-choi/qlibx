"""Composite full-strategy validator — importable plain function.

Exposes ``validate_strategy_full`` as a directly-importable function so the
qorka coding pipeline can call it deterministically (no LLM/MCP round-trip).
The MCP tool in ``echolon.mcp.server`` delegates to this function verbatim;
the return shape and all composition logic are defined here as the single
source of truth.

Return shape::

    {
        "status": "VALID" | "INVALID",
        "any_errors": bool,
        "total_findings": int,
        "findings": [{"code": ..., ...}],
        "invocations": [{"validator": str, "count": int}],
    }

``status`` is ``"VALID"`` iff no findings were reported by any validator.

IND-001/IND-002 contract: a ``VALID`` verdict means the regime/indicator
columns the code reads are declared in ``strategy_indicator_list.json``.
"""
from __future__ import annotations

import json as _json_il
from pathlib import Path

from echolon.indicators import catalog as _catalog
from echolon.native.validation import validate_strategy as _validate_strategy


def validate_strategy_full(strategy_dir: str | Path) -> dict:
    """Run every shipped validator and return merged findings.

    Composes the individual validators (``validate_strategy`` /
    ``validate_component_protocol_signatures`` /
    ``validate_component_integration`` / ``validate_component_logging`` /
    ``validate_parameter_access`` / ``validate_indicator_names``) so a caller
    gets a complete validation report from a single function call —
    including the JSON↔code indicator contract (IND-001/IND-002), so a VALID
    verdict means the regime/indicator columns the code reads are declared.

    Args:
        strategy_dir: Absolute path to the strategy directory (str or Path).

    Returns:
        ``{status, any_errors, total_findings, findings: [{code, ...}],
        invocations: [{validator, count}]}``. ``status`` is ``"VALID"``
        iff no findings were reported by any validator.
    """
    from echolon.strategy.validators.component_signatures import (
        validate_component_signatures as _vcs,
    )
    from echolon.strategy.validators.component_integration import (
        validate_component_integration as _vci,
    )
    from echolon.strategy.validators.component_logging import (
        validate_component_logging as _vcl,
    )
    from echolon.strategy.validators.parameter_access import (
        validate_parameter_access as _vpa,
    )
    from echolon.strategy.validators.params_sync import (
        validate_params_sync as _vps,
    )
    from echolon.native.validation.indicator_validator import (
        validate_indicator_names as _vin,
    )

    strategy_dir = str(strategy_dir)

    invocations: list[dict] = []
    findings: list[dict] = []

    result = _validate_strategy(Path(strategy_dir))
    struct_findings = [
        {"code": e.code, "what": e.what, "why": e.why, "fix": e.fix, "docs_url": e.docs_url}
        for e in result.errors
    ]
    invocations.append({"validator": "validate_strategy", "count": len(struct_findings)})
    findings.extend(struct_findings)

    for name, impl in (
        ("validate_component_protocol_signatures", _vcs),
        ("validate_component_integration", _vci),
        ("validate_component_logging", _vcl),
        ("validate_parameter_access", _vpa),
        ("validate_params_sync", _vps),
    ):
        sub = impl(strategy_dir=strategy_dir).to_dict()
        sub_findings = sub.get("findings", [])
        invocations.append({"validator": name, "count": len(sub_findings)})
        findings.extend(sub_findings)

    ind_findings = [
        {"code": e.code, "what": e.what, "why": e.why, "fix": e.fix, "docs_url": e.docs_url}
        for e in _vin(Path(strategy_dir))
    ]
    invocations.append({"validator": "validate_indicator_names", "count": len(ind_findings)})
    findings.extend(ind_findings)

    # A6 (RCA 2026-06-18): compose the indicator-LIST catalog check so "full" implies
    # the indicator-list contract — legacy section-keys (IND-008) + unknown indicators
    # (IND-004) — not just the accessor scan (IND-002). Static: load
    # strategy_indicator_list.json + catalog.validate (regime columns accepted via
    # A1's KNOWN_REGIME_COLUMNS). Absent file → skip (mirrors validate_params_sync;
    # some paradigms have no list at this stage). NOTE: validate_component_smoke
    # (IND-007) is deliberately NOT composed here — it is advisory/zero-FP-by-design
    # and swallows inconclusive runs (see its docstring: "call it explicitly as a
    # pre-flight"); the static IND-002 + this catalog check cover the list contract.
    _ind_list_path = Path(strategy_dir) / "strategy_indicator_list.json"
    if _ind_list_path.exists():
        try:
            _il_data = _json_il.loads(_ind_list_path.read_text())
            _il_errors = [
                {"code": c.get("code"), "message": c.get("message"),
                 "fix": c.get("suggestion"), "field": c.get("field")}
                for c in _catalog.validate(_il_data)
            ]
        except _json_il.JSONDecodeError as e:
            _il_errors = [{"code": "IND-000",
                           "message": f"strategy_indicator_list.json parse error: {e}",
                           "fix": "Fix the JSON syntax."}]
        invocations.append({"validator": "validate_indicator_list", "count": len(_il_errors)})
        findings.extend(_il_errors)

    return {
        "status": "VALID" if not findings else "INVALID",
        "any_errors": bool(findings),
        "total_findings": len(findings),
        "findings": findings,
        "invocations": invocations,
    }
