"""A run is configuration: its universe, its period, its venue, and when it asks its strategies.

Record `148`: an agenda is no longer a user declaration. A run says which sessions it fires on
(`sessions`, listed, or `sessions_from`, a dataset's own days) and at what venue-local wall time
(`at`, in `timezone`); every strategy is called on every session and decides for itself. The
book is valued at the instant the venue fills and monitored right after each commit, so `at` is
the one wall time a run declares, and the valuation and monitoring declarations are gone.
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.project.run import ConstraintSet, RunDefinition, StrategyConfig, StrategyEntry

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
        "writes": "r-weights",
        "strategy": StrategyEntry("strategy", ("no-short",)),
        "instruments": ("ABC",),
        "timezone": "Asia/Seoul",
        "at": time(15, 29),
        "sessions": (date(2024, 1, 2), date(2024, 1, 3)),
    }
    declared.update(overrides)
    return RunDefinition(**declared)  # type: ignore[arg-type]


def test_a_strategy_config_binds_a_strategy_to_the_run_agenda() -> None:
    """Preflight's product, not a user declaration; it carries no role (record `182`)."""
    strategy = _component(ComponentKind.STRATEGY_MODEL, "strategy")

    config = StrategyConfig(strategy, "r.sessions")

    assert config.agenda_id == "r.sessions"
    assert not hasattr(config, "agenda_role")
    with pytest.raises(ValueError, match="STRATEGY_MODEL"):
        StrategyConfig(
            _component(ComponentKind.CONSTRAINT, "limit"),
            "r.sessions",
        )


def test_a_run_names_one_strategy_and_that_strategy_its_constraints() -> None:
    """A run runs one model; constraints belong to the strategy under it."""
    run = _definition(strategy=StrategyEntry("a", ("no-short",)))

    assert run.strategy is not None
    assert run.strategy.component_id == "a"
    assert run.strategy.constraints == ("no-short",)
    assert run.member is run.strategy
    assert "constraints" not in set(RunDefinition.model_fields)
    assert "strategies" not in set(RunDefinition.model_fields)


def test_a_run_names_exactly_one_model() -> None:
    """Two members are refused by name rather than half-run, and none is refused too.

    The stored block is still `strategies: {id: {...}}`; what changed is that it holds one.
    """
    with pytest.raises(ValueError, match="names exactly one model"):
        _definition(strategies={"a": {}, "b": {}})
    with pytest.raises(ValueError, match="exactly one of"):
        _definition(strategy=None)


def test_a_strategy_entry_is_ids_and_memory_only() -> None:
    entry = StrategyEntry("a", ("x", "y"), {"cadence": [1]})
    assert entry.initial_model_memory == {"cadence": [1]}
    with pytest.raises(ValueError, match="repeat"):
        StrategyEntry("a", ("x", "x"))
    # pydantic owns the shape now (one-shape campaign Step 5): a ComponentRef where an id belongs
    # is pydantic's own shape error, not a hand-written TypeError.
    with pytest.raises(ValidationError, match="valid string"):
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
    # A string is coerced by pydantic ("15:29" is a valid time); a non-time is a shape error.
    assert _definition(at="15:29").at == time(15, 29)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="at"):
        _definition(at=object())  # type: ignore[arg-type]
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
    with pytest.raises(ValueError, match="sessions_from must be a non-empty identifier"):
        _definition(sessions=(), sessions_from="")
    # pydantic owns the shape: a datetime is not a date, and a list of dates becomes a tuple of
    # dates rather than being refused for its container type (a declaration writes a list).
    with pytest.raises(ValidationError, match="sessions"):
        _definition(sessions=(datetime(2024, 1, 2, 9, 30, tzinfo=KST),))
    assert _definition(sessions=[date(2024, 1, 2)]).sessions == (date(2024, 1, 2),)
    assert _definition(sessions=("2024-01-02",)).sessions == (date(2024, 1, 2),)  # type: ignore[arg-type]


def test_the_agenda_a_run_derives_is_named_after_the_run_and_is_not_a_field() -> None:
    """The one agenda is preflight's to build; the definition only knows what it will be called."""
    assert _definition(run_id="alpha").agenda_id == "alpha.sessions"
    assert "agenda_id" not in set(RunDefinition.model_fields)
    assert "agenda_role" not in set(RunDefinition.model_fields)


def test_a_run_declares_no_valuation_and_no_monitoring() -> None:
    """Record `148` pins the surface: valued where it fills, judged after each commit."""
    assert set(RunDefinition.model_fields) == {
        "run_id",
        "writes",
        "strategy",
        "instruments",
        "datamodel",
        "timezone",
        "at",
        "sessions_from",
        "sessions",
        "exchange",
        "execution",
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
