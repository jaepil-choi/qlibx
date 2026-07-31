"""PRM-006 — a param read via ``self.params['X']`` that is absent from
DEFAULT_PARAMS is a guaranteed bar-time KeyError. Catch it at preflight
(parameter_access, already composed into validate_strategy_full) instead of ~15
min into the backtest (the EXPLOITATION value-tune param-drop class:
``self.params['initial_capital']`` KeyError ×4 etc.).

DEFAULT_PARAMS is composed at RUNTIME (``framework.compose_default_strategy()``
plus cross-section copies), so the declared key set is LOADED via StrategyLoader,
not statically parsed; the ``self.params['X']`` READS are collected statically
(complete coverage, all code paths). Mirrors A1's IND-002 (used-but-undeclared),
for parameters.
"""
import shutil
from pathlib import Path

from echolon.strategy.validators.parameter_access import validate_parameter_access

_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "baselines" / "aluminum_baseline"

_PARAMS_PY = (
    "DEFAULT_PARAMS = {\n"
    "    'entry_params': {'present': 1, 'printlog': False},\n"
    "    'exit_params': {'shared_x': 2},\n"
    "    'risk_params': {},\n"
    "    'sizer_params': {},\n"
    "}\n"
)


def _write(tmp_path, entry_body, params_py=_PARAMS_PY):
    (tmp_path / "strategy_params.py").write_text(params_py, encoding="utf-8")
    (tmp_path / "entry.py").write_text(
        "class Entry:\n    def __init__(self):\n" + entry_body, encoding="utf-8"
    )


def _prm006(report):
    return [f for f in report.findings if f.code == "PRM-006"]


def test_missing_param_subscript_flagged_prm006(tmp_path):
    _write(tmp_path, "        self.a = self.params['present']\n"
                     "        self.b = self.params['absent_xyz']\n")
    found = _prm006(validate_parameter_access(tmp_path))
    assert len(found) == 1
    assert "absent_xyz" in (found[0].message + str(found[0].context))


def test_all_present_params_no_prm006(tmp_path):
    _write(tmp_path, "        self.a = self.params['present']\n")
    assert not _prm006(validate_parameter_access(tmp_path))


def test_cross_section_key_not_flagged_union(tmp_path):
    # 'shared_x' lives in exit_params but is read in entry.py — the union of all
    # sections means "declared somewhere", so no false positive.
    _write(tmp_path, "        self.a = self.params['shared_x']\n")
    assert not _prm006(validate_parameter_access(tmp_path))


def test_nonconstant_key_not_flagged(tmp_path):
    _write(tmp_path, "        k = 'present'\n        self.a = self.params[k]\n")
    assert not _prm006(validate_parameter_access(tmp_path))


def test_unloadable_params_skips_check(tmp_path):
    # If DEFAULT_PARAMS can't be loaded, skip the check (no PRM-006, no crash).
    _write(tmp_path, "        self.a = self.params['anything']\n",
           params_py="raise RuntimeError('boom')\n")
    assert not _prm006(validate_parameter_access(tmp_path))


def test_real_fixture_no_prm006():
    # The correct aluminum baseline declares every param it reads.
    found = _prm006(validate_parameter_access(_FIXTURE))
    assert not found, [f.message for f in found]


def test_real_fixture_with_bogus_param_read_flagged(tmp_path):
    dst = tmp_path / "strat"
    shutil.copytree(_FIXTURE, dst, ignore=shutil.ignore_patterns("__pycache__"))
    entry = dst / "entry.py"
    entry.write_text(
        entry.read_text(encoding="utf-8")
        + "\n_BOGUS = lambda self: self.params['totally_not_a_real_param']\n",
        encoding="utf-8",
    )
    found = _prm006(validate_parameter_access(dst))
    assert any("totally_not_a_real_param" in (f.message + str(f.context)) for f in found)
