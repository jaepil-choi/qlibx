"""Phase A1 + A2 — generate_strategy_params public API.

Required args, structured GenerationResult return, absolute import in generated code.
"""
import json
from pathlib import Path

import pytest


_MINIMAL_PARAMS = {
    "entry_parameters": {
        "calculation": {
            "rsi_period": {
                "type": "int",
                "range": [10, 20],
                "default": 14,
                "description": "RSI lookback period",
                "ownership": "owner",
            },
        },
        "usage": {
            "rsi_oversold": {
                "type": "float",
                "range": [20.0, 35.0],
                "default": 30.0,
                "description": "RSI oversold threshold",
                "ownership": "owner",
            },
        },
        "fixed": {},
    },
    "exit_parameters": {
        "calculation": {},
        "usage": {},
        "fixed": {
            "exit_take_profit_pct": {
                "type": "float",
                "value": 0.05,
                "description": "Take profit at 5%",
                "ownership": "owner",
            },
        },
    },
    "risk_parameters": {
        "calculation": {},
        "usage": {},
        "fixed": {
            "max_position_size": {
                "type": "int",
                "value": 10,
                "description": "Max position size",
                "ownership": "owner",
            },
        },
    },
    "sizing_parameters": {
        "calculation": {},
        "usage": {},
        "fixed": {
            "risk_per_trade": {
                "type": "float",
                "value": 0.01,
                "description": "Risk 1% per trade",
                "ownership": "owner",
            },
        },
    },
    "extraction_report": {"shared_parameters": []},
}


def _write_fixture(tmp_path: Path, data: dict = None) -> Path:
    p = tmp_path / "params_to_optimize.json"
    p.write_text(json.dumps(data if data is not None else _MINIMAL_PARAMS, indent=2))
    return p


def test_generate_with_required_args_writes_file(tmp_path):
    from echolon.strategy.generators import generate_strategy_params

    params_file = _write_fixture(tmp_path)
    output = tmp_path / "strategy_params.py"

    result = generate_strategy_params(
        params_file_path=str(params_file),
        output_path=str(output),
        frequency="interday",
    )
    assert output.exists()
    assert result.success
    assert result.output_path == str(output)


def test_generate_returns_generation_result_dataclass(tmp_path):
    from echolon.strategy.generators import GenerationResult, generate_strategy_params

    params_file = _write_fixture(tmp_path)
    output = tmp_path / "strategy_params.py"
    result = generate_strategy_params(
        params_file_path=str(params_file),
        output_path=str(output),
    )
    assert isinstance(result, GenerationResult)
    assert hasattr(result, "success")
    assert hasattr(result, "output_path")
    assert hasattr(result, "corrections")
    assert hasattr(result, "message")


def test_missing_params_file_path_raises(tmp_path):
    from echolon.strategy.generators import generate_strategy_params

    with pytest.raises(TypeError):
        generate_strategy_params(output_path=str(tmp_path / "x.py"))


def test_missing_output_path_raises(tmp_path):
    from echolon.strategy.generators import generate_strategy_params

    params_file = _write_fixture(tmp_path)
    with pytest.raises(TypeError):
        generate_strategy_params(params_file_path=str(params_file))


def test_generated_file_uses_absolute_echolon_import(tmp_path):
    """Phase A2 — generated strategy_params.py must absolute-import
    parameter_architecture from echolon, not the broken `..parameter_architecture`."""
    from echolon.strategy.generators import generate_strategy_params

    params_file = _write_fixture(tmp_path)
    output = tmp_path / "strategy_params.py"
    generate_strategy_params(
        params_file_path=str(params_file),
        output_path=str(output),
    )
    content = output.read_text(encoding="utf-8")
    assert "from echolon.strategy.parameter_architecture import" in content
    assert "from ..parameter_architecture import" not in content


def test_generated_file_is_importable(tmp_path, monkeypatch):
    """End-to-end: generated file should exec + expose DEFAULT_PARAMS + optuna_search_space."""
    import importlib.util
    import sys

    from echolon.strategy.generators import generate_strategy_params

    params_file = _write_fixture(tmp_path)
    output = tmp_path / "strategy_params.py"
    generate_strategy_params(
        params_file_path=str(params_file),
        output_path=str(output),
    )
    spec = importlib.util.spec_from_file_location("_test_strategy_params", str(output))
    module = importlib.util.module_from_spec(spec)
    sys.modules["_test_strategy_params"] = module
    try:
        spec.loader.exec_module(module)
        assert hasattr(module, "DEFAULT_PARAMS")
        assert hasattr(module, "optuna_search_space")
        assert "entry_params" in module.DEFAULT_PARAMS
    finally:
        sys.modules.pop("_test_strategy_params", None)


