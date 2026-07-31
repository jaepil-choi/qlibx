"""Golden regression tests for the trial→deployed parameter resolution fix.

The fixture is SYNTHETIC (public-repo safe — no live strategy parameterization)
but structurally faithful: it reproduces the four defect mechanisms the
incident proved against production artifacts:

  1. Family-A flat keys whose canonical names ALREADY carry the component
     prefix + Family-B double-prefixed default twins — the strip-once mappers
     orphan the optimized value and deliver the default;
  2. an in-function SHARED sizer copy of an exit value — unrecoverable from
     the flat dict by any name-based merge (the copy happens inside
     optuna_search_space);
  3. a BARE optuna key (silently dropped by the live mapper; routed to a
     top-level extra by the backtest mapper) with a same-destination Family-B
     twin;
  4. an int distribution whose value round-trips through CSV/pandas as float —
     replay must re-cast.

Fixture ground truth (synthetic values):
  exit_down_stop_mult: default 1.0 deployed by the legacy mapping, optimized
  1.444 orphaned; trailing_mult: default 3.0, optimized 2.222 bare-keyed;
  alpha_period: optimized 21 (arrives as 21.0).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from echolon._internal.param_resolution import resolve_via_replay
from echolon._internal.strategy_files import (
    ResolvedParams,
    load_resolved_params,
    save_resolved_params,
    trial_params_fingerprint,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "param_resolution" / "synthetic_s1"

OPTIMIZED_STOP = 1.444
OPTIMIZED_TRAIL = 2.222


def _load_fixture():
    """Load the synthetic strategy_params module + its trial JSON."""
    spec = importlib.util.spec_from_file_location(
        "sp_synthetic", FIXTURE / "strategy_params.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    trial = json.loads((FIXTURE / "selected_robust_trial.json").read_text())
    return module, trial


# ---- resolve_via_replay: the authoritative resolver -------------------------


def test_replay_recovers_orphaned_canonical_prefixed_values():
    sp, trial = _load_fixture()
    nested = resolve_via_replay(sp.optuna_search_space, trial["params"])
    assert nested is not None
    assert nested["exit_params"]["exit_down_stop_mult"] == OPTIMIZED_STOP
    assert nested["entry_params"]["entry_gate_threshold"] == pytest.approx(0.777)
    # int distribution round-trips through pandas as float — replay re-casts
    assert nested["entry_params"]["alpha_period"] == 21
    assert isinstance(nested["entry_params"]["alpha_period"], int)


def test_replay_recovers_shared_sizer_copy():
    """The in-function shared copy exists ONLY in the replay — the flat dict's
    sizer twin carries the stale default, so replaying the search space is the
    only way to recover the optimized value (no name-based merge can)."""
    sp, trial = _load_fixture()
    nested = resolve_via_replay(sp.optuna_search_space, trial["params"])
    assert nested["sizer_params"]["exit_down_stop_mult"] == OPTIMIZED_STOP


def test_replay_recovers_bare_optuna_key():
    sp, trial = _load_fixture()
    nested = resolve_via_replay(sp.optuna_search_space, trial["params"])
    assert nested["sizer_params"]["trailing_mult"] == OPTIMIZED_TRAIL
    assert nested["exit_params"]["exit_atr_period"] == 17


def test_replay_returns_none_on_missing_suggested_name():
    sp, trial = _load_fixture()
    crippled = {k: v for k, v in trial["params"].items() if k != "exit_atr_period"}
    assert resolve_via_replay(sp.optuna_search_space, crippled) is None


def test_replay_returns_none_on_broken_search_space():
    def exploding(_trial):
        raise RuntimeError("boom")

    assert resolve_via_replay(exploding, {"x": 1}) is None


def test_replay_canonicalizes_categorical_types():
    """CSV round-trips deliver 10.0 / 1.0 where the optimizer had int 10 /
    True; cross-type equality (10.0 in [10, 20]) must not leak the float
    through — the canonical choice object is restored."""

    def space(trial):
        return {
            "x_params": {
                "n": trial.suggest_categorical("n", [10, 20]),
                "flag": trial.suggest_categorical("flag", [True, False]),
                "label": trial.suggest_categorical("label", ["a", "b"]),
            }
        }

    nested = resolve_via_replay(space, {"n": 10.0, "flag": 1.0, "label": "b"})
    assert nested["x_params"]["n"] == 10 and isinstance(nested["x_params"]["n"], int)
    assert nested["x_params"]["flag"] is True
    assert nested["x_params"]["label"] == "b"


# ---- best_trial resolution: authoritative-only, hard-fail (no lossy mapper) --


def test_legacy_strip_once_mapper_is_deleted():
    """The lossy `_map_optuna_params` must no longer exist — it silently
    orphaned prefixed-canonical params and dropped shared copies."""
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    assert not hasattr(BacktestRunner, "_map_optuna_params")


def test_on_demand_replay_recovers_the_optimized_vector_without_artifact():
    """`_replay_strategy_params` reproduces the optimizer-exact vector from the
    dir's OWN optuna_search_space — no resolved_params.json needed. This is the
    floor that lets an artifact-less dir resolve correctly instead of falling
    back to the (deleted) lossy mapping."""
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    _sp, trial = _load_fixture()
    nested = BacktestRunner._replay_strategy_params(
        trial["params"], strategy_code_dir=str(FIXTURE)
    )
    assert nested is not None
    # the exact values the legacy strip-once mapper used to lose:
    assert nested["exit_params"]["exit_down_stop_mult"] == OPTIMIZED_STOP
    assert nested["sizer_params"]["trailing_mult"] == OPTIMIZED_TRAIL


def test_replay_returns_none_when_search_space_unloadable(tmp_path):
    """A dir with no loadable optuna_search_space → None (caller hard-fails)."""
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    assert BacktestRunner._replay_strategy_params(
        {"x": 1}, strategy_code_dir=str(tmp_path)
    ) is None


def test_resolve_optimized_params_prefers_artifact(tmp_path):
    """When a sha-verified resolved_params.json is present it wins (provenance
    fast-path), even over replay."""
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    _sp, trial = _load_fixture()
    (tmp_path / "selected_robust_trial.json").write_text(json.dumps(trial))
    components = {"entry_params": {"sentinel": 1}}
    save_resolved_params(
        tmp_path, components,
        provenance={"trial_number": trial["trial_number"],
                    "trial_params_sha256": trial_params_fingerprint(trial["params"])},
    )
    got = BacktestRunner._resolve_optimized_params(
        str(tmp_path / "selected_robust_trial.json"), trial["params"],
        strategy_code_dir=str(tmp_path),
    )
    assert got == {"entry_params": {"sentinel": 1}}  # artifact, not replay


def test_resolve_optimized_params_falls_through_to_replay(tmp_path):
    """No artifact but a loadable search space → on-demand replay vector."""
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    _sp, trial = _load_fixture()
    got = BacktestRunner._resolve_optimized_params(
        str(FIXTURE / "selected_robust_trial.json"), trial["params"],
        strategy_code_dir=str(FIXTURE),
    )
    assert got["exit_params"]["exit_down_stop_mult"] == OPTIMIZED_STOP


def test_resolve_optimized_params_hard_fails_when_unresolvable(tmp_path):
    """No artifact AND no loadable search space → PRM-005, never a lossy guess."""
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    with pytest.raises(Exception) as exc:
        BacktestRunner._resolve_optimized_params(
            str(tmp_path / "selected_robust_trial.json"), {"x": 1},
            strategy_code_dir=str(tmp_path),
        )
    assert "PRM-005" in str(exc.value)


def test_prm005_is_documented():
    """get_error_doc('PRM-005') must resolve (registry + markdown) so the
    hard-fail's remediation is available to agents/operators."""
    from echolon.native.errors import get_error_doc

    doc = get_error_doc("PRM-005")
    assert doc.code == "PRM-005"
    assert doc.what and doc.fix


