"""The acceptance criteria of `docs/issues/archive/049`'s ruling, read one at a time.

The campaign's own measurement is 614x on a Korean statement warehouse
(`kwam-enhanced-index/vqapr-performance-testbed/`), which this suite cannot carry. What it can
carry is the property that measurement depends on and that a fast wrong answer would break: **the
same facts registered long, with the reduction written as field expressions, deliver exactly what
the pre-pivoted registration delivers.** A materialization that is 600x faster and slightly
different is a different model rather than a faster one, so the equality is checked as a full
anti-join in both directions rather than as a spot comparison.

The other two criteria are the ruling's other halves: a dataset with no instrument axis is not
narrowed by a run's instrument list (`docs/issues/archive/038`), and a requirement is a field id and a
lookback and nothing else.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from vqapr.data.lookback import CalendarLookback, InstantsLookback, RowsLookback
from vqapr.data.requirement import DataRequirement
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.window import ModelWindow
from vqapr.domain.errors import VqaprError
from vqapr.project.store import Workspace
from vqapr.public import DatasetRegistration, SourceSpec, register_dataset

EVALUATED_AT = datetime(2024, 4, 1, tzinfo=UTC)

# Eight published values, as the campaign's own model publishes eight.
ACCOUNTS = {
    "net_income": "111000",
    "operating_income": "112000",
    "revenue": "113000",
    "total_assets": "121000",
    "total_equity": "122000",
    "total_debt": "123000",
    "operating_cash_flow": "131000",
    "capital_expenditure": "132000",
}

# (instrument, available_at, account, value, dump). Two dumps disagree on one cell, which is the
# decision a pivot cannot avoid making and an expression states out loud: latest dump wins.
_FACTS = [
    ("A", "2024-01-31", "111000", 10.0, 1),
    ("A", "2024-01-31", "111000", 11.5, 2),
    ("A", "2024-01-31", "112000", 20.0, 1),
    ("A", "2024-01-31", "113000", 30.0, 1),
    ("A", "2024-01-31", "121000", 40.0, 1),
    ("A", "2024-01-31", "122000", 50.0, 1),
    ("A", "2024-01-31", "123000", 60.0, 1),
    ("A", "2024-01-31", "131000", 70.0, 1),
    ("A", "2024-01-31", "132000", 80.0, 1),
    ("B", "2024-01-31", "111000", 1.0, 1),
    ("B", "2024-01-31", "112000", 2.0, 1),
    ("B", "2024-01-31", "113000", 3.0, 1),
    ("B", "2024-01-31", "121000", 4.0, 1),
    ("B", "2024-01-31", "122000", 5.0, 1),
    ("B", "2024-01-31", "123000", 6.0, 1),
    # B publishes no cash-flow rows at all on this date: an absent row must arrive as NULL, not as
    # a dropped instrument.
    ("A", "2024-02-29", "111000", 12.0, 1),
    ("A", "2024-02-29", "112000", 21.0, 1),
    ("A", "2024-02-29", "113000", 31.0, 1),
    ("A", "2024-02-29", "121000", 41.0, 1),
    ("A", "2024-02-29", "122000", 51.0, 1),
    ("A", "2024-02-29", "123000", 61.0, 1),
    ("A", "2024-02-29", "131000", 71.0, 1),
    ("A", "2024-02-29", "132000", 81.0, 1),
]


def _expression(code: str) -> str:
    """The reduction the long model would otherwise run in Python, written as a field.

    `arg_max(value, dump)` is the download-bundle tie-break the pivot has to decide anyway -- a
    column cannot hold two values. Written here it is declared, reviewable and covered by the
    run's source digest, instead of living in an ETL step upstream of the framework.
    """
    return f"arg_max(value, dump) FILTER (WHERE account_code = '{code}')"


@pytest.fixture
def warehouse(tmp_path: Path) -> tuple[Path, Path]:
    """The same facts twice: at the vendor's grain, and pre-pivoted."""
    long_dir = tmp_path / "long"
    wide_dir = tmp_path / "wide"
    long_dir.mkdir()
    wide_dir.mkdir()
    values = ", ".join(
        f"('{name}', TIMESTAMPTZ '{at} 00:00:00+00', '{code}', {value}::DOUBLE, {dump})"
        for name, at, code, value, dump in _FACTS
    )
    con = duckdb.connect()
    try:
        con.execute(
            f"""CREATE TABLE facts AS SELECT * FROM (VALUES {values})
                AS t(instrument, available_at, account_code, value, dump)"""
        )
        con.execute(f"COPY facts TO '{(long_dir / 'facts.parquet').as_posix()}' (FORMAT PARQUET)")
        pivoted = ", ".join(f"{_expression(code)} AS {name}" for name, code in ACCOUNTS.items())
        con.execute(
            f"""COPY (SELECT instrument, available_at, {pivoted} FROM facts GROUP BY 1, 2)
                TO '{(wide_dir / "facts.parquet").as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return long_dir, wide_dir


def _register(root: Path, dataset_id: str, path: Path, *, long: bool) -> None:
    register_dataset(
        root,
        DatasetRegistration.of(
            dataset_id,
            f"{dataset_id}-source",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=(
                ("available_at", "instrument", "account_code", "dump")
                if long
                else ("available_at", "instrument")
            ),
            # Both registrations expose the SAME eight field ids: a field id is unique within a
            # dataset, not across the workspace, and schema parity is what makes the two
            # comparable at all (`docs/issues/archive/049`, the owner's 2026-09-01 correction).
            fields={name: (_expression(code) if long else name) for name, code in ACCOUNTS.items()},
            # An expression's declared type is what it evaluates to: `arg_max` over a DOUBLE
            # column is a DOUBLE, and the pre-pivoted file carries the same eight DOUBLEs.
            field_types=dict.fromkeys(ACCOUNTS, "DOUBLE"),
        ),
        SourceSpec.of(f"{dataset_id}-source", path),
    )


def _read(workspace: Workspace, dataset_id: str) -> dict[str, tuple]:
    """Every published field, one requirement each, keyed by (instrument, instant)."""
    store = DuckDbObservationStore(workspace)
    rows: dict[tuple, dict[str, object]] = {}
    for name in ACCOUNTS:
        requirement = DataRequirement.of(
            dataset_id, name, lookback=CalendarLookback(days=365, timezone="UTC")
        )
        window = ModelWindow(
            evaluation_time=EVALUATED_AT,
            instruments=("A", "B"),
            store=store,
            allowed_requirements=(requirement,),
            consumer_id="annual-fundamentals",
        )
        for row in window.observations(requirement).rows:
            key = (str(row["instrument"]), row["available_at"])
            rows.setdefault(key, {})[name] = row[name]
    # Keyed on the instant itself, normalised to UTC: duckdb hands a stamp back in the session's
    # own zone, and the two registrations must agree on the instant rather than on its spelling.
    return {
        f"{instrument}|{instant.astimezone(UTC).isoformat()}": tuple(
            values.get(name) for name in sorted(ACCOUNTS)
        )
        for (instrument, instant), values in rows.items()
    }


def test_criterion_1_a_long_registration_is_byte_identical_to_the_wide_one(
    tmp_path: Path, warehouse: tuple[Path, Path]
) -> None:
    """A full anti-join, both directions, zero rows on either side. Checked before any timing.

    The whole campaign rests on this. `049` measures 614x between these two registrations of one
    warehouse, and a difference of one cell would mean the speed was bought by reading something
    else. The long side writes its reduction as field expressions -- the account pivot, and the
    latest-dump tie-break -- and the framework composes the grouping around it.
    """
    long_dir, wide_dir = warehouse
    Workspace.create(tmp_path)
    _register(tmp_path, "long", long_dir, long=True)
    _register(tmp_path, "wide", wide_dir, long=False)

    workspace = Workspace.open(tmp_path)
    assert workspace.dataset("long").aggregated is True, "the long registration groups"
    assert workspace.dataset("wide").aggregated is False, "the wide one is row-wise, as before"

    from_long = _read(workspace, "long")
    from_wide = _read(workspace, "wide")

    only_long = {key: from_long[key] for key in from_long if from_wide.get(key) != from_long[key]}
    only_wide = {key: from_wide[key] for key in from_wide if from_long.get(key) != from_wide[key]}
    assert only_long == {}, f"rows only the long registration produced: {only_long}"
    assert only_wide == {}, f"rows only the wide registration produced: {only_wide}"
    assert from_long, "the fixture must produce rows, or this proves nothing"

    # The one cell two download bundles disagree about resolves the same way on both sides, which
    # is the decision the pivot could not avoid and the expression states.
    key = f"A|{datetime(2024, 1, 31, tzinfo=UTC).isoformat()}"
    assert from_long[key][sorted(ACCOUNTS).index("net_income")] == 11.5
    # An instrument that published no rows for a field carries NULL rather than vanishing.
    absent = f"B|{datetime(2024, 1, 31, tzinfo=UTC).isoformat()}"
    assert from_long[absent][sorted(ACCOUNTS).index("operating_cash_flow")] is None


def test_criterion_2_a_dataset_with_no_instrument_axis_is_not_narrowed(tmp_path: Path) -> None:
    """`038`'s kimchi-ff5 shape: factor ids stay out of `instruments:`.

    `RMRF` and `SMB` are not instruments for any reader, and a table keyed on them has no
    instrument axis. So the declared instrument list does not apply to it, its rows carry no
    `instrument`, and the run's universe stays the universe.
    """
    factors = tmp_path / "factors"
    factors.mkdir()
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
                (TIMESTAMPTZ '2024-03-01 00:00:00+00', 'RMRF', 0.01::DOUBLE),
                (TIMESTAMPTZ '2024-03-01 00:00:00+00', 'SMB', 0.02::DOUBLE),
                (TIMESTAMPTZ '2024-03-02 00:00:00+00', 'RMRF', 0.03::DOUBLE),
                (TIMESTAMPTZ '2024-03-02 00:00:00+00', 'SMB', 0.04::DOUBLE)
              ) AS t(available_at, factor, value))
              TO '{(factors / "f.parquet").as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()

    Workspace.create(tmp_path)
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "kimchi-ff5",
            "kimchi-ff5-source",
            available_at="available_at",
            grain="instant",
            key_fields=("available_at", "factor"),
            fields={
                "rmrf": "sum(value) FILTER (WHERE factor = 'RMRF')",
                "smb": "sum(value) FILTER (WHERE factor = 'SMB')",
            },
            field_types={"rmrf": "DOUBLE", "smb": "DOUBLE"},
        ),
        SourceSpec.of("kimchi-ff5-source", factors),
    )

    workspace = Workspace.open(tmp_path)
    assert workspace.dataset("kimchi-ff5").instrument_field is None
    assert workspace.instruments("kimchi-ff5") == (), "no axis means no instruments to enumerate"

    requirement = DataRequirement.of("kimchi-ff5", "rmrf", lookback=RowsLookback(2))
    window = ModelWindow(
        evaluation_time=EVALUATED_AT,
        # The stocks the run is evaluated over. No factor id among them, which is the point.
        instruments=("A005930", "A000660"),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
        consumer_id="ff5-residual",
    )

    batch = window.observations(requirement)
    assert [row["rmrf"] for row in batch.rows] == pytest.approx([0.01, 0.03]), (
        "the declared instrument list must not filter a table that has no instrument axis"
    )
    assert all("instrument" not in row for row in batch.rows)
    assert batch.access.instruments == ()
    assert batch.access.actual_rows == {}


def test_criterion_3_a_requirement_is_a_field_and_a_lookback(
    tmp_path: Path, warehouse: tuple[Path, Path]
) -> None:
    """One field, no dataset id, no consumer id -- and provenance loses nothing."""
    long_dir, _ = warehouse
    Workspace.create(tmp_path)
    _register(tmp_path, "long", long_dir, long=True)
    workspace = Workspace.open(tmp_path)

    requirement = DataRequirement.of(
        "long", "net_income", lookback=CalendarLookback(days=365, timezone="UTC")
    )
    window = ModelWindow(
        evaluation_time=EVALUATED_AT,
        instruments=("A", "B"),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
        consumer_id="annual-fundamentals",
    )

    access = window.observations(requirement).access
    # Stamped by the framework from the component that read it, exactly as before.
    assert access.consumer_id == "annual-fundamentals"
    # And the dataset is on the record, resolved from the field rather than named by the reader.
    assert str(access.dataset_id) == "long"
    assert access.fields == ("net_income",)


def test_two_datasets_may_expose_the_same_field_ids(
    tmp_path: Path, warehouse: tuple[Path, Path]
) -> None:
    """Parallel series are the point, and the pair is what identifies a read.

    `049`'s ruling had a requirement name a field alone, on the grounds that a field id is unique
    across a workspace. Measured against this package's research environment that premise did not
    hold: 21 of its 27 datasets' field ids are exposed by more than one of them. Some are
    deliberately schema-identical parallel series -- `ff5-factors-broad` and `-k200` differ only in
    universe, which is what makes them comparable -- and some are just `fiscal_yyyymm` being what
    that column is called on all six datasets that carry it. The owner overturned that half of the
    ruling on 2026-09-01.

    So this pins the corrected rule: the same eight field ids on two registrations is not an error,
    and each requirement says which dataset it means. The fixture is the campaign's own pair, which
    is exactly the shape the research environment relies on.
    """
    long_dir, wide_dir = warehouse
    Workspace.create(tmp_path)
    _register(tmp_path, "long", long_dir, long=True)
    _register(tmp_path, "wide", wide_dir, long=False)

    workspace = Workspace.open(tmp_path)
    assert set(workspace.dataset("long").fields) == set(workspace.dataset("wide").fields), (
        "schema parity is the property parallel series exist for"
    )

    store = DuckDbObservationStore(workspace)
    read = {}
    for dataset_id in ("long", "wide"):
        requirement = DataRequirement.of(
            dataset_id, "net_income", lookback=CalendarLookback(days=365, timezone="UTC")
        )
        window = ModelWindow(
            evaluation_time=EVALUATED_AT,
            instruments=("A", "B"),
            store=store,
            allowed_requirements=(requirement,),
            consumer_id="annual-fundamentals",
        )
        batch = window.observations(requirement)
        read[dataset_id] = tuple(row["net_income"] for row in batch.rows)
        assert str(batch.access.dataset_id) == dataset_id, (
            "the requirement names which of the two it read, and provenance records that"
        )
    assert read["long"] == read["wide"]


def test_a_field_the_named_dataset_does_not_expose_is_refused(
    tmp_path: Path, warehouse: tuple[Path, Path]
) -> None:
    """The other half of the pair still has to be there, and the refusal names what is."""
    long_dir, _ = warehouse
    Workspace.create(tmp_path)
    _register(tmp_path, "long", long_dir, long=True)
    workspace = Workspace.open(tmp_path)

    requirement = DataRequirement.of(
        "long", "no_such_field", lookback=CalendarLookback(days=365, timezone="UTC")
    )
    window = ModelWindow(
        evaluation_time=EVALUATED_AT,
        instruments=("A", "B"),
        store=DuckDbObservationStore(workspace),
        allowed_requirements=(requirement,),
        consumer_id="annual-fundamentals",
    )

    with pytest.raises(VqaprError) as refused:
        window.observations(requirement)

    failure = refused.value.failures[0]
    assert failure.code == "store.field_missing"
    assert "net_income" in failure.observed, "the refusal must say what the dataset does expose"


def test_a_registration_that_mixes_the_two_shapes_is_refused(
    tmp_path: Path, warehouse: tuple[Path, Path]
) -> None:
    """Every field row-wise, or every field aggregating. A mixture has no grain.

    Neither shape binds, and duckdb's own message is carried up rather than paraphrased -- the
    binder is what decided, so the binder is what explains.
    """
    long_dir, _ = warehouse
    Workspace.create(tmp_path)

    with pytest.raises(VqaprError) as refused:
        register_dataset(
            tmp_path,
            DatasetRegistration.of(
                "mixed",
                "mixed-source",
                instrument_field="instrument",
                available_at="available_at",
                grain="instrument_instant",
                key_fields=("available_at", "instrument", "account_code", "dump"),
                fields={"summed": _expression("111000"), "raw": "value"},
                field_types={"summed": "DOUBLE", "raw": "DOUBLE"},
            ),
            SourceSpec.of("mixed-source", long_dir),
        )

    failure = refused.value.failures[0]
    assert failure.code == "dataset.projection_unbindable"
    assert "row-wise:" in failure.observed and "grouped:" in failure.observed


def test_a_field_expression_may_not_carry_its_own_from(tmp_path: Path) -> None:
    """The property that makes a look-ahead unwritable rather than merely discouraged.

    An expression is evaluated inside the window the framework drew. A scalar subquery brings its
    own `FROM`, so it can read rows that window excludes -- and it is the only expression form
    that can.
    """
    prices = tmp_path / "prices"
    prices.mkdir()
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
                (TIMESTAMPTZ '2024-03-01 00:00:00+00', 'A', 100.0::DOUBLE)
              ) AS t(available_at, instrument, close))
              TO '{(prices / "p.parquet").as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()

    Workspace.create(tmp_path)
    with pytest.raises(VqaprError) as refused:
        register_dataset(
            tmp_path,
            DatasetRegistration.of(
                "peeking",
                "peeking-source",
                instrument_field="instrument",
                available_at="available_at",
                grain="instrument_instant",
                key_fields=("available_at", "instrument"),
                fields={"tomorrow": "(SELECT max(close) FROM read_parquet('*.parquet'))"},
                field_types={"tomorrow": "DOUBLE"},
            ),
            SourceSpec.of("peeking-source", prices),
        )

    assert refused.value.failures[0].code == "dataset.field_not_an_expression"


def test_a_bounded_grouped_read_returns_the_unbounded_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `RowsLookback` proof must count what the projection PRODUCES, in both places it is taken.

    Lane B made a bounded read cost one statement rather than two by having the read carry its own
    proof: the same count is computed once as a cold-start `GROUP BY` and once as a window
    aggregate inside the read. A grouped registration is where the two can come apart, because a
    long source carries several rows per instant and a `RowsLookback` counts instants.

    `SPARSE` is built so the two ways of counting disagree about it. It publishes on five instants
    inside the bound window, two account rows on each: the values the projection produces number
    5, short of the declared 8, so it is unsafe and must be read unbounded; the source's rows
    number 10, which would prove it safe and lose the older instants the window was declared to
    include.

    **On this fixture the wrong count is loud, and that is not a safety net.** Every field here is
    an aggregate, so counting the source through them is `count(sum(...))` -- a nested aggregate
    duckdb refuses to bind. Checked by making `_counted` return the row-wise vocabulary for a
    grouped registration: this test then fails with `Binder Error: aggregate function calls cannot
    be nested`, before any answer is produced.

    **Do not read that as the binder guarding it.** A grouped registration may expose a field that
    is a bare grouping key -- `fields: {stamp: <the available_at column>, total: sum(x)}` binds
    grouped, because the key is grouped by -- and `count(<that column>)` binds perfectly well over
    the source while counting something else entirely. The guard is `_Counted`, which gives the
    statement and the sidecar one vocabulary structurally; the binder merely happens to catch the
    all-aggregate case first.
    """
    from vqapr.data import scan
    from vqapr.data.scan import ScanSession

    # The production gate keeps a fixture-sized source on the unbounded path, so without this the
    # assertion would pass by never taking the bound it exists to guard.
    monkeypatch.setattr(scan, "ROWS_BOUND_MIN_BYTES", 0)

    instants = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index) for index in range(40)]
    facts: list[str] = []
    for index, instant in enumerate(instants):
        stamp = f"TIMESTAMPTZ '{instant.isoformat()}'"
        for code in ("111000", "112000"):
            # DENSE publishes throughout; SPARSE stops after the bound window's first five.
            facts.append(f"('DENSE', {stamp}, '{code}', {100 + index}.0::DOUBLE)")
            if index <= 20:
                facts.append(f"('SPARSE', {stamp}, '{code}', {200 + index}.0::DOUBLE)")

    source_dir = tmp_path / "long"
    source_dir.mkdir()
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES {", ".join(facts)})
                AS t(instrument, available_at, account_code, value))
                TO '{(source_dir / "facts.parquet").as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()

    Workspace.create(tmp_path)
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "facts",
            "facts-source",
            instrument_field="instrument",
            available_at="available_at",
            grain="rows",
            key_fields=("available_at", "instrument", "account_code"),
            fields={
                "net_income": "sum(value) FILTER (WHERE account_code = '111000')",
                "operating_income": "sum(value) FILTER (WHERE account_code = '112000')",
            },
            field_types={"net_income": "DOUBLE", "operating_income": "DOUBLE"},
        ),
        SourceSpec.of("facts-source", source_dir),
    )
    workspace = Workspace.open(tmp_path)
    assert workspace.dataset("facts").aggregated is True

    # A per-name window on a grouped projection is a rows-grain read since record `137`: the
    # table is registered at the vendor's grain, the expressions still collapse it to one row per
    # (instant, instrument), and `InstantsLookback` ranks each name's own instants -- which is
    # exactly the bounded read lane B proved. On a panel grain the same number would be the
    # table's last eight instants, and SPARSE would not fill them; that is the design, not a gap.
    requirement = DataRequirement.of("facts", "net_income", lookback=InstantsLookback(8))
    evaluated_at = instants[-1] + timedelta(hours=1)

    def read(store: DuckDbObservationStore) -> tuple:
        window = ModelWindow(
            evaluation_time=evaluated_at,
            instruments=("DENSE", "SPARSE"),
            store=store,
            allowed_requirements=(requirement,),
            consumer_id="proof-probe",
        )
        return tuple(
            (str(row["instrument"]), row["available_at"], row["net_income"])
            for row in window.observations(requirement).rows
        )

    # No session means no bound is even guessed: this is the answer the window declares.
    unbounded = read(DuckDbObservationStore(workspace))
    with ScanSession() as session:
        bounded = read(DuckDbObservationStore(workspace, session=session))

    assert bounded == unbounded, (
        "the bounded read must return the unbounded answer; a proof that counted source rows "
        "instead of the values the projection produces would drop SPARSE's older instants"
    )
    # And the window really does reach past the bound, or the comparison proves nothing.
    sparse = [instant for name, instant, _ in unbounded if name == "SPARSE"]
    assert len(sparse) == 8, "SPARSE must fill its declared window from instants it published on"
