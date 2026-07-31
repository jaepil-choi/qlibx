"""FLAG-4 round-trip pin: slot-grammar param name invariant.

Slot-grammar param names (e.g. `ranging_long_entry_quantile`) are NEVER
component-prefixed in the dict key, per the consumer's naming invariant
(T10 dissolution invariant). The codegen adds the component prefix ONLY in
the Optuna trial-suggestion name (for display/logging); the dict key that
the strategy reads at bar time retains the raw slot name.

This test file pins:
1. codegen emits Optuna name `entry_ranging_long_entry_quantile` AND
   dict key `ranging_long_entry_quantile` for a param declared in
   entry_parameters.usage as `ranging_long_entry_quantile`.
2. validate_params_sync passes (dict key == JSON key → no PRM-007/PRM-008).
3. resolve_via_replay recovers the raw dict key from the Optuna flat params.

No production change is made here. If any assertion fails, report actual
behavior — do NOT tune the test to pass.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from echolon.strategy.generators import generate_strategy_params
from echolon._internal.param_resolution import resolve_via_replay
from echolon.strategy.validators.params_sync import validate_params_sync


SLOT_PARAM = "ranging_long_entry_quantile"
OPTUNA_NAME = f"entry_{SLOT_PARAM}"
DICT_KEY = SLOT_PARAM


def _build_params_json(tmp_path: Path) -> Path:
    """Write a minimal params_to_optimize.json with the slot-grammar param."""
    data = {
        "entry_parameters": {
            "usage": {
                SLOT_PARAM: {
                    "range": [10, 90],
                    "default": 30,
                    "type": "int",
                    "description": "Entry quantile threshold (slot-grammar name)"
                }
            }
        }
    }
    p = tmp_path / "params_to_optimize.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def _generate_params_py(tmp_path: Path) -> Path:
    """Generate strategy_params.py from the slot-grammar params_to_optimize.json."""
    params_json = _build_params_json(tmp_path)
    out_py = tmp_path / "strategy_params.py"
    result = generate_strategy_params(
        params_file_path=str(params_json),
        output_path=str(out_py),
        frequency="interday",
    )
    assert result.success, f"generate_strategy_params failed: {result.message}"
    return out_py


def _load_module(py_path: Path):
    spec = importlib.util.spec_from_file_location("sp_flag4", py_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_codegen_emits_component_prefixed_optuna_name(tmp_path):
    """Generator must prefix the Optuna name but NOT the dict key.

    Generated line should be:
      entry_params["ranging_long_entry_quantile"] = trial.suggest_int(
          "entry_ranging_long_entry_quantile", 10, 90)
    """
    py_path = _generate_params_py(tmp_path)
    code = py_path.read_text(encoding="utf-8")
    assert f'trial.suggest_int("{OPTUNA_NAME}"' in code, \
        f"Expected Optuna name '{OPTUNA_NAME}' in generated code. Snippet:\n{code}"
    # Dict key must be the raw slot name (no prefix)
    assert f'entry_params["{DICT_KEY}"]' in code, \
        f"Expected dict key '{DICT_KEY}' in generated code. Snippet:\n{code}"


def test_codegen_does_not_double_prefix_dict_key(tmp_path):
    """The dict key must NOT be 'entry_ranging_long_entry_quantile' (double prefix)."""
    py_path = _generate_params_py(tmp_path)
    code = py_path.read_text(encoding="utf-8")
    # The dict key is the raw name; the doubled prefix would be the Optuna name as a key
    assert f'entry_params["entry_{SLOT_PARAM}"]' not in code, \
        f"Dict key must not be double-prefixed: found 'entry_{SLOT_PARAM}' as dict key"


def test_validate_params_sync_passes(tmp_path):
    """validate_params_sync must find no PRM-007/PRM-008 for slot-grammar params."""
    _generate_params_py(tmp_path)
    _build_params_json(tmp_path)  # ensure JSON is co-located
    report = validate_params_sync(tmp_path)
    assert not report.findings, (
        f"validate_params_sync reported findings for slot-grammar param:\n"
        + "\n".join(str(f) for f in report.findings)
    )


def test_resolve_via_replay_recovers_raw_key(tmp_path):
    """resolve_via_replay with the Optuna flat key recovers the raw dict key.

    The flat params dict uses the Optuna name (entry_ranging_long_entry_quantile=30);
    replay must return entry_params["ranging_long_entry_quantile"] = 30.
    """
    py_path = _generate_params_py(tmp_path)
    mod = _load_module(py_path)
    # Flat params use the Optuna name (as recorded in CSV/JSON artifacts)
    flat = {OPTUNA_NAME: 30}
    nested = resolve_via_replay(mod.optuna_search_space, flat)
    assert nested is not None, \
        f"resolve_via_replay returned None for flat={flat!r}"
    assert "entry_params" in nested, \
        f"Expected 'entry_params' in nested={nested!r}"
    assert DICT_KEY in nested["entry_params"], \
        f"Expected raw key '{DICT_KEY}' in entry_params={nested['entry_params']!r}"
    assert nested["entry_params"][DICT_KEY] == 30, \
        f"Expected value 30, got {nested['entry_params'][DICT_KEY]!r}"