# ---- artifact IO ------------------------------------------------------------


def test_resolved_params_roundtrip(tmp_path):
    components = {"entry_params": {"a": 1}, "exit_params": {"b": 2.5}}
    provenance = {"trial_number": 7, "trial_params_sha256": "ab" * 32}
    out = save_resolved_params(tmp_path, components, provenance=provenance)
    assert out.name == "resolved_params.json"
    loaded = load_resolved_params(tmp_path)
    assert isinstance(loaded, ResolvedParams)
    assert loaded.version == 1
    assert loaded.components == components
    assert loaded.provenance == provenance


def test_load_resolved_params_missing_returns_none(tmp_path):
    assert load_resolved_params(tmp_path) is None


def test_load_resolved_params_unknown_version_raises(tmp_path):
    (tmp_path / "resolved_params.json").write_text(json.dumps({"version": 2}))
    with pytest.raises(ValueError, match="version"):
        load_resolved_params(tmp_path)


def test_fingerprint_is_numpy_stable():
    np = pytest.importorskip("numpy")
    py_side = {"exit_atr_period": 17.0, "x": 1.444}
    np_side = {"exit_atr_period": np.float64(17.0), "x": np.float64(1.444)}
    assert trial_params_fingerprint(py_side) == trial_params_fingerprint(np_side)
    assert trial_params_fingerprint(py_side) != trial_params_fingerprint({"x": 1.0})


