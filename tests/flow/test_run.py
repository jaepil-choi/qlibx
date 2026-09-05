"""A run is configuration: its universe, its period, its venue, and when it asks its strategies.

Record `148`: an agenda is no longer a user declaration. A run says which sessions it fires on
(`sessions`, listed, or `sessions_from`, a dataset's own days) and at what venue-local wall time
(`at`, in `timezone`); every strategy is called on every session and decides for itself. The
book is valued at the instant the venue fills and monitored right after each commit, so `at` is
the one wall time a run declares, and the valuation and monitoring declarations are gone.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import ConstraintSet, RunDefinition, StrategyConfig, StrategyEntry
from vqapr.runtime.agendas import OperationRole

KST = ZoneInfo("Asia/Seoul")


def _component(kind: ComponentKind, name: str) -> ComponentRef:
    return ComponentRef.of(
        name,
        kind,
        Path(f"{name}.py"),
        "Component",
        fingerprint="0" * 64,
    )


def _definition(**overrides: object) -> RunDefinition:
    declared: dict[str, object] = {
        "run_id": "r",
        "strategies": (StrategyEntry("strategy", ("no-short",)),),
        "instruments": ("ABC",),
        "timezone": "Asia/Seoul",
        "at": time(15, 29),
        "sessions": (date(2024, 1, 2), date(2024, 1, 3)),
    }
    declared.update(overrides)
    return RunDefinition(**declared)  # type: ignore[arg-type]


def test_a_strategy_config_binds_a_strategy_to_a_callback_agenda_only() -> None:
    """Preflight's product, not a user declaration; the role it carries is fixed."""
    strategy = _component(ComponentKind.STRATEGY_MODEL, "strategy")

    config = StrategyConfig(strategy, "r.sessions", OperationRole.STRATEGY_CALLBACK)

    assert config.agenda_role is OperationRole.STRATEGY_CALLBACK
    with pytest.raises(ValueError, match="strategy agenda_role"):
        StrategyConfig(strategy, "r.sessions", OperationRole.VALUATION)
    with pytest.raises(ValueError, match="STRATEGY_MODEL"):
        StrategyConfig(
            _component(ComponentKind.CONSTRAINT, "limit"),
            "r.sessions",
            OperationRole.STRATEGY_CALLBACK,
        )


def test_a_run_names_its_strategies_and_each_strategy_its_constraints() -> None:
    """Record `139`: the run layer is shared; constraints belong to the strategy under them."""
    run = _definition(
        strategies=(StrategyEntry("a", ("no-short",)), StrategyEntry("b")),
    )

    assert [entry.component_id for entry in run.strategies] == ["a", "b"]
    assert run.strategy("a").constraints == ("no-short",)
    assert run.strategy("b").constraints == ()
    assert "constraints" not in {field.name for field in fields(RunDefinition)}
    assert "strategy" not in {field.name for field in fields(RunDefinition)}
    with pytest.raises(KeyError, match="does not name strategy 'c'"):
        run.strategy("c")


def test_a_run_names_each_strategy_at_most_once_and_at_least_one() -> None:
    with pytest.raises(ValueError, match="at most once"):
        _definition(strategies=(StrategyEntry("a"), StrategyEntry("a")))
    with pytest.raises(ValueError, match="at least one strategy"):
        _definition(strategies=())


def test_a_strategy_entry_is_ids_and_memory_only() -> None:
    entry = StrategyEntry("a", ("x", "y"), {"cadence": [1]})
    assert entry.initial_model_memory == {"cadence": [1]}
    with pytest.raises(ValueError, match="repeat"):
        StrategyEntry("a", ("x", "x"))
    with pytest.raises(TypeError, match="component ids"):
        StrategyEntry("a", (_component(ComponentKind.CONSTRAINT, "x"),))  # type: ignore[arg-type]


