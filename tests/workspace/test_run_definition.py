"""A run is configuration: its universe, its period, its venue, and when it asks its strategies.

Record `148`: an schedule is no longer a user declaration. A run says when it fires with its
`schedule:` block (design §3.4) and in which venue-local zone; the days come from data
(`at`, in `timezone`); every strategy is called on every session and decides for itself. The
book is valued at the instant the venue fills and monitored right after each commit, so `at` is
the one wall time a run declares, and the valuation and monitoring declarations are gone.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from vqapr.component.reference import ComponentRef
from vqapr.domain.wiring import EXTENSION_POINTS, Role
from vqapr.workspace.run_definition import (
    ComplianceSet,
    DataModelEntry,
    RunSchedule,
    RunDefinition,
    StrategyConfig,
    StrategyEntry,
)

KST = ZoneInfo("Asia/Seoul")


def _component(kind: Role, name: str) -> ComponentRef:
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
        "strategy": StrategyEntry("strategy"),
        "compliance": ("no-short",),
        "instruments": ("ABC",),
        "timezone": "Asia/Seoul",
        "schedule": {"every": "1d", "at": time(15, 29)},
    }
    declared.update(overrides)
    return RunDefinition(**declared)  # type: ignore[arg-type]


def test_a_strategy_config_binds_a_strategy_to_the_run_schedule() -> None:
    """Preflight's product, not a user declaration; it carries no role (record `182`)."""
    strategy = _component(Role.STRATEGY_MODEL, "strategy")

    config = StrategyConfig(strategy, "r.schedule")

    assert config.schedule_id == "r.schedule"
    assert not hasattr(config, "schedule_role")
    with pytest.raises(ValueError, match="STRATEGY_MODEL"):
        StrategyConfig(
            _component(Role.COMPLIANCE, "limit"),
            "r.schedule",
        )


def test_a_run_names_one_strategy_and_its_own_compliance_rules() -> None:
    """A run runs one model; the rules that watch its book are the run's, not the strategy's
    (design §7.2), and the old `constraints:` under the strategy is refused by name."""
    run = _definition(strategy=StrategyEntry("a"), compliance=("no-short",))

    assert run.strategy is not None
    assert run.strategy.component_id == "a"
    assert run.compliance == ("no-short",)
    assert run.member is run.strategy
    assert "constraints" not in {field.name for field in fields(StrategyEntry)}
    with pytest.raises(ValueError, match="left the strategy entry"):
        _definition(strategy={"component": "a", "constraints": ["no-short"]})
    with pytest.raises(ValueError, match="declares no compliance"):
        _definition(
            strategy=None,
            datamodel={"component": "d", "value_fields": ["v"]},
            schedule={"every": "1d", "at": time(15, 29), "days_from": "prices"},
        )
    assert "strategies" not in set(RunDefinition.model_fields)


def test_a_run_names_exactly_one_model() -> None:
    """Two members are refused by name rather than half-run, and none is refused too.

    The stored block is still `strategies: {id: {...}}`; what changed is that it holds one.
    """
    with pytest.raises(ValueError, match="names exactly one model"):
        _definition(strategies={"a": {}, "b": {}})
    with pytest.raises(ValueError, match="exactly one of"):
        _definition(strategy=None)


def test_a_strategy_entry_is_an_id_and_memory_only() -> None:
    entry = StrategyEntry("a", {"cadence": [1]})
    assert entry.initial_model_memory == {"cadence": [1]}
    with pytest.raises(ValueError, match="repeat"):
        _definition(compliance=("x", "x"))
    # pydantic owns the shape now (one-shape campaign Step 5): a ComponentRef where an id belongs
    # is pydantic's own shape error, not a hand-written TypeError.
    with pytest.raises(ValidationError, match="valid string"):
        _definition(compliance=(_component(Role.COMPLIANCE, "x"),))


def test_an_undeclared_opening_memory_is_an_empty_mapping() -> None:
    """`{}` unless declared, and a declared `null` is the same `{}` (`docs/issues/089`).

    `make-strategy`'s reference shows `self.memory.setdefault(...)` on the first callback; an
    entry whose opening memory was `None` made that documented example raise. Any other
    strict-JSON value a run declares is kept as declared.
    """
    assert StrategyEntry("a").initial_model_memory == {}
    assert StrategyEntry("a", None).initial_model_memory == {}
    assert StrategyEntry("a", {"cadence": [1]}).initial_model_memory == {"cadence": [1]}
    assert DataModelEntry("d", ("x",)).initial_model_memory == {}
    assert DataModelEntry("d", ("x",), None).initial_model_memory == {}
    # Distinct entries do not share one mutable default.
    first, second = StrategyEntry("a"), StrategyEntry("b")
    assert first.initial_model_memory is not second.initial_model_memory


def test_the_run_layer_pairs_its_declarations() -> None:
    with pytest.raises(ValueError, match="declared together"):
        _definition(exchange="venue")
    with pytest.raises(ValueError, match="declared together"):
        _definition(start=datetime(2024, 1, 2, tzinfo=KST))
    with pytest.raises(ValueError, match="start must not be after end"):
        _definition(start=datetime(2024, 1, 3, tzinfo=KST), end=datetime(2024, 1, 2, tzinfo=KST))
    with pytest.raises(ValueError, match="instruments must be unique"):
        _definition(instruments=("A", "A"))


