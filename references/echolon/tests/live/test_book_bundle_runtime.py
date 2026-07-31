from __future__ import annotations

import pytest

from echolon.live.book import load_bundle_strategy
from echolon.portfolio import PortfolioStrategy

from ._book_fixtures import CONSTRUCTOR, build_bundle

NOT_SELF_CONTAINED_SIGNAL = '''
from __future__ import annotations

from ._helpers import shared_helper  # relative import: not shippable

from echolon.signals import ScoreVector, SignalEngine


class BrokenSignal(SignalEngine):
    signal_id = "const_long_v1"
    family = "tsmom"

    def __init__(self) -> None:
        self.params = {}

    def compute(self, view):
        raise NotImplementedError
'''

WRONG_IDENTITY_SIGNAL = '''
from __future__ import annotations

from echolon.signals import ScoreVector, SignalEngine


class Imposter(SignalEngine):
    signal_id = "someone_else_v9"
    family = "tsmom"

    def __init__(self, *, strength: float = 1.0) -> None:
        self.params = {"strength": strength}

    def compute(self, view):
        return ScoreVector(
            signal_id=self.signal_id, family=self.family, date=view.date, scores={}
        )
'''


def test_load_bundle_strategy_assembles_engines_and_strategy(tmp_path):
    bundle_dir = build_bundle(tmp_path)

    runtime = load_bundle_strategy(bundle_dir)

    assert runtime.manifest.bundle_version == "1.0.0"
    assert [engine.signal_id for engine in runtime.engines] == ["const_long_v1"]
    assert runtime.engines[0].params == {"strength": 1.0}
    assert isinstance(runtime.strategy, PortfolioStrategy)
    assert runtime.rebalance_rule == "W-FRI"
    assert runtime.max_drawdown_pct_of_equity == 8.0
    assert runtime.expectations_path == bundle_dir / "expectations.json"


def test_load_bundle_strategy_never_mutates_the_bundle_dir(tmp_path):
    # Importing the signal module must not drop __pycache__ into the bundle:
    # S5 hash coverage is TOTAL, so any generated file breaks the next load.
    bundle_dir = build_bundle(tmp_path)

    load_bundle_strategy(bundle_dir)
    assert not list(bundle_dir.rglob("__pycache__"))
    load_bundle_strategy(bundle_dir)  # must still verify cleanly


def test_load_bundle_strategy_refuses_tampered_signal_file(tmp_path):
    bundle_dir = build_bundle(tmp_path)
    signal_path = bundle_dir / "signals" / "const_long_v1.py"
    signal_path.write_text(
        signal_path.read_text(encoding="utf-8").replace("strength: float = 1.0", "strength: float = 9.0"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        load_bundle_strategy(bundle_dir)


def test_load_bundle_strategy_refuses_signal_identity_mismatch(tmp_path):
    bundle_dir = build_bundle(tmp_path, signal_source=WRONG_IDENTITY_SIGNAL)

    with pytest.raises(ValueError, match="chain-of-custody"):
        load_bundle_strategy(bundle_dir)


def test_load_bundle_strategy_refuses_non_self_contained_signal(tmp_path):
    bundle_dir = build_bundle(tmp_path, signal_source=NOT_SELF_CONTAINED_SIGNAL)

    with pytest.raises(ValueError, match="not self-contained"):
        load_bundle_strategy(bundle_dir)


def test_load_bundle_strategy_refuses_research_sizing_mode(tmp_path):
    constructor = dict(CONSTRUCTOR)
    constructor["sizing_mode"] = "research"
    bundle_dir = build_bundle(tmp_path, constructor=constructor)

    with pytest.raises(ValueError, match="implementation"):
        load_bundle_strategy(bundle_dir)


def test_load_bundle_strategy_refuses_missing_rebalance_rule(tmp_path):
    constructor = dict(CONSTRUCTOR)
    del constructor["rebalance"]
    bundle_dir = build_bundle(tmp_path, constructor=constructor)

    with pytest.raises(ValueError, match="rebalance"):
        load_bundle_strategy(bundle_dir)


def test_load_bundle_strategy_refuses_missing_drawdown_risk(tmp_path):
    bundle_dir = build_bundle(tmp_path, risk={})

    with pytest.raises(ValueError, match="max_drawdown_pct_of_equity"):
        load_bundle_strategy(bundle_dir)
