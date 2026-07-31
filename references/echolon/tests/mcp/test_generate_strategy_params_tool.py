"""Phase B1 — generate_strategy_params MCP tool.

Tool signature + happy-path + failure-path assertions via the in-process
FastMCP tool manager (stdio smoke lives in test_stdio_smoke.py).
"""
import asyncio
import json
from pathlib import Path

import pytest

from echolon.mcp.server import build_server


_MINIMAL = {
    "entry_parameters": {
        "calculation": {
            "rsi_period": {
                "type": "int", "range": [10, 20], "default": 14,
                "description": "RSI", "ownership": "owner",
            },
        },
        "usage": {}, "fixed": {},
    },
    "exit_parameters": {"calculation": {}, "usage": {}, "fixed": {
        "take_profit": {"type": "float", "value": 0.05, "description": "TP", "ownership": "owner"},
    }},
    "risk_parameters": {"calculation": {}, "usage": {}, "fixed": {
        "max_positions": {"type": "int", "value": 5, "description": "max", "ownership": "owner"},
    }},
    "sizing_parameters": {"calculation": {}, "usage": {}, "fixed": {
        "risk_pct": {"type": "float", "value": 0.01, "description": "risk", "ownership": "owner"},
    }},
    "extraction_report": {"shared_parameters": []},
}


def _get_tool_fn(name: str):
    server = build_server()
    tm = server._tool_manager
    tools = getattr(tm, "_tools", None) or getattr(tm, "tools", None)
    if tools is None:
        raise RuntimeError(f"FastMCP tool_manager shape unknown: {dir(tm)}")
    return tools[name].fn


def _registered() -> set[str]:
    server = build_server()
    tools = server.list_tools()
    if asyncio.iscoroutine(tools):
        tools = asyncio.run(tools)
    return {t.name for t in tools}


def test_generate_strategy_params_tool_registered():
    assert "generate_strategy_params" in _registered()


def test_generate_strategy_params_happy_path(tmp_path):
    fn = _get_tool_fn("generate_strategy_params")
    params_file = tmp_path / "params_to_optimize.json"
    params_file.write_text(json.dumps(_MINIMAL, indent=2))
    output = tmp_path / "strategy_params.py"

    result = fn(
        params_file_path=str(params_file),
        output_path=str(output),
        frequency="interday",
    )
    assert result["success"] is True
    assert result["output_path"] == str(output)
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "from echolon.strategy.parameter_architecture import" in content
    assert isinstance(result["corrections"], list)


def test_generate_strategy_params_reports_corrections(tmp_path):
    """Over-cap TEMA period → correction surfaces in the tool result."""
    fn = _get_tool_fn("generate_strategy_params")
    data = {
        "entry_parameters": {
            "calculation": {
                "tema_period": {
                    "type": "int", "range": [30, 120], "default": 60,
                    "description": "TEMA", "ownership": "owner",
                },
            },
            "usage": {}, "fixed": {},
        },
        "exit_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
        "risk_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
        "sizing_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
        "extraction_report": {"shared_parameters": []},
    }
    params_file = tmp_path / "params_to_optimize.json"
    params_file.write_text(json.dumps(data))
    output = tmp_path / "strategy_params.py"
    result = fn(
        params_file_path=str(params_file),
        output_path=str(output),
        frequency="interday",
    )
    assert result["success"] is True
    tema = next((c for c in result["corrections"] if c["param"] == "tema_period"), None)
    assert tema is not None
    assert tema["cap"] == 62


def test_generate_strategy_params_bad_json_returns_failure(tmp_path):
    fn = _get_tool_fn("generate_strategy_params")
    bad = tmp_path / "params_to_optimize.json"
    bad.write_text("{not json", encoding="utf-8")
    output = tmp_path / "strategy_params.py"

    result = fn(
        params_file_path=str(bad),
        output_path=str(output),
        frequency="interday",
    )
    assert result["success"] is False
    assert output.exists() is False
    assert "JSON" in result["message"] or "json" in result["message"].lower()


def test_generate_strategy_params_missing_input_returns_failure(tmp_path):
    fn = _get_tool_fn("generate_strategy_params")
    missing = tmp_path / "nope.json"
    output = tmp_path / "strategy_params.py"
    result = fn(
        params_file_path=str(missing),
        output_path=str(output),
    )
    assert result["success"] is False
    assert output.exists() is False
