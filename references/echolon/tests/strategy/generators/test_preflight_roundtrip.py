"""End-to-end: a fully-scaffolded strategy passes preflight.

Acts as the canary for Part A. Any future drift in a generator that
violates preflight's STR-*/PRM-*/IND-* contract will surface here.
"""
import json
from pathlib import Path

from echolon.strategy.generators import (
    generate_entry,
    generate_exit,
    generate_risk,
    generate_sizer,
    generate_strategy,
    generate_strategy_params,
)
from echolon.strategy.preflight import preflight


def _write_minimal_strategy_indicator_list(strategy_dir: Path) -> None:
    """Empty flat-dict — preflight validates shape, not content."""
    (strategy_dir / "strategy_indicator_list.json").write_text(
        json.dumps({}, indent=2),
        encoding="utf-8",
    )


def test_scaffolded_strategy_passes_preflight(tmp_path: Path):
    # 1. Scaffold the 4 components + coordinator.
    generate_entry(strategy_dir=tmp_path)
    generate_exit(strategy_dir=tmp_path)
    generate_risk(strategy_dir=tmp_path)
    generate_sizer(strategy_dir=tmp_path)
    generate_strategy(strategy_dir=tmp_path)

    # 2. Add the non-scaffolded required files.
    _write_minimal_strategy_indicator_list(tmp_path)

    # 3. Generate strategy_params.py via generate_strategy_params.
    #
    #    Input: an empty params_to_optimize.json (all 4 component sections
    #    absent → each ComponentParameterTemplate.define_parameters() returns []).
    #    Output: DEFAULT_PARAMS with 4 keys, each sub-dict seeded with
    #    {'printlog': False} by ComponentParameterTemplate.get_default_structure().
    #    This satisfies PRM-001 and PRM-002 without any strategy-specific params.
    params_json = tmp_path / "params_to_optimize.json"
    params_json.write_text(json.dumps({}, indent=2), encoding="utf-8")

    result = generate_strategy_params(
        params_file_path=str(params_json),
        output_path=str(tmp_path / "strategy_params.py"),
        frequency="interday",
    )
    assert result.success, (
        f"generate_strategy_params failed before preflight could run:\n{result.message}"
    )

    # 4. Preflight must not raise.
    preflight(tmp_path)
