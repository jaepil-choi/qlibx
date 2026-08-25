"""A caller holding only public types runs a simulation end to end.

This is the test the whole migration exists to make possible. Everything the engine needs -
the strategy component, its agendas, the exchange, the execution input, the account - is
registered by `Project.simulate` from public declarations. No caller touches a
`ComponentRef`, a fingerprint, an agenda id, or an `EconomicPortfolioIntent`.

The strategies live in a real module written to disk because the engine's loader resolves a
component by re-importing its module and looking the class up by name; a class defined
inside a test function cannot be found that way, and refusing it is deliberate.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import duckdb
import pytest

KST = ZoneInfo("Asia/Seoul")
SESSIONS = (date(2024, 3, 4), date(2024, 3, 5))

STRATEGIES = textwrap.dedent(
    '''
    from decimal import Decimal

    from vqapr.authoring import (
        Constraint,
        ConstraintBounds,
        ConstraintFinding,
        Hold,
        Rebalance,
        StrategyModel,
        StrategyResult,
    )
    from vqapr.portfolio.budgets import Budget, PortfolioDirection

    BUDGET = Budget(
        direction=PortfolioDirection.LONG_ONLY,
        cash_lower=Decimal(0),
        cash_upper=Decimal(1),
        target_lower=Decimal(0),
        target_upper=Decimal(1),
    )


    class Idle(StrategyModel):
        """Never trades."""

        def decide(self, call):
            return StrategyResult(
                decision=Hold(reason="idle"), next_state=None, diagnostics={}
            )


    class Reader(StrategyModel):
        """Declares an input, so preflight must resolve a registered dataset.

        Every earlier test here declared no inputs() at all, so none of them touched the
        dataset-resolution path - which is exactly how a two-store split survived an
        end-to-end proof.
        """

        def inputs(self):
            from vqapr.authoring import DatasetInput, RowsLookback

            return {
                "prices": DatasetInput(
                    dataset_id="price_daily", fields=("close",), lookback=RowsLookback(rows=1)
                )
            }

        def decide(self, call):
            observations = call.read("prices")
            return StrategyResult(
                decision=Hold(reason=f"saw-{len(observations)}"),
                next_state=None,
                diagnostics={},
            )


    class NavWatcher(StrategyModel):
        """Declares account history and reports the NAV it can actually see.

        `EconomicAccountView.nav` was hardcoded None in the bridges, so no authored rule
        could ever measure a weight - which is most real constraints. The contract couples
        nav and nav_observed_at: both None before any committed valuation, both set after.
        """

        def account_history(self):
            from vqapr.authoring import AccountHistoryInput, RowsLookback

            return AccountHistoryInput(fields=("nav",), lookback=RowsLookback(rows=4))

        def decide(self, call):
            navs = call.account_history.series("nav")
            coupled = (call.account.nav is None) == (call.account.nav_observed_at is None)
            return StrategyResult(
                decision=Hold(
                    reason=f"navs-{len(navs)}-view-{call.account.nav is not None}-"
                    f"coupled-{coupled}"
                ),
                next_state=None,
                diagnostics={},
            )


    class Diagnosing(StrategyModel):
        """Emits rows into a diagnostic table it declared itself."""

        def diagnostics(self):
            from vqapr.authoring import DiagnosticTable

            return (
                DiagnosticTable(
                    table_id="alpha.signal", semantic_fields=("instrument", "score")
                ),
            )

        def decide(self, call):
            return StrategyResult(
                decision=Hold(reason="diagnosing"),
                next_state=None,
                diagnostics={"alpha.signal": ({"instrument": "A005930", "score": "0.42"},)},
            )


    class SingleNameCap(Constraint):
        """No single name above CAP of the book."""

        CAP = Decimal("0.60")

        def inputs(self):
            return {}

        def project(self, call):
            return ConstraintBounds(
                lower_weights={name: -self.CAP for name in call.instruments},
                upper_weights={name: self.CAP for name in call.instruments},
            )

        def validate(self, decision, bounds):
            worst = max(
                (abs(weight) for weight in decision.target_weights.values()),
                default=Decimal(0),
            )
            return ConstraintFinding(
                passed=worst <= self.CAP,
                measured=worst,
                bound=self.CAP,
                excess=max(worst - self.CAP, Decimal(0)),
                details={},
            )

        def monitor(self, call, bounds):
            return ConstraintFinding(
                passed=True, measured=Decimal(0), bound=self.CAP,
                excess=Decimal(0), details={},
            )


    class TightCap(SingleNameCap):
        """Tighter than the 0.5 Buyer asks for, so it must refuse."""

        CAP = Decimal("0.10")


    class Buyer(StrategyModel):
        """Holds half the book, so every occurrence produces an intent."""

        def decide(self, call):
            return StrategyResult(
                decision=Rebalance(
                    target_weights={"A005930": Decimal("0.5")},
                    cash_weight=Decimal("0.5"),
                    budget=BUDGET,
                ),
                next_state=None,
                diagnostics={},
            )
    '''
)

RUNNER = textwrap.dedent(
    '''
    import sys
    from datetime import date, datetime, time
    from decimal import Decimal
    from pathlib import Path
    from zoneinfo import ZoneInfo

    import vqapr
    from vqapr.simulation import (
        AccountMode, AccountSnapshot, Cadence, ConstraintDeclaration, Execution,
        ExecutionInput, FillConvention, FillSelector, InitialAccount, Schedule, Simulation,
    )
    from vqapr.venues import Academic, Listing, ListingAccess, VenueCost

    import authored_strategies

    KST = ZoneInfo("Asia/Seoul")
    root, exec_path, which = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    sessions = (date(2024, 3, 4), date(2024, 3, 5))

    simulation = Simulation(
        schedule=Schedule(
            strategy=Cadence(sessions=sessions, at=time(15, 0), timezone="Asia/Seoul"),
            valuation=Cadence(sessions=sessions, at=time(15, 30), timezone="Asia/Seoul"),
            monitoring=(
                Cadence(sessions=sessions, at=time(16, 0), timezone="Asia/Seoul")
                if len(sys.argv) > 5 and sys.argv[5] == "monitored"
                else None
            ),
            start=datetime(2024, 3, 4, tzinfo=KST),
            end=datetime(2024, 3, 5, 23, tzinfo=KST),
        ),
        execution=Execution(
            input=ExecutionInput(
                input_id="krx-daily", path=exec_path, hive_partitioned=False,
                trade_at_field="trade_at", instrument_field="instrument",
                is_tradable_field="is_tradable", price_fields={"close": "close"},
            ),
            fill=FillConvention(
                selector=FillSelector.NEXT_ELIGIBLE, at=time(15, 30),
                timezone="Asia/Seoul", trade_price="close",
            ),
        ),
        exchange=Academic(
            listings=(Listing(instrument_id="A005930", access=ListingAccess.SIGNED),),
            quantity_step=Decimal("1"), price_step=Decimal("0.1"),
            costs=(VenueCost(side="buy", commission_rate=Decimal("0.0015"),
                             tax_rate=Decimal(0)),),
        ),
        account=InitialAccount(
            snapshot=AccountSnapshot(version=0, cash=Decimal("1000000"), positions={}),
            mode=AccountMode.SIGNED,
        ),
        constraints=(
            (
                ConstraintDeclaration(
                    constraint=getattr(authored_strategies, sys.argv[6]),
                    config={}, name="cap",
                ),
            )
            if len(sys.argv) > 6
            else ()
        ),
        instruments=("A005930",), initial_strategy_state=None,
    )

    strategy = getattr(authored_strategies, which)
    project = vqapr.open(root)
    if len(sys.argv) > 4 and sys.argv[4] == "readback":
        completed = project.run_completed(
            definition=simulation, strategy=strategy, run_id="probe"
        )
        summary = completed.summary
        account = completed.account
        fills = completed.fills()
        print(
            f"ACCOUNT|{account.version}|{account.cash}|{len(fills)}|"
            f"{sorted(completed.tables)}"
        )
        print(f"DIAGROWS|{len(completed.tables.get('alpha.signal', ()))}")
        if fills:
            print(f"FIELDS|{sorted(fills[0])}")
    else:
        summary = project.simulate(
            definition=simulation, strategy=strategy, run_id="probe"
        )
        if len(sys.argv) > 4 and sys.argv[4] == "reasons":
            from vqapr._internal.run_bridge import execute_frozen_run, frozen_run_for

            definition = project._engine_definition(simulation, strategy, "reasons")
            replay = execute_frozen_run(root, frozen_run_for(root, definition))
            for trace in replay.occurrences:
                reason = getattr(getattr(trace, "result", None), "reason", None)
                if reason:
                    print(f"REASON|{reason}")
    print(
        f"{summary.occurrences},{summary.accepted_intents},"
        f"{summary.executions},{summary.final_account_version}"
    )
    '''
)


@pytest.fixture
def workspace(tmp_path):
    """A real importable strategy module plus a real execution table."""
    (tmp_path / "authored_strategies.py").write_text(STRATEGIES, encoding="utf-8")
    (tmp_path / "runner.py").write_text(RUNNER, encoding="utf-8")

    prices = tmp_path / "price.parquet"
    price_connection = duckdb.connect()
    price_connection.execute(
        f"""COPY (SELECT * FROM (VALUES
        ('A005930', TIMESTAMPTZ '2024-03-04 14:00:00+09', 72000.0),
        ('A005930', TIMESTAMPTZ '2024-03-05 14:00:00+09', 72500.0)
        ) AS t(instrument, available_at, close))
        TO '{prices.as_posix()}' (FORMAT PARQUET)"""
    )
    price_connection.close()

    execution = tmp_path / "exec.parquet"
    connection = duckdb.connect()
    connection.execute(
        f"""COPY (SELECT * FROM (VALUES
        ('A005930', TIMESTAMPTZ '2024-03-04 15:30:00+09', TRUE, 72000.0),
        ('A005930', TIMESTAMPTZ '2024-03-05 15:30:00+09', TRUE, 72500.0)
        ) AS t(instrument, trade_at, is_tradable, close))
        TO '{execution.as_posix()}' (FORMAT PARQUET)"""
    )
    connection.close()

    root = tmp_path / "project"
    root.mkdir()
    return tmp_path, root, execution, prices


def _run(workspace, which: str) -> tuple[int, int, int, int]:
    tmp_path, root, execution, _ = workspace
    result = subprocess.run(
        [sys.executable, str(tmp_path / "runner.py"), str(root), str(execution), which],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return tuple(int(part) for part in result.stdout.strip().splitlines()[-1].split(","))


def test_a_public_simulation_runs_end_to_end(workspace):
    """Only public declarations in, a real executed run out."""
    occurrences, intents, executions, version = _run(workspace, "Idle")

    # Two sessions, each dispatching a strategy callback and a valuation, plus the
    # executions those imply.
    assert occurrences > 0
    assert executions > 0
    # An idle strategy accepts no intent, and its account therefore never advances.
    assert intents == 0
    assert version == 0


def test_an_active_strategy_produces_intents_and_advances_the_account(workspace):
    """The difference from Idle is the author's decision, nothing else."""
    occurrences, intents, executions, version = _run(workspace, "Buyer")

    assert intents == 2, "one accepted intent per strategy occurrence"
    assert executions == 2
    # Every accepted intent commits an account version.
    assert version == intents
    assert occurrences == 6


