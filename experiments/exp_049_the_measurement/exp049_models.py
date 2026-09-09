"""One reduction, three registrations: the annual-fundamentals model `docs/issues/archive/049` measured.

The model is the enhanced-index one, step for step -- consolidated annual rows only, the latest
dump bundle wins, an ORDERED FALLBACK among account codes (never a sum), one statement per fiscal
year, the prior year's assets only across a 10-15 month gap, and book equity by a three-step
chain that records which step answered. What differs between the three classes is only *where
the reduction's first three steps happen*:

| class      | registration                                   | steps 1-3 happen in |
|------------|------------------------------------------------|---------------------|
| `OnRows`   | the vendor's long table, `grain: rows`         | Python, per evaluation, over `rows(alias)` |
| `OnExpr`   | the SAME long file, `grain: instrument_instant`, each item an aggregate expression | duckdb, once per run, when the panel is built |
| `OnWide`   | a pre-pivoted parquet, `grain: instrument_instant` | the preparation script, before registration |

Steps 4 and 5 (`_reduce_statements`, `_derive`) are one shared function, so a difference in the
published rows can only come from the read, which is what the anti-join checks.

Timing: when `EXP049_TIMING_FILE` is set, every `compute` appends one JSON line with the seconds
its own body took, so the harness can separate the model's time from the framework's.
"""

from __future__ import annotations

import json
import os
import time
from decimal import Decimal, InvalidOperation

from vqapr import authoring as va

TIMEZONE = "Asia/Seoul"
LOOKBACK_DAYS = 1150
"""Enough to reach two consecutive annual statements, with the margin the original carried."""

INSTANTS_LOOKBACK = 12
"""`grain: rows` admits only `InstantsLookback`, and a calendar span is refused on it
(`lookback_fits_grain`), so the long side cannot say "1150 days" the way the original model did.

Twelve instants is three fiscal years: the generator publishes four availability instants a year
per name (March, June, September and December quarters; the December annual row shares the
quarter's instant). The reduction keeps only the last two fiscal years, so reaching a third
changes nothing in the published rows, and the anti-join is what proves that.

This was `2000` while the read counted source rows rather than instants (`docs/issues/archive/053`): a
name carried between ~250 and ~600 rows a year, so the number had to be argued in a docstring
rather than read off the calendar. Deletion campaign Step 1 made the count mean what the type
says, and the number became the one the question has."""

CONSOLIDATED_SCOPE = "C"
ANNUAL_SETTLEMENT_TYPE = "D"
PRIOR_ASSET_GAP_MONTHS = (10, 15)

ITEMS = (
    "total_assets",
    "total_liabilities",
    "total_equity",
    "controlling_equity",
    "noncontrolling_interest",
    "operating_income",
    "interest_expense",
    "depreciation",
    "amortization",
)

ACCOUNT_CODES: dict[str, tuple[str, ...]] = {
    # primary code first; the fallback is consulted only when the primary has no value.
    "total_assets": ("115000", "115001"),
    "total_liabilities": ("215000", "215001"),
    "total_equity": ("315000", "315001"),
    "controlling_equity": ("315100", "315101"),
    "noncontrolling_interest": ("315200", "315201"),
    "operating_income": ("412000", "412001"),
    "interest_expense": ("413100", "413101"),
    "depreciation": ("511000", "511001"),
    "amortization": ("512000", "512001"),
}

CODE_TO_ITEM: dict[str, str] = {}
CODE_PRIORITY: dict[str, int] = {}
for _item in ITEMS:
    for _priority, _code in enumerate(ACCOUNT_CODES[_item]):
        CODE_TO_ITEM[_code] = _item
        CODE_PRIORITY[_code] = _priority

BOOK_EQUITY_SOURCES = {
    "total_equity_minus_nci": 1,
    "controlling_equity_fallback": 2,
    "assets_minus_liabilities_minus_nci_fallback": 3,
}

OUTPUT_FIELDS = (
    "fiscal_year",
    "fiscal_yyyymm",
    "book_equity",
    "book_equity_source",
    "ebitda",
    "interest_expense",
    "total_assets",
    "prior_total_assets",
)


