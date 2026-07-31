"""PRM-007 / PRM-008 — params_to_optimize.json <-> strategy_params.py sync.

Both files are consumed downstream: the ``.json`` ``calculation``/``usage``
ranges feed the indicator-calc + Optuna search; ``strategy_params.py``'s
``optuna_search_space`` feeds the backtest. An EXPLOITATION value-tune EDITS
``.py`` directly (and ``.json`` when an indicator range changes) — if they drift,
the indicator-calc searches one range while the backtest optimizes another
(silent) or a ``.json``-declared param is missing from ``.py`` (drop).

Matching is by the **dict key** in ``optuna_search_space`` (``entry_params["atr_14_period"]``)
which equals the ``.json`` key — NOT the optuna trial name
(``"entry_atr_14_period"``) which is inconsistently prefixed. Pure static AST on
both files; conservative (skip non-constant ranges, skip when a file is absent).

- PRM-007: a ``.json`` calculation/usage ``range`` differs from the matching
  ``trial.suggest_int/float`` range in ``optuna_search_space``.
- PRM-008: a param declared in ``.json`` is absent from ``optuna_search_space``.
"""
import json as _json

from echolon.strategy.validators.params_sync import validate_params_sync


_PY_OK = '''
import optuna
def optuna_search_space(trial):
    entry_params = {}
    entry_params["atr_14_period"] = trial.suggest_int("entry_atr_14_period", 10, 20)
    entry_params["thr"] = trial.suggest_float("entry_thr", 1.0, 2.5)
    entry_params["aroonosc_period"] = 16
    return {"entry_params": entry_params}
'''

_JSON_OK = {
    "entry_parameters": {
        "calculation": {"atr_14_period": {"range": [10, 20], "type": "int"}},
        "usage": {"thr": {"range": [1.0, 2.5], "type": "float"}},
        "fixed": {"aroonosc_period": {"value": 16}},
    },
    "exit_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
    "risk_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
    "sizing_parameters": {"calculation": {}, "usage": {}, "fixed": {}},
    "extraction_report": {},
}


def _setup(tmp_path, py_body, json_data):
    code = tmp_path / "code"; code.mkdir()
    strat = tmp_path / "strategy"; strat.mkdir()
    (code / "strategy_params.py").write_text(py_body, encoding="utf-8")
    (strat / "params_to_optimize.json").write_text(_json.dumps(json_data), encoding="utf-8")
    return code


def _codes(report):
    return [f.code for f in report.findings]


def test_in_sync_no_findings(tmp_path):
    code = _setup(tmp_path, _PY_OK, _JSON_OK)
    assert validate_params_sync(code).findings == []


def test_range_drift_flagged_prm007(tmp_path):
    bad = _json.loads(_json.dumps(_JSON_OK))
    bad["entry_parameters"]["calculation"]["atr_14_period"]["range"] = [10, 30]  # .py is [10,20]
    code = _setup(tmp_path, _PY_OK, bad)
    found = [f for f in validate_params_sync(code).findings if f.code == "PRM-007"]
    assert len(found) == 1
    assert "atr_14_period" in (found[0].message + str(found[0].context))


def test_usage_range_drift_flagged(tmp_path):
    bad = _json.loads(_json.dumps(_JSON_OK))
    bad["entry_parameters"]["usage"]["thr"]["range"] = [1.0, 9.9]  # .py is [1.0, 2.5]
    code = _setup(tmp_path, _PY_OK, bad)
    assert any(c == "PRM-007" for c in _codes(validate_params_sync(code)))


def test_param_in_json_absent_from_py_flagged_prm008(tmp_path):
    bad = _json.loads(_json.dumps(_JSON_OK))
    bad["entry_parameters"]["fixed"]["dropped_param"] = {"value": 5}  # not in .py
    code = _setup(tmp_path, _PY_OK, bad)
    found = [f for f in validate_params_sync(code).findings if f.code == "PRM-008"]
    assert len(found) == 1
    assert "dropped_param" in (found[0].message + str(found[0].context))


def test_missing_json_skips(tmp_path):
    code = tmp_path / "code"; code.mkdir()
    (code / "strategy_params.py").write_text(_PY_OK, encoding="utf-8")
    assert validate_params_sync(code).findings == []


def test_nonconstant_range_skipped(tmp_path):
    py = (
        "def optuna_search_space(trial):\n"
        "    lo = 10\n"
        "    entry_params = {}\n"
        "    entry_params['atr_14_period'] = trial.suggest_int('entry_atr_14_period', lo, 20)\n"
        "    return {'entry_params': entry_params}\n"
    )
    bad = _json.loads(_json.dumps(_JSON_OK))
    bad["entry_parameters"]["calculation"]["atr_14_period"]["range"] = [99, 100]
    bad["entry_parameters"]["usage"] = {}
    bad["entry_parameters"]["fixed"] = {}
    code = _setup(tmp_path, py, bad)
    # non-constant low -> can't compare -> no PRM-007 (conservative, no false positive)
    assert not any(c == "PRM-007" for c in _codes(validate_params_sync(code)))


def test_json_sibling_of_code_dir_is_found(tmp_path):
    # The .json lives in ../strategy/ relative to the code dir validate_strategy_full
    # receives — the in-sync case proves the sibling lookup works.
    code = _setup(tmp_path, _PY_OK, _JSON_OK)
    assert code.name == "code" and (code.parent / "strategy" / "params_to_optimize.json").exists()
    assert validate_params_sync(code).findings == []
