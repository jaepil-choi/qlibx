"""Strategy-layer errors must use catalog codes, not bare Python exceptions."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from echolon.errors import EchelonError, StrategyStructureError


def test_loader_missing_file_raises_str_001(tmp_path: Path):
    """Loader should raise STR-001 when a required strategy file is missing."""
    # Create a 5-file directory (missing strategy_indicator_list.json)
    for name in ("entry.py", "exit.py", "risk.py", "sizer.py",
                 "strategy_params.py"):
        (tmp_path / name).write_text("# stub", encoding="utf-8")

    # Import the public loader — match the real name discovered in Step 1.
    from echolon.strategy import loader as loader_mod
    load_fn = getattr(loader_mod, "load_strategy_from_dir", None) or \
              getattr(loader_mod, "load_strategy", None)
    assert load_fn is not None, "strategy loader entry point not found"

    with pytest.raises(StrategyStructureError) as exc:
        load_fn(tmp_path)

    assert exc.value.code == "STR-001"
    assert "strategy_indicator_list.json" in str(exc.value)


def test_loader_missing_class_raises_str_002(tmp_path: Path):
    """Loader should raise STR-002 when a required class name is not exported."""
    for name in ("exit.py", "risk.py", "sizer.py", "strategy_params.py"):
        (tmp_path / name).write_text("# stub", encoding="utf-8")
    (tmp_path / "strategy_indicator_list.json").write_text("{}", encoding="utf-8")
    (tmp_path / "entry.py").write_text(dedent("""
        class NotEntry:
            pass
    """))

    from echolon.strategy import loader as loader_mod
    load_fn = getattr(loader_mod, "load_strategy_from_dir", None) or \
              getattr(loader_mod, "load_strategy", None)
    assert load_fn is not None

    with pytest.raises(StrategyStructureError) as exc:
        load_fn(tmp_path)

    assert exc.value.code == "STR-002"


def test_component_not_implemented_raises_str_003():
    """A component subclass without the required abstract method raises STR-003."""
    from echolon.strategy.component import EntryComponent

    class BadEntry(EntryComponent):
        pass  # does not implement the required method

    bad = BadEntry.__new__(BadEntry)  # skip __init__ for unit test

    # Find the first method the abstract contract requires.
    # Inspect EntryComponent to learn the abstract method name.
    # EntryComponent exposes stub methods that raise STR-003; call generate_signal
    # directly to exercise the catalog raise from the BaseComponent stub.
    with pytest.raises(EchelonError) as exc:
        bad.generate_signal()
    assert exc.value.code == "STR-003"


def test_parameter_missing_printlog_raises_prm_001():
    """Parameter validator raises PRM-001 when 'printlog' is missing."""
    from echolon.strategy.parameter_architecture import validate_component_params

    with pytest.raises(EchelonError) as exc:
        validate_component_params(
            component_key="entry_params",
            params={"threshold": 50},  # missing 'printlog'
        )

    assert exc.value.code == "PRM-001"
    assert "printlog" in str(exc.value)