# ---- exporter: TrialSelector companion emission ------------------------------


def _make_selector(tmp_path, search_space_fn, default_params):
    """Minimal TrialSelector: a tiny synthetic trials CSV satisfies __init__."""
    import pandas as pd

    from echolon.backtest.optimization.select_best_trial import TrialSelector

    csv_path = tmp_path / "optimization_trials.csv"
    pd.DataFrame(
        {
            "number": [0, 1],
            "values_0": [1.0, 1.2],
            "values_1": [-10.0, -9.0],
            "values_2": [12.0, 14.0],
            "params_entry_alpha_period": [12, 21],
        }
    ).to_csv(csv_path, index=False)
    return TrialSelector(
        trial_data_path=str(csv_path),
        output_dir=str(tmp_path / "out"),
        default_params=default_params,
        strategy_code_dir=tmp_path / "code",
        search_space_fn=search_space_fn,
    )


def test_exporter_writes_sha_matched_resolved_artifact(tmp_path):
    sp, trial = _load_fixture()
    selector = _make_selector(tmp_path, sp.optuna_search_space, sp.DEFAULT_PARAMS)
    selector._export_resolved_params(
        {"trial_number": trial["trial_number"], "params": trial["params"]}
    )
    resolved = load_resolved_params(tmp_path / "code")
    assert resolved is not None
    assert resolved.provenance["trial_number"] == trial["trial_number"]
    assert resolved.provenance["trial_params_sha256"] == trial_params_fingerprint(
        trial["params"]
    )
    assert resolved.components["exit_params"]["exit_down_stop_mult"] == OPTIMIZED_STOP


def test_exporter_without_search_space_fn_discards_stale_artifact(tmp_path):
    """A trial save WITHOUT companion export must remove any older companion —
    a leftover artifact must never pair with a newer trial file."""
    sp, trial = _load_fixture()
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "resolved_params.json").write_text(
        json.dumps({"version": 1, "components": {}, "provenance": {}})
    )
    selector = _make_selector(tmp_path, None, sp.DEFAULT_PARAMS)
    selector._export_resolved_params({"trial_number": 1, "params": trial["params"]})
    assert load_resolved_params(code_dir) is None


def test_exporter_replay_failure_discards_stale_and_does_not_raise(tmp_path):
    sp, _ = _load_fixture()
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "resolved_params.json").write_text(
        json.dumps({"version": 1, "components": {}, "provenance": {}})
    )
    selector = _make_selector(tmp_path, sp.optuna_search_space, sp.DEFAULT_PARAMS)
    selector._export_resolved_params({"trial_number": 1, "params": {}})  # replay fails
    assert load_resolved_params(code_dir) is None


# ---- WFA runner: the stale-read regression guard -----------------------------