def test_the_author_never_mints_framework_identity(workspace):
    """`Buyer` returns only a Rebalance - no UUID, strategy id, source refs or version.

    The legacy protocol required all four on every intent. If the framework were not
    stamping them, this run could not have produced an accepted intent at all.
    """
    tmp_path, _, _, _ = workspace
    source = (tmp_path / "authored_strategies.py").read_text(encoding="utf-8")
    for minted in ("uuid5", "intent_id", "source_refs", "account_version"):
        assert minted not in source

    _, intents, _, _ = _run(workspace, "Buyer")
    assert intents == 2


def test_a_strategy_that_reads_a_registered_dataset_runs(workspace):
    """A dataset registered through the public surface must reach the run declaring it.

    `Project.register` commits to the catalog while preflight resolves out of the legacy
    Workspace. Without a bridge between them every `DatasetDeclaration` is invisible to
    `simulate()`, and a strategy declaring `inputs()` fails with
    "dataset 'price_daily' must be registered in this workspace".
    """
    _tmp_path, root, _execution, prices = workspace
    import vqapr
    from vqapr.project import DatasetDeclaration

    project = vqapr.open(root)
    receipt = project.register(
        DatasetDeclaration(
            dataset_id="price_daily",
            path=prices,
            hive_partitioned=False,
            instrument_field="instrument",
            available_at_field="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        )
    )
    assert receipt.created is True

    occurrences, intents, _executions, _version = _run(workspace, "Reader")
    # It ran at all: that is the assertion. A Hold-only strategy accepts no intent.
    assert occurrences > 0
    assert intents == 0


def _run_readback(workspace, which: str) -> str:
    tmp_path, root, execution, _prices = workspace
    result = subprocess.run(
        [sys.executable, str(tmp_path / "runner.py"), str(root), str(execution), which,
         "readback"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_a_completed_run_exposes_its_account_and_fills(workspace):
    """`simulate` returns counts only; research needs the account and the costs.

    show_004's cost comparison and show_005's fill-journal replay were both blocked on
    this: a run whose commission, tax and dealt quantity cannot be inspected afterwards
    is not usable for research, however green it looks.
    """
    stdout = _run_readback(workspace, "Buyer")
    line = [ln for ln in stdout.splitlines() if ln.startswith("ACCOUNT|")]
    assert line, stdout
    _, version, cash, fill_count, tables = line[0].split("|", 4)

    assert int(version) == 2
    assert Decimal(cash) > 0
    assert int(fill_count) == 2
    assert "vqapr.fill" in tables


def test_fills_carry_the_cost_fields_research_needs(workspace):
    """Commission, tax and dealt quantity: what a cost comparison is made of."""
    stdout = _run_readback(workspace, "Buyer")
    fields = [ln for ln in stdout.splitlines() if ln.startswith("FIELDS|")]
    assert fields, stdout
    for required in ("commission", "tax", "dealt_quantity", "price", "cash_delta"):
        assert required in fields[0], f"{required} missing from {fields[0]}"


def test_reading_a_table_the_run_never_recorded_raises(workspace):
    """An absent table is an error, not an empty tuple that looks like no activity."""
    from vqapr._internal.run_bridge import CompletedRun, RunAccount, SimulationSummary

    completed = CompletedRun(
        summary=SimulationSummary(
            occurrences=1, accepted_intents=0, executions=0, final_account_version=None
        ),
        account=RunAccount(version=0, cash=Decimal(0), positions={}),
        tables={"vqapr.weight": ()},
    )
    assert completed.fills() == ()
    with pytest.raises(KeyError, match="recorded no table"):
        completed.table("never.recorded")


def test_a_declared_monitoring_cadence_reaches_the_engine(workspace):
    """`schedule_bridge` built the monitoring agenda; `_engine_definition` dropped it.

    A declared Cadence that is computed and then discarded is worse than an unsupported
    one: the caller has every reason to believe monitoring is running. The proof is that
    declaring it changes the dispatched occurrence count.
    """
    tmp_path, root, execution, _prices = workspace

    def _occurrences(*extra: str) -> int:
        result = subprocess.run(
            [sys.executable, str(tmp_path / "runner.py"), str(root), str(execution),
             "Idle", *extra],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        counts = [ln for ln in result.stdout.splitlines() if "," in ln][-1]
        return int(counts.split(",")[0])

    unmonitored = _occurrences()
    monitored = _occurrences("plain", "monitored")

    # Two sessions declared, so two monitoring occurrences are dispatched.
    assert monitored == unmonitored + 2


def test_an_authored_strategy_can_see_a_committed_nav(workspace):
    """`EconomicAccountView.nav` was hardcoded None, so weight-based rules were impossible.

    The contract couples nav with nav_observed_at, and a NAV must never be synthesized
    from cash and positions - it is read from committed valuations or it is None.
    """
    tmp_path, root, execution, _prices = workspace
    result = subprocess.run(
        [sys.executable, str(tmp_path / "runner.py"), str(root), str(execution),
         "NavWatcher", "reasons"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr

    reasons = [ln.split("|", 1)[1] for ln in result.stdout.splitlines()
               if ln.startswith("REASON|")]
    assert reasons, result.stdout

    # Before any committed valuation there is no NAV; after one, the view carries it.
    assert any("view-False" in r for r in reasons), reasons
    assert any("view-True" in r for r in reasons), reasons
    # nav and nav_observed_at are set or absent together on every callback.
    assert all("coupled-True" in r for r in reasons), reasons


def test_authored_diagnostic_rows_reach_the_recorder(workspace):
    """Declared, validated, and previously discarded.

    `_decide` never forwarded `prepared.diagnostics` and `AdaptedStrategy` never declared
    the authored tables, so an author's diagnostic rows were schema-checked and dropped.
    show_005 had to abandon its recorder claim over exactly this.
    """
    stdout = _run_readback(workspace, "Diagnosing")
    line = [ln for ln in stdout.splitlines() if ln.startswith("ACCOUNT|")]
    assert line, stdout
    tables = line[0].split("|", 4)[4]
    assert "alpha.signal" in tables, tables

    # The table name alone proves only that it was DECLARED. Rows prove it was forwarded.
    rows = [ln for ln in stdout.splitlines() if ln.startswith("DIAGROWS|")]
    assert rows, stdout
    assert int(rows[0].split("|", 1)[1]) > 0, "authored diagnostic rows never reached the recorder"


def test_the_framework_stamps_provenance_around_authored_rows(workspace):
    """The author supplies semantics; the framework supplies identity."""
    tmp_path, root, execution, _prices = workspace
    result = subprocess.run(
        [sys.executable, str(tmp_path / "runner.py"), str(root), str(execution),
         "Diagnosing", "readback"],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [ln for ln in result.stdout.splitlines() if ln.startswith("DIAGROWS|")]
    assert rows and int(rows[0].split("|", 1)[1]) > 0, result.stdout


def _run_constrained(workspace, which: str, constraint: str):
    tmp_path, root, execution, _prices = workspace
    return subprocess.run(
        [sys.executable, str(tmp_path / "runner.py"), str(root), str(execution), which,
         "plain", "unmonitored", constraint],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(tmp_path),
    )


def test_a_declared_constraint_runs_at_all(workspace):
    """Every constraint-bearing Simulation failed before this.

    `_engine_definition` registered the component as `{run_id}-{name}` while the adapted
    constraint reported the bare `{name}`, and the engine requires them equal - so
    `constraints=()` was the only shape that worked.
    """
    result = _run_constrained(workspace, "Buyer", "SingleNameCap")
    assert result.returncode == 0, result.stdout + result.stderr

    counts = [ln for ln in result.stdout.splitlines() if "," in ln][-1]
    accepted = int(counts.split(",")[1])
    # A cap of 0.60 leaves the strategy's 0.5 target alone.
    assert accepted == 2, result.stdout


def test_a_binding_constraint_actually_refuses_the_intent(workspace):
    """A constraint that loads but never bites would pass a weaker check.

    `TightCap` caps at 0.10 while the strategy asks for 0.5, so the run must be refused
    rather than quietly clipped or ignored.
    """
    result = _run_constrained(workspace, "Buyer", "TightCap")
    assert result.returncode != 0, (
        "a 0.10 cap must refuse a 0.5 target; the run succeeded instead:\n"
        + result.stdout
    )
    assert "violates projected constraints" in result.stdout + result.stderr