def test_auto_correction_surfaces_in_result(tmp_path):
    """Over-cap TEMA period gets clamped; correction appears in result.corrections."""
    from echolon.strategy.generators import generate_strategy_params

    data = {
        "entry_parameters": {
            "calculation": {
                "tema_period": {
                    "type": "int",
                    "range": [30, 120],  # interday TEMA cap = 62
                    "default": 60,
                    "description": "TEMA period",
                    "ownership": "owner",
                },
            },
            "usage": {},
            "fixed": {},
        },
        "exit_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
        "risk_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
        "sizing_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
        "extraction_report": {"shared_parameters": []},
    }
    params_file = _write_fixture(tmp_path, data)
    output = tmp_path / "strategy_params.py"
    result = generate_strategy_params(
        params_file_path=str(params_file),
        output_path=str(output),
        frequency="interday",
    )
    assert result.success
    assert len(result.corrections) >= 1
    tema_corr = next((c for c in result.corrections if c["param"] == "tema_period"), None)
    assert tema_corr is not None
    assert tema_corr["cap"] == 62
    assert tema_corr["new_range"][1] == 62


def test_intraday_uses_larger_caps(tmp_path):
    """Same params + intraday frequency → TEMA cap is 500 (not 62), no correction needed."""
    from echolon.strategy.generators import generate_strategy_params

    data = {
        "entry_parameters": {
            "calculation": {
                "tema_period": {
                    "type": "int",
                    "range": [30, 120],
                    "default": 60,
                    "description": "TEMA period",
                    "ownership": "owner",
                },
            },
            "usage": {},
            "fixed": {},
        },
        "exit_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
        "risk_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
        "sizing_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
        "extraction_report": {"shared_parameters": []},
    }
    params_file = _write_fixture(tmp_path, data)
    output = tmp_path / "strategy_params.py"
    result = generate_strategy_params(
        params_file_path=str(params_file),
        output_path=str(output),
        frequency="intraday",
    )
    assert result.success
    tema_corr = next((c for c in result.corrections if c["param"] == "tema_period"), None)
    assert tema_corr is None  # 120 < 500, no clamp


def test_bad_json_returns_failure(tmp_path):
    """Malformed input should come back as GenerationResult(success=False), not raise."""
    from echolon.strategy.generators import generate_strategy_params

    bad = tmp_path / "params_to_optimize.json"
    bad.write_text("{this is not valid JSON", encoding="utf-8")
    output = tmp_path / "strategy_params.py"

    result = generate_strategy_params(
        params_file_path=str(bad),
        output_path=str(output),
    )
    assert result.success is False
    assert "JSON" in result.message or "json" in result.message.lower()
    assert not output.exists()


def test_missing_input_file_returns_failure(tmp_path):
    from echolon.strategy.generators import generate_strategy_params

    missing = tmp_path / "does_not_exist.json"
    output = tmp_path / "strategy_params.py"
    result = generate_strategy_params(
        params_file_path=str(missing),
        output_path=str(output),
    )
    assert result.success is False
    assert not output.exists()


def test_package_exports_public_symbols():
    """Phase A3 — public API importable from echolon.strategy.generators."""
    from echolon.strategy.generators import (
        GenerationResult,
        StrategyParamsGenerator,
        generate_strategy_params,
    )
    assert callable(generate_strategy_params)
    assert callable(StrategyParamsGenerator)
    assert GenerationResult is not None


def test_generate_creates_missing_output_parent_dir(tmp_path):
    """write_to_file must create the output's parent directory when missing.

    Iteration-loop workflows that wipe the strategy code directory between
    refinements would otherwise cause the next ``generate_strategy_params``
    call to fail with a misleading "Input file not found" message.
    """
    from echolon.strategy.generators import generate_strategy_params

    params_file = _write_fixture(tmp_path)
    nested_output_dir = tmp_path / "deep" / "nested" / "code"
    output = nested_output_dir / "strategy_params.py"
    assert not nested_output_dir.exists()

    result = generate_strategy_params(
        params_file_path=str(params_file),
        output_path=str(output),
        frequency="interday",
    )
    assert result.success, f"expected success, got: {result.message}"
    assert output.exists()


def test_missing_input_message_labels_input(tmp_path):
    """A missing input file must say 'Input file not found', not output."""
    from echolon.strategy.generators import generate_strategy_params

    missing = tmp_path / "does_not_exist.json"
    output = tmp_path / "strategy_params.py"
    result = generate_strategy_params(
        params_file_path=str(missing),
        output_path=str(output),
    )
    assert result.success is False
    assert "Input file not found" in result.message