def test_the_run_layer_pairs_its_declarations() -> None:
    with pytest.raises(ValueError, match="declared together"):
        _definition(exchange="venue")
    with pytest.raises(ValueError, match="declared together"):
        _definition(start=datetime(2024, 1, 2, tzinfo=KST))
    with pytest.raises(ValueError, match="start must not be after end"):
        _definition(start=datetime(2024, 1, 3, tzinfo=KST), end=datetime(2024, 1, 2, tzinfo=KST))
    with pytest.raises(ValueError, match="instruments must be unique"):
        _definition(instruments=("A", "A"))


def test_a_run_declares_its_zone_and_one_naive_wall_time() -> None:
    """`at` is a wall time on the venue's clock; the zone is declared once, beside it.

    A tz-aware `time` would carry a second zone that could disagree with `timezone`, and a
    string would let "15:29" and "3:29 PM" name the same instant under two spellings.
    """
    assert _definition().at == time(15, 29)
    assert _definition().timezone == "Asia/Seoul"
    with pytest.raises(ValueError, match="timezone must be a non-empty IANA timezone name"):
        _definition(timezone="")
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        _definition(timezone="Mars/Olympus_Mons")
    with pytest.raises(ValueError, match="at must be declared"):
        _definition(at=None)
    with pytest.raises(TypeError, match=r"at must be a datetime\.time"):
        _definition(at="15:29")
    with pytest.raises(ValueError, match="timezone-naive wall time"):
        _definition(at=time(15, 29, tzinfo=KST))


def test_a_run_declares_exactly_one_source_of_sessions() -> None:
    """Listed dates, or a dataset's own days -- never both, never neither.

    A `datetime` is refused as a session on purpose: a session is a venue-local day and the
    time of day comes from `at`. Letting a datetime through would smuggle a second wall time in.
    """
    from_dataset = _definition(sessions=(), sessions_from="prices")
    assert from_dataset.sessions_from == "prices" and from_dataset.sessions == ()

    with pytest.raises(ValueError, match="declare exactly one of sessions_from or sessions"):
        _definition(sessions=())
    with pytest.raises(ValueError, match="declare exactly one of sessions_from or sessions"):
        _definition(sessions_from="prices")
    with pytest.raises(TypeError, match="sessions_from must be a non-empty identifier"):
        _definition(sessions=(), sessions_from="")
    with pytest.raises(TypeError, match="sessions must be a tuple of dates"):
        _definition(sessions=(datetime(2024, 1, 2, tzinfo=KST),))
    with pytest.raises(TypeError, match="sessions must be a tuple of dates"):
        _definition(sessions=[date(2024, 1, 2)])
    with pytest.raises(TypeError, match="sessions must be a tuple of dates"):
        _definition(sessions=("2024-01-02",))


def test_the_agenda_a_run_derives_is_named_after_the_run_and_is_not_a_field() -> None:
    """The one agenda is preflight's to build; the definition only knows what it will be called."""
    assert _definition(run_id="alpha").agenda_id == "alpha.sessions"
    assert "agenda_id" not in {field.name for field in fields(RunDefinition)}
    assert "agenda_role" not in {field.name for field in fields(RunDefinition)}


def test_a_run_declares_no_valuation_and_no_monitoring() -> None:
    """Record `148` pins the surface: valued where it fills, judged after each commit."""
    assert {field.name for field in fields(RunDefinition)} == {
        "run_id",
        "strategies",
        "instruments",
        "datamodels",
        "timezone",
        "at",
        "sessions_from",
        "sessions",
        "exchange",
        "execution_input_id",
        "start",
        "end",
        "initial_account_snapshot",
        "initial_account_mode",
    }


def test_constraint_set_holds_constraint_refs_only() -> None:
    constraints = ConstraintSet((_component(ComponentKind.CONSTRAINT, "no-short"),))
    assert constraints.constraints[0].component_id == "no-short"
    with pytest.raises(ValueError, match="CONSTRAINT"):
        ConstraintSet((_component(ComponentKind.STRATEGY_MODEL, "s"),))


def test_component_kinds_remain_closed_to_the_existing_four() -> None:
    assert tuple(ComponentKind) == (
        ComponentKind.DATA_MODEL,
        ComponentKind.STRATEGY_MODEL,
        ComponentKind.EXCHANGE,
        ComponentKind.CONSTRAINT,
    )