def item_expression(item: str) -> str:
    """The aggregate expression that performs steps 1-3 for one item inside duckdb.

    `arg_max(value, dump)` is "the latest bundle wins"; the `FILTER` is the scope and settlement
    test; `coalesce` over the codes in priority order is the ordered fallback.
    """
    picks = ", ".join(
        f"arg_max(numeric_value, dump_last_modified) FILTER (WHERE statement_scope = "
        f"'{CONSOLIDATED_SCOPE}' AND settlement_type = '{ANNUAL_SETTLEMENT_TYPE}' "
        f"AND account_code = '{code}')"
        for code in ACCOUNT_CODES[item]
    )
    return f"coalesce({picks})"


FISCAL_EXPRESSION = (
    f"max(fiscal_yyyymm) FILTER (WHERE statement_scope = '{CONSOLIDATED_SCOPE}' "
    f"AND settlement_type = '{ANNUAL_SETTLEMENT_TYPE}')"
)


def _months_between(earlier: int, later: int) -> int:
    return (later // 100 - earlier // 100) * 12 + (later % 100 - earlier % 100)


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _derive(values: dict[str, Decimal]) -> dict[str, object] | None:
    nci = values.get("noncontrolling_interest") or Decimal(0)
    total_equity = values.get("total_equity")
    controlling = values.get("controlling_equity")
    total_assets = values.get("total_assets")
    total_liabilities = values.get("total_liabilities")

    if total_equity is not None:
        book_equity, source = total_equity - nci, "total_equity_minus_nci"
    elif controlling is not None:
        book_equity, source = controlling, "controlling_equity_fallback"
    elif total_assets is not None and total_liabilities is not None:
        book_equity = total_assets - total_liabilities - nci
        source = "assets_minus_liabilities_minus_nci_fallback"
    else:
        return None

    operating_income = values.get("operating_income")
    depreciation = values.get("depreciation") or Decimal(0)
    amortization = values.get("amortization") or Decimal(0)
    ebitda = None if operating_income is None else operating_income + depreciation + amortization
    return {
        "book_equity": book_equity,
        "book_equity_source": BOOK_EQUITY_SOURCES[source],
        "ebitda": ebitda,
        "interest_expense": values.get("interest_expense"),
        "total_assets": total_assets,
    }


def _reduce_statements(
    statements: dict[tuple[str, int], dict[str, Decimal]],
) -> list[dict[str, object]]:
    """Steps 4-5, shared by every registration: one statement per fiscal year, the last two."""
    by_instrument: dict[str, list[tuple[int, dict[str, Decimal]]]] = {}
    for (instrument, period), values in statements.items():
        by_instrument.setdefault(instrument, []).append((period, values))

    emitted: list[dict[str, object]] = []
    for instrument, periods in sorted(by_instrument.items()):
        periods.sort(key=lambda entry: entry[0])
        by_year: dict[int, tuple[int, dict[str, Decimal]]] = {}
        for period, values in periods:
            by_year[period // 100] = (period, values)
        ordered = [by_year[year] for year in sorted(by_year)]
        if not ordered:
            continue
        period, values = ordered[-1]
        record = _derive(values)
        if record is None:
            continue
        record["prior_total_assets"] = None
        if len(ordered) >= 2:
            previous_period, previous_values = ordered[-2]
            gap = _months_between(previous_period, period)
            if PRIOR_ASSET_GAP_MONTHS[0] <= gap <= PRIOR_ASSET_GAP_MONTHS[1]:
                record["prior_total_assets"] = previous_values.get("total_assets")
        record["instrument"] = instrument
        record["fiscal_year"] = period // 100
        record["fiscal_yyyymm"] = period
        emitted.append(record)
    return emitted


class _Timed(va.DataModel):
    """Times its own callback, and separates the read from the reduction.

    The read happens inside `compute` -- `call.rows(alias)` runs the scan, `call.read(alias,
    field)` slices the panel -- so a callback's wall time is read + reduce, and the two are
    reported apart: `read_s` is what the framework spent handing the model its window, and
    `reduce_s` is the model's own arithmetic, which `049` found to be the same on both sides.
    """

    label = ""

    def compute(self, call):
        started = time.perf_counter()
        self._read_s = 0.0
        rows = self._compute(call)
        elapsed = time.perf_counter() - started
        target = os.environ.get("EXP049_TIMING_FILE")
        if target:
            with open(target, "a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "model": self.label,
                            "evaluation_time": call.evaluation_time.isoformat(),
                            "compute_s": elapsed,
                            "read_s": self._read_s,
                            "reduce_s": elapsed - self._read_s,
                            "rows": len(rows),
                        }
                    )
                    + "\n"
                )
        return rows

    def _timed_read(self, action):
        started = time.perf_counter()
        result = action()
        self._read_s += time.perf_counter() - started
        return result

    def _compute(self, call):  # pragma: no cover - abstract by convention
        raise NotImplementedError