def test_wfa_selector_writes_where_run_best_trial_reads(tmp_path):
    """THE stale-read incident pin: the per-window TrialSelector must write its
    selection to paths.strategy_code_dir (what run_best_trial reads), never to
    TrialSelector's env-based default (a different dir under run isolation —
    proven incident: 5 windows, 5 selected trials, ONE identical executed
    vector from the stale file at the read path)."""
    import pandas as pd

    from echolon.backtest.wfa.runner import WFARunner

    csv_path = tmp_path / "optimization_trials.csv"
    pd.DataFrame(
        {
            "number": [0],
            "values_0": [1.0],
            "values_1": [-10.0],
            "values_2": [12.0],
            "params_entry_alpha_period": [21],
        }
    ).to_csv(csv_path, index=False)

    runner = WFARunner.__new__(WFARunner)  # bypass heavy __init__; test the seam
    runner._paths = SimpleNamespace(strategy_code_dir=tmp_path / "run_code_dir")
    runner.config = SimpleNamespace(max_drawdown_threshold=15.0)
    runner.selection_score_fn = None

    selector = runner._build_selector(
        trials_csv_path=csv_path,
        window_dir=tmp_path / "window",
        default_params={},
        apply_shared_params_fn=None,
        param_classifications=None,
        search_space_fn=None,
    )
    assert selector.selected_trial_output_dir == tmp_path / "run_code_dir"


# ---- consumer: BacktestRunner gate -------------------------------------------


def _stage_pair(tmp_path, sp, trial):
    """Stage a matched trial + resolved pair the way the exporter would."""
    (tmp_path / "selected_robust_trial.json").write_text(json.dumps(trial))
    nested = resolve_via_replay(sp.optuna_search_space, trial["params"])
    save_resolved_params(
        tmp_path,
        nested,
        provenance={
            "trial_number": trial["trial_number"],
            "trial_params_sha256": trial_params_fingerprint(trial["params"]),
        },
    )


def test_consumer_prefers_sha_matched_resolved_artifact(tmp_path):
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    sp, trial = _load_fixture()
    _stage_pair(tmp_path, sp, trial)
    params_path = str(tmp_path / "selected_robust_trial.json")
    effective = BacktestRunner._resolved_strategy_params(params_path, trial["params"])
    assert effective is not None
    assert effective["exit_params"]["exit_down_stop_mult"] == OPTIMIZED_STOP
    # the resolved path carries no orphan keys
    assert "down_stop_mult" not in effective["exit_params"]


def test_consumer_falls_back_on_provenance_mismatch(tmp_path):
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    sp, trial = _load_fixture()
    _stage_pair(tmp_path, sp, trial)
    # Simulate a STALE pair: trial params changed after the artifact was written
    mutated = dict(trial["params"])
    mutated["exit_atr_period"] = 11.0
    effective = BacktestRunner._resolved_strategy_params(
        str(tmp_path / "selected_robust_trial.json"), mutated
    )
    assert effective is None


def test_consumer_falls_back_on_missing_provenance_sha(tmp_path):
    """The sha is load-bearing: an artifact that cannot prove it pairs with
    THIS trial file is never trusted (a hand-edited / truncated artifact must
    not bypass the gate)."""
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    sp, trial = _load_fixture()
    (tmp_path / "selected_robust_trial.json").write_text(json.dumps(trial))
    save_resolved_params(
        tmp_path,
        {"entry_params": {"stale": True}},
        provenance={"trial_number": 99},  # no sha
    )
    effective = BacktestRunner._resolved_strategy_params(
        str(tmp_path / "selected_robust_trial.json"), trial["params"]
    )
    assert effective is None


def test_consumer_absent_artifact_returns_none(tmp_path):
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    (tmp_path / "selected_robust_trial.json").write_text("{}")
    assert (
        BacktestRunner._resolved_strategy_params(
            str(tmp_path / "selected_robust_trial.json"), {"x": 1}
        )
        is None
    )


def test_consumer_malformed_artifact_never_raises(tmp_path):
    from echolon.backtest.engine.backtest_runner import BacktestRunner

    (tmp_path / "resolved_params.json").write_text("{not json")
    assert (
        BacktestRunner._resolved_strategy_params(
            str(tmp_path / "selected_robust_trial.json"), {"x": 1}
        )
        is None
    )
