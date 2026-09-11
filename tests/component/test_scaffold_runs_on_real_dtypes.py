"""What `vqapr new` emits must *run* against a real dataset, not merely register.

`test_the_scaffold_registers_as_written` proves the template passes its door. That door only
constructs the object and checks its signature -- it never calls the callback, so a template that
registers cleanly and raises on its first row satisfies it completely.

That gap shipped. A testbed agent registered the unmodified strategy scaffold against a parquet
whose `close` is float64 and got, mid-run:

    simulation.callback.intent: unsupported operand type(s) for -: 'float' and 'decimal.Decimal'

The scaffold collected `row[field]` raw and then subtracted it against `Decimal`.

Why 691 tests missed it is the part worth keeping. `normalize_scalar` passes `float` through as
`float` -- the store returns whatever the column holds. But **every** price fixture in this suite
writes its values as bare DuckDB literals, and `typeof(100.0)` in DuckDB is `DECIMAL(4,1)`, not
`DOUBLE`. So the fixtures fed `Decimal` to every model ever tested, which is the one dtype under
which the bug is invisible. A parquet written by pandas, polars, or pyarrow from a float column --
the overwhelmingly common case for a price -- gives `float`.

Hence `float_price_parquet` below, with an explicit `CAST(... AS DOUBLE)`. It is the only fixture
here that reproduces what a user's file actually contains. Verified by reverting the fix: with
`.append(value)` restored, `test_the_datamodel_scaffold_computes_against_a_float64_column` and
`test_the_strategy_scaffold_decides_against_a_float64_column` both fail with the TypeError above,
and pass with it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.authoring import EconomicAccountView
from vqapr.component.loading import load_data_model, load_strategy_model
from vqapr.component.scaffold import render
from vqapr.component.strategy.recorder import InvocationRecorder
from vqapr.data.dataset import DatasetRegistration
from vqapr.data.lookback import RowsLookback
from vqapr.data.requirement import DataRequirement
from vqapr.data.source import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.window import ModelWindow
from vqapr.domain.instants import LocalInstantDeclaration
from vqapr.domain.schedule import OperationOccurrence
from vqapr.domain.wiring import Role
from vqapr.flow.run.calls import DataModelContext, StrategyModelContext
from vqapr.public import Workspace, register_data_model, register_dataset, register_strategy_model

KST = ZoneInfo("Asia/Seoul")

# Three rows per name at or before this instant. The 03-08 row is later and stays outside.
EVALUATION_TIME = datetime(2024, 3, 7, 16, tzinfo=KST)
LOOKBACK = 3

@pytest.fixture(scope="session")
def float_price_parquet(tmp_path_factory) -> Path:
    """A price column that is genuinely `DOUBLE`, which is what a real parquet holds.

    `CAST(... AS DOUBLE)` is load-bearing and must not be simplified back to a bare literal:
    DuckDB types `100.0` as `DECIMAL(4,1)`, and a decimal column makes this whole file pass
    against the broken template.
    """
    out = tmp_path_factory.mktemp("float-price") / "price_daily.parquet"
    con = duckdb.connect()
    con.execute(
        f"""COPY (
            SELECT
                session_date,
                available_at,
                instrument,
                CAST(close AS DOUBLE) AS close
            FROM (VALUES
              (DATE '2024-03-05', TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', 100.0),
              (DATE '2024-03-06', TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', 103.0),
              (DATE '2024-03-07', TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', 105.0),
              (DATE '2024-03-08', TIMESTAMPTZ '2024-03-08 15:30:00+09', 'A', 999.0),
              (DATE '2024-03-05', TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B',  50.0),
              (DATE '2024-03-06', TIMESTAMPTZ '2024-03-06 15:30:00+09', 'B',  51.0),
              (DATE '2024-03-07', TIMESTAMPTZ '2024-03-07 15:30:00+09', 'B',  53.0),
              (DATE '2024-03-08', TIMESTAMPTZ '2024-03-08 15:30:00+09', 'B', 999.0)
            ) AS t(session_date, available_at, instrument, close)
        ) TO '{out.as_posix()}' (FORMAT PARQUET)"""
    )
    con.close()
    return out

def _workspace(project: Path, prices: Path) -> Workspace:
    # Registered through the public entry point, which measures the span persistence requires.
    register_dataset(
        project,
        DatasetRegistration.of(
            "price_daily",
            "prices",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
        ),
        SourceSpec.of("prices", prices),
    )
    return Workspace.open(project)

def _window(workspace: Workspace, requirement: DataRequirement) -> ModelWindow:
    return ModelWindow(
        evaluation_time=EVALUATION_TIME,
        instruments=("A", "B"),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
        consumer_id="test-consumer",
    )

def _emit(
    project: Path, kind: Role, component_id: str, lookback_kind: str = "rows"
) -> Path:
    path = project / f"{component_id.replace('-', '_')}.py"
    path.write_text(
        render(
            kind,
            component_id,
            dataset_id="price_daily",
            lookback=LOOKBACK,
            lookback_kind=lookback_kind,
        ),
        encoding="utf-8",
    )
    return path

def test_the_price_fixture_really_holds_python_floats(
    tmp_path: Path, float_price_parquet: Path
) -> None:
    """Guard the guard.

    If this fixture ever drifts back to a decimal column, the two tests below keep passing while
    testing nothing -- which is exactly how the bug shipped. Assert the dtype directly.
    """
    workspace = _workspace(tmp_path, float_price_parquet)
    requirement = DataRequirement.of('price_daily', 'close', lookback=RowsLookback(LOOKBACK))

    rows = _window(workspace, requirement).observations(requirement).rows

    assert rows, "fixture produced no rows"
    assert all(type(row["close"]) is float for row in rows)

def test_the_datamodel_scaffold_computes_against_a_float64_column(
    tmp_path: Path, float_price_parquet: Path
) -> None:
    """The template's `compute` must survive the dtype a real parquet stores."""
    workspace = _workspace(tmp_path, float_price_parquet)
    path = _emit(tmp_path, Role.DATA_MODEL, "float-model")
    ref = register_data_model(tmp_path, "float-model", path, "FloatModel")
    model = load_data_model(ref, project_root=tmp_path)

    rows = model.compute(
        DataModelContext(window=_window(workspace, model.requirements()[0]), reads=model.inputs())
    )

    # A: 105/100 - 1 = 0.05.  B: 53/50 - 1 = 0.06. Floats, because the scaffold returns the
    # `double` it declares (record 174) and computes on the window's matrix (record 233), so the
    # quotient carries a binary float's last bit; the crossing to Decimal, if an author wants one,
    # is theirs.
    assert [row["instrument"] for row in rows] == ["A", "B"]
    assert [row["value"] for row in rows] == pytest.approx([0.05, 0.06])
    assert all(type(row["value"]) is float for row in rows)


def _prime_like_the_run(strategy) -> None:
    """What the Flow does before every callback: memory restored (`{}` on the first one, record
    `215`) and a recorder for the callback's declared tables. The scaffold uses both since record
    `267`, so a `decide()` called by hand is handed them the way a run hands them."""
    strategy.memory = {}
    strategy.recorder = InvocationRecorder(
        strategy.tables(),
        run_id="by-hand",
        producer_id="scaffold",
        stage="callback",
        event_time=EVALUATION_TIME,
    )


def test_the_strategy_scaffold_decides_against_a_float64_column(
    tmp_path: Path, float_price_parquet: Path
) -> None:
    """The template's `decide` must reach a decision, not a `TypeError`.

    This is the call the testbed agent's run actually made when it failed.
    """
    workspace = _workspace(tmp_path, float_price_parquet)
    path = _emit(tmp_path, Role.STRATEGY_MODEL, "float-alpha")
    ref = register_strategy_model(tmp_path, "float-alpha", path, "FloatAlpha")
    strategy = load_strategy_model(ref, project_root=tmp_path)

    context = StrategyModelContext(
        occurrence=OperationOccurrence(
            "cb-1",
            LocalInstantDeclaration(
                EVALUATION_TIME.date(),
                EVALUATION_TIME.timetz().replace(tzinfo=None),
                "Asia/Seoul",
                0,
                "+09:00",
            ),
        ),
        window=_window(workspace, strategy.requirements()[0]),
        reads=strategy.inputs(),
        account=EconomicAccountView(
            cash=Decimal("1000000"), positions={}, nav=None, nav_observed_at=None
        ),
    )

    _prime_like_the_run(strategy)
    decision = strategy.decide(context)

    # Both names rose over the window, so the five-day *reversal* scores both negative and the
    # template declines. What is under test is that the arithmetic completed at all: before the
    # fix this raised `TypeError` instead of returning any decision.
    assert decision is not None
    assert type(decision).__name__ in {"Hold", "Rebalance"}


def test_the_calendar_strategy_scaffold_decides_against_a_float64_column(
    tmp_path: Path, float_price_parquet: Path
) -> None:
    """The calendar flavour runs as written (record `251`), and reaches a real decision.

    Three calendar days back from 2024-03-07 16:00 KST keeps the 03-05..03-07 rows: A rises
    100 -> 105 and B 50 -> 53, so the momentum signal chooses both and the template rebalances.
    """
    workspace = _workspace(tmp_path, float_price_parquet)
    path = _emit(tmp_path, Role.STRATEGY_MODEL, "day-alpha", lookback_kind="calendar")
    ref = register_strategy_model(tmp_path, "day-alpha", path, "DayAlpha")
    strategy = load_strategy_model(ref, project_root=tmp_path)

    context = StrategyModelContext(
        occurrence=OperationOccurrence(
            "cb-1",
            LocalInstantDeclaration(
                EVALUATION_TIME.date(),
                EVALUATION_TIME.timetz().replace(tzinfo=None),
                "Asia/Seoul",
                0,
                "+09:00",
            ),
        ),
        window=_window(workspace, strategy.requirements()[0]),
        reads=strategy.inputs(),
        account=EconomicAccountView(
            cash=Decimal("1000000"), positions={}, nav=None, nav_observed_at=None
        ),
    )

    _prime_like_the_run(strategy)
    decision = strategy.decide(context)

    assert type(decision).__name__ == "Rebalance", decision
    assert strategy.memory == {"held": ["A", "B"]}, "what the next callback's log compares with"

@pytest.mark.parametrize("kind", [Role.DATA_MODEL, Role.STRATEGY_MODEL])
def test_neither_template_collects_a_raw_cell(kind: Role) -> None:
    """Pin the conversion in the emitted source.

    The tests above prove the templates run on float64. This one names *why*, so an edit that
    reintroduces `.append(value)` fails on the line that caused it rather than on an arithmetic
    result several frames away.
    """
    source = render(kind, "pinned", dataset_id="price_daily")

    # Since record `233` a panel-grain body computes on `window.matrix()` -- one float array
    # over every name -- so no cell is collected or converted one at a time at all.
    assert "window.matrix()" in source
    assert "Decimal(" not in source and ".append(value)" not in source
    assert "for name in window.instruments" not in source, "no per-name loop over the window"

    # The rows grain has no shared instant axis and keeps the per-name reduction; there the
    # property is the old one: every cell goes through `Decimal(str(...))`, never `Decimal(...)`
    # on the raw cell.
    rows = render(Role.DATA_MODEL, "pinned", dataset_id="vendor", lookback_kind="instants")
    assert "Decimal(str(value))" in rows
    assert "[Decimal(v)" not in rows and ".append(value)" not in rows