class OnRows(_Timed):
    """The vendor's long table, read as observations; steps 1-3 in Python, every evaluation."""

    label = "rows"

    def inputs(self):
        return {
            "facts": va.DatasetInput(
                dataset_id="sf_rows",
                fields=(
                    "statement_scope",
                    "settlement_type",
                    "account_code",
                    "fiscal_yyyymm",
                    "dump_last_modified",
                    "numeric_value",
                ),
                lookback=va.InstantsLookback(instants=INSTANTS_LOOKBACK),
            )
        }

    def _compute(self, call):
        observations = self._timed_read(lambda: call.rows("facts"))
        best: dict[tuple[str, int, str], tuple[object, Decimal]] = {}
        for row in observations:
            values = row.values
            if values["statement_scope"] != CONSOLIDATED_SCOPE:
                continue
            if values["settlement_type"] != ANNUAL_SETTLEMENT_TYPE:
                continue
            code = values["account_code"]
            if code not in CODE_TO_ITEM:
                continue
            value = _decimal(values["numeric_value"])
            if value is None:
                continue
            key = (row.instrument_id, int(values["fiscal_yyyymm"]), code)
            stamp = values["dump_last_modified"]
            current = best.get(key)
            if current is None or (
                stamp is not None and current[0] is not None and stamp > current[0]
            ):
                best[key] = (stamp, value)

        statements: dict[tuple[str, int], dict[str, tuple[int, Decimal]]] = {}
        for (instrument, period, code), (_stamp, value) in best.items():
            item = CODE_TO_ITEM[code]
            priority = CODE_PRIORITY[code]
            bucket = statements.setdefault((instrument, period), {})
            held = bucket.get(item)
            if held is None or priority < held[0]:
                bucket[item] = (priority, value)

        reduced = {
            key: {item: value for item, (_priority, value) in bucket.items()}
            for key, bucket in statements.items()
        }
        return _reduce_statements(reduced)


class _OnPanel(_Timed):
    """A panel-grain registration whose columns already are the items; steps 4-5 only."""

    dataset_id = ""

    def inputs(self):
        return {
            "facts": va.DatasetInput(
                dataset_id=self.dataset_id,
                fields=("fiscal_yyyymm", *ITEMS),
                lookback=va.CalendarLookback(days=LOOKBACK_DAYS, timezone=TIMEZONE),
            )
        }

    def _compute(self, call):
        fiscal = self._timed_read(lambda: call.read("facts", "fiscal_yyyymm"))
        columns = self._timed_read(
            lambda: {item: call.read("facts", item).values for item in ITEMS}
        )
        statements: dict[tuple[str, int], dict[str, Decimal]] = {}
        for instrument in fiscal.instruments:
            periods = fiscal.values[instrument]
            for index, period in enumerate(periods):
                if period is None:
                    continue
                values: dict[str, Decimal] = {}
                for item in ITEMS:
                    value = _decimal(columns[item][instrument][index])
                    if value is not None:
                        values[item] = value
                statements[(instrument, int(period))] = values
        return _reduce_statements(statements)


class OnExpr(_OnPanel):
    """The same long file as `OnRows`, pivoted by the registration's expressions."""

    label = "expr"
    dataset_id = "sf_expr"


class OnWide(_OnPanel):
    """A parquet pivoted before registration -- `049`'s `wide` case, unchanged."""

    label = "wide"
    dataset_id = "sf_wide"
