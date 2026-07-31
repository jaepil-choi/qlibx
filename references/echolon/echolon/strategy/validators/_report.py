"""Uniform result type for all deterministic validators.

Validators DO NOT raise (unlike ``echolon.strategy.preflight`` which
fail-fasts on first error). They accumulate findings and hand back a
structured report so callers can see multiple issues per call instead
of one-at-a-time. MCP tool wrappers (``echolon/mcp/server.py``) convert
findings to actionable error messages for downstream agents.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class Finding:
    """One issue surfaced by a validator.

    ``code`` is an error-catalog code (STR-*, VAL-*, PRM-*, IND-*, BT-*).
    ``message`` is a short human-readable summary.
    ``context`` carries the structured key/value fix-template fields from
    the catalog entry so downstream consumers can format remediation
    guidance deterministically.
    """

    code: str
    message: str
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Report:
    """Aggregate of findings from one validator call.

    A validator returns one ``Report``. The caller can inspect
    ``any_errors`` as a one-shot gate, or iterate ``findings`` to surface
    every issue at once. ``to_dict()`` produces the JSON-serializable
    form the MCP tool wrappers return to agents.
    """

    findings: List[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    @property
    def any_errors(self) -> bool:
        return len(self.findings) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "any_errors": self.any_errors,
            "findings": [asdict(f) for f in self.findings],
        }
