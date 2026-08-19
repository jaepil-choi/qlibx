"""A holding the venue stopped quoting keeps its last price, and says how old it is."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vqapr.account.snapshot import AccountSnapshot
from vqapr.data.store import DuckDbObservationStore
from vqapr.public import (
    DataRequirement,
    DatasetRegistration,
    RowsLookback,
    SourceSpec,
    Workspace,
    _marks_for_occurrence,
)
from vqapr.valuation.marking import SelectedMark, ValuationService

SESSIONS = tuple(datetime(2024, 1, day, 6, 30, tzinfo=UTC) for day in range(1, 11))
LAST_QUOTED = 4
"""`HALT` stops appearing after this many sessions."""


class _FrozenRun:
    """The single attribute the mark provider reads."""

    class valuation:
        mark_requirement = DataRequirement.of(
            "valuation", "prices", fields=("close",), lookback=RowsLookback(1)
        )


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    rows: list[dict[str, object]] = []
    for index, stamp in enumerate(SESSIONS):
        rows.append(
            {"available_at": stamp, "instrument": "LIVE", "close": Decimal(100 + index)}
        )
        if index < LAST_QUOTED:
            rows.append(
                {"available_at": stamp, "instrument": "HALT", "close": Decimal(200 + index)}
            )
    source = tmp_path / "prices.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            rows,
            schema=pa.schema(
                [
                    ("available_at", pa.timestamp("us", tz="UTC")),
                    ("instrument", pa.string()),
                    ("close", pa.decimal128(18, 4)),
                ]
            ),
        ),
        source,
    )
    space = Workspace.create(tmp_path)
    space.register_dataset(
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("prices-source", source),
    )
    return space


def _marks(workspace: Workspace, account: AccountSnapshot) -> dict[str, SelectedMark]:
    selected = _marks_for_occurrence(
        DuckDbObservationStore(workspace), _FrozenRun, SESSIONS[-1], account
    )
    return {mark.instrument_id: mark for mark in selected}


def test_a_holding_that_stopped_quoting_keeps_its_last_price(workspace: Workspace) -> None:
    """Writing a halted position down to nothing would report a loss that did not happen."""
    account = AccountSnapshot(1, Decimal("1000"), {"LIVE": Decimal("10"), "HALT": Decimal("5")})

    marks = _marks(workspace, account)

    assert marks["HALT"].price == Decimal("203.0000")
    assert marks["HALT"].observed_at == SESSIONS[LAST_QUOTED - 1]


def test_each_mark_reports_how_old_its_price_is(workspace: Workspace) -> None:
    """Valuation states the observation instant; it does not decide what the gap means.

    A long halt and a delisting are identical at the cutoff and are told apart only by whether
    the instrument trades again, which is a fact from the future.
    """
    account = AccountSnapshot(1, Decimal("1000"), {"LIVE": Decimal("10"), "HALT": Decimal("5")})

    marks = _marks(workspace, account)

    assert marks["LIVE"].staleness(SESSIONS[-1]) == timedelta(0)
    assert marks["HALT"].staleness(SESSIONS[-1]) == timedelta(days=6)


def test_the_stale_position_still_carries_its_value_into_nav(workspace: Workspace) -> None:
    account = AccountSnapshot(1, Decimal("1000"), {"LIVE": Decimal("10"), "HALT": Decimal("5")})

    batch = ValuationService().mark(account, tuple(_marks(workspace, account).values()))

    # 10 x 109 held live, plus 5 x 203 carried at the last quoted price.
    assert batch.total_value == Decimal("2105.0000")


def test_a_mark_requires_a_timezone_aware_observation() -> None:
    with pytest.raises(ValueError, match="observed_at"):
        SelectedMark("A", Decimal("10"), datetime(2024, 1, 1, 6, 30))
