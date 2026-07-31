"""params_to_optimize.json <-> strategy_params.py consistency (PRM-007 / PRM-008).

Both artifacts are consumed downstream: the ``.json`` ``calculation``/``usage``
``range``s feed the indicator-calc + Optuna search; ``strategy_params.py``'s
``optuna_search_space`` feeds the backtest. An EXPLOITATION value-tune edits
``.py`` directly (and ``.json`` when an indicator range changes) — if they drift,
the search ranges silently disagree, or a ``.json``-declared param is dropped
from ``.py``.

Pure static AST on both files (no runtime load, no generator). Matched by the
``optuna_search_space`` DICT KEY (``entry_params["atr_14_period"]``), which equals
the ``.json`` key — NOT the optuna trial name (``"entry_atr_14_period"``), which
is inconsistently prefixed. Conservative: skip non-constant ranges; skip when a
file is absent / unparseable; PRM-008 checks the UNION of all component dicts so a
shared/cross-component param is never falsely flagged.

- PRM-007: a ``.json`` calculation/usage ``range`` differs from the matching
  ``trial.suggest_int/float`` range in ``optuna_search_space``.
- PRM-008: a param declared in ``.json`` (calculation/usage/fixed) is absent from
  ``optuna_search_space`` entirely (a drop).
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from echolon.strategy.validators import Finding, Report

# .json section -> optuna_search_space dict variable name.
_COMPONENT_MAP = {
    "entry_parameters": "entry_params",
    "exit_parameters": "exit_params",
    "risk_parameters": "risk_params",
    "sizing_parameters": "sizer_params",
}

_SUGGEST_RANGE_FNS = {"suggest_int", "suggest_float"}


def _find_params_json(strategy_dir: Path):
    """``params_to_optimize.json`` lives in the code dir or its sibling
    ``strategy/`` dir (workspace layout: current/code/ + current/strategy/).
    Returns the path or None."""
    for cand in (
        strategy_dir / "params_to_optimize.json",
        strategy_dir.parent / "strategy" / "params_to_optimize.json",
    ):
        if cand.exists():
            return cand
    return None


def _const(node):
    return node.value if isinstance(node, ast.Constant) else None


def _parse_optuna_search_space(py_path: Path):
    """Return ``{py_dict_name: {key: ('range', (lo, hi)) | ('range', None) |
    ('fixed', value) | ('other', None)}}`` parsed from the ``optuna_search_space``
    function, or None if it can't be parsed.

    Two assignment forms inside the function:
      ``X_params["key"] = trial.suggest_int/float("name", lo, hi)``  -> ('range', (lo, hi))
      ``X_params["key"] = <constant>``                               -> ('fixed', value)
    Non-constant ranges record ('range', None) (presence known, value uncomparable).
    """
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    func = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "optuna_search_space"),
        None,
    )
    if func is None:
        return None
    out: dict = {}
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not (
            isinstance(tgt, ast.Subscript)
            and isinstance(tgt.value, ast.Name)
            and isinstance(_const(tgt.slice), str)
        ):
            continue
        dict_name = tgt.value.id
        key = tgt.slice.value
        val = node.value
        if (
            isinstance(val, ast.Call)
            and isinstance(val.func, ast.Attribute)
            and val.func.attr in _SUGGEST_RANGE_FNS
            and len(val.args) >= 3
        ):
            lo, hi = _const(val.args[1]), _const(val.args[2])
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                out.setdefault(dict_name, {})[key] = ("range", (lo, hi))
            else:
                out.setdefault(dict_name, {})[key] = ("range", None)
        elif isinstance(val, ast.Constant):
            out.setdefault(dict_name, {})[key] = ("fixed", val.value)
        else:
            out.setdefault(dict_name, {})[key] = ("other", None)
    return out


def validate_params_sync(strategy_dir: "Path | str") -> Report:
    """Cross-check params_to_optimize.json against strategy_params.py's
    optuna_search_space (PRM-007 range drift, PRM-008 dropped param). Returns an
    empty Report (skips) when either file is absent/unparseable."""
    report = Report()
    strategy_dir = Path(strategy_dir)
    json_path = _find_params_json(strategy_dir)
    py_path = strategy_dir / "strategy_params.py"
    if json_path is None or not py_path.exists():
        return report
    try:
        jdata = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return report
    py = _parse_optuna_search_space(py_path)
    if py is None or not isinstance(jdata, dict):
        return report

    # PRM-008 checks the UNION of all component dicts (a shared/cross-component
    # param declared once in its owner's section must not false-positive).
    all_py_keys = set().union(*[set(d) for d in py.values()]) if py else set()

    for section, dict_name in _COMPONENT_MAP.items():
        comp = jdata.get(section)
        if not isinstance(comp, dict):
            continue
        py_keys = py.get(dict_name, {})

        # PRM-008: a .json-declared param absent from optuna_search_space entirely.
        for sub in ("calculation", "usage", "fixed"):
            for key in (comp.get(sub) or {}):
                if key not in all_py_keys:
                    report.add(Finding(
                        code="PRM-008",
                        message=(
                            f"Param {key!r} is declared in params_to_optimize.json "
                            f"({section}.{sub}) but is absent from optuna_search_space "
                            f"in strategy_params.py — the two are out of sync (drop)."
                        ),
                        context={"param": key, "section": section, "sub": sub},
                    ))

        # PRM-007: a searched range must match between .json and optuna_search_space.
        for sub in ("calculation", "usage"):
            for key, spec in (comp.get(sub) or {}).items():
                jrange = spec.get("range") if isinstance(spec, dict) else None
                if not (isinstance(jrange, list) and len(jrange) == 2):
                    continue
                kind, pyval = py_keys.get(key, (None, None))
                if kind != "range" or pyval is None:
                    continue  # not searched in .py, or non-constant -> skip (conservative)
                if [pyval[0], pyval[1]] != [jrange[0], jrange[1]]:
                    report.add(Finding(
                        code="PRM-007",
                        message=(
                            f"Search range for {key!r} differs: params_to_optimize.json "
                            f"({section}.{sub}) = {jrange}, but optuna_search_space "
                            f"({dict_name}) = [{pyval[0]}, {pyval[1]}]. Edit both in sync."
                        ),
                        context={
                            "param": key,
                            "json_range": jrange,
                            "py_range": [pyval[0], pyval[1]],
                            "section": section,
                        },
                    ))
    return report
