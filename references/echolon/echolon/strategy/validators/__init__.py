"""Deterministic component validators.

Each validator under this package is a pure function:

 def validate_<name>(**inputs) -> Report:

Validators accumulate findings instead of raising — callers get the full
picture in one shot. See _report.py for the result type.

MCP tool wrappers in echolon/mcp/server.py expose each validator as a
first-class tool for the coding-agent pipeline.
"""
from echolon.strategy.validators._report import Finding, Report

__all__ = ["Finding", "Report"]