def test_a_run_declares_its_zone_and_naive_wall_times() -> None:
    """`at` is a wall time on the venue's clock; the zone is declared once, beside the schedule.

    A tz-aware `time` would carry a second zone that could disagree with `timezone`, and a
    string would let "15:29" and "3:29 PM" name the same instant under two spellings.
    """
    assert _definition().schedule.rule.at == (time(15, 29),)
    assert _definition().timezone == "Asia/Seoul"
    with pytest.raises(ValueError, match="timezone must be a non-empty IANA timezone name"):
        _definition(timezone="")
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        _definition(timezone="Mars/Olympus_Mons")
    with pytest.raises(ValidationError, match="schedule"):
        _definition(schedule=None)
    # A string is coerced by pydantic ("15:29" is a valid time); a non-time is a shape error.
    assert _definition(schedule={"every": "1d", "at": "15:29"}).schedule.at == (time(15, 29),)
    with pytest.raises(ValidationError, match="at"):
        _definition(schedule={"every": "1d", "at": object()})
    with pytest.raises(ValueError, match="timezone-naive wall time"):
        _definition(schedule={"every": "1d", "at": time(15, 29, tzinfo=KST)})


def test_an_schedule_is_a_day_filter_and_a_within_day_rule() -> None:
    """Design §3.4: `every` picks days (`1d`, `1w`, `1M`) with `at`, or instants (`5m`, `1h`)
    with `from`/`to`; the two halves must agree, and a strategy run names no day source -- its
    trading days are its execution table's."""
    schedule = RunSchedule(every="5m", **{"from": time(9, 0)}, to=time(9, 10))
    assert schedule.rule.times() == (time(9, 0), time(9, 5), time(9, 10))
    assert schedule.model_dump(mode="json") == {"every": "5m", "from": "09:00:00", "to": "09:10:00"}
    assert RunSchedule(every="1d", at=(time(9),)).model_dump(mode="json") == {
        "every": "1d",
        "at": ["09:00:00"],
    }

    with pytest.raises(ValueError, match="needs at"):
        RunSchedule(every="1d")
    with pytest.raises(ValueError, match="declare from/to, not at"):
        RunSchedule(every="5m", at=(time(9),))
    with pytest.raises(ValueError, match="declare at, not from/to"):
        RunSchedule(every="1w", at=(time(9),), to=time(10))
    with pytest.raises(ValueError, match="count and a unit"):
        RunSchedule(every="daily", at=(time(9),))
    with pytest.raises(ValueError, match="declares no schedule.days_from"):
        _definition(schedule={"every": "1d", "at": "15:29", "days_from": "prices"})


def test_on_last_is_stored_only_when_it_is_last() -> None:
    """Record `253`. `on: first` is what every run before it meant, so a run that says nothing and
    one that says `first` store the same body -- and keep the identity they had."""
    last = RunSchedule(every="1M", at=(time(15, 29),), on="last")
    assert last.rule.on == "last"
    assert last.model_dump(mode="json") == {"every": "1M", "at": ["15:29:00"], "on": "last"}
    assert RunSchedule(every="1M", at=(time(9),), on="first").model_dump(mode="json") == {
        "every": "1M",
        "at": ["09:00:00"],
    }
    assert _definition(schedule={"every": "1M", "at": "15:29", "on": "first"}).model_dump(
        mode="json"
    ) == _definition(schedule={"every": "1M", "at": "15:29"}).model_dump(mode="json")
    with pytest.raises(ValueError, match="pairs with a w or M rule"):
        RunSchedule(every="1d", at=(time(9),), on="last")


def test_the_schedule_a_run_derives_is_named_after_the_run_and_is_not_a_field() -> None:
    """The one schedule is preflight's to build; the definition only knows what it will be called."""
    assert _definition(run_id="alpha").schedule_id == "alpha.schedule"
    assert "schedule_id" not in set(RunDefinition.model_fields)
    assert "schedule_role" not in set(RunDefinition.model_fields)


def test_a_run_declares_no_valuation_and_no_monitoring() -> None:
    """Record `148` pins the surface: valued where it fills, judged after each commit."""
    assert set(RunDefinition.model_fields) == {
        "run_id",
        "writes",
        "strategy",
        "instruments",
        "datamodel",
        "timezone",
        "schedule",
        "exchange",
        "execution",
        "compliance",
        "start",
        "end",
        "initial_account_snapshot",
        "initial_account_mode",
    }


def test_compliance_set_holds_compliance_refs_only() -> None:
    rules = ComplianceSet((_component(Role.COMPLIANCE, "no-short"),))
    assert rules.rules[0].component_id == "no-short"
    with pytest.raises(ValueError, match="COMPLIANCE"):
        ComplianceSet((_component(Role.STRATEGY_MODEL, "s"),))


def test_the_extension_points_remain_closed_to_the_existing_four() -> None:
    assert EXTENSION_POINTS == (
        Role.DATA_MODEL,
        Role.STRATEGY_MODEL,
        Role.EXCHANGE,
        Role.COMPLIANCE,
    )
