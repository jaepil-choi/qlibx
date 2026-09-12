"""A DataModel that derives one column from declared observations."""

from __future__ import annotations

from decimal import Decimal

from vqapr import authoring as va

DATASET_ID = "sample-prices"
FIELD = "close"
LOOKBACK = 6  # rows of the table: the same instants for every name


class SampleFeatures(va.DataModel):
    """Derives one value per instrument from `close` of `sample-prices`, each session.

    The example below is a trailing return and is a placeholder: replace the marked block, and
    this docstring, with what this model actually computes.
    """

    def inputs(self):
        read = va.DatasetInput(
            dataset_id=DATASET_ID, fields=(FIELD,), lookback=va.RowsLookback(rows=LOOKBACK)
        )
        return {
            "sample-prices": read
        }  # the alias is YOUR name for this read; `context.read` takes it

    def compute(self, context):
        #
        # This model declares a ROWS lookback on a panel-grain dataset, so the window is the
        # table's last N rows -- the same N instants for every name. A name that stopped
        # publishing contributes fewer values inside it rather than reaching further back, which
        # is what makes a cross-section built from this window safe. The reduction below is still
        # per instrument because a trailing return is a per-name question; the guard asks for a
        # full window. A calendar period instead of a row count is `--calendar-lookback DAYS`;
        # per-name counting (each name's own last N reported instants) is `InstantsLookback`
        # and belongs to a `grain: rows` dataset: `--instants-lookback N`.
        # One field of the alias as a window: `instants` x `instruments`, the same instants for
        # every name. `window.values[name]` is that name's values over them, `None` where it had
        # none; `window.current()` is the cross-section at the last instant (a name with no row
        # there is absent), `window.latest()` the newest value per name anywhere in the window.
        window = context.read("sample-prices", FIELD)
        history: dict[str, list[Decimal]] = {}
        for name in window.instruments:
            # A DOUBLE field arrives as `float`, as the dataset declared it. The intent below is
            # stated in Decimal, so cross once here and through `str`: `Decimal(0.1)` inherits
            # the binary float's expansion, `Decimal("0.1")` is one tenth.
            history[name] = [Decimal(str(v)) for v in window.values[name] if v is not None]

        # ---- the one line to change -------------------------------------------------------
        # Trailing return over the declared lookback.
        derived = {
            name: values[-1] / values[0] - Decimal(1)
            for name, values in history.items()
            if len(values) == LOOKBACK
        }
        # -----------------------------------------------------------------------------------

        # One dict per instrument. The fields are the ones the materialization spec declares;
        # `available_at` is the package's to stamp and a row that carries one is refused.
        # The value crosses back to `float`: a dataset field is DOUBLE, never DECIMAL (record
        # 173), and the first session's row types the output for every later one.
        return [
            {"instrument": name, "value": float(value)} for name, value in sorted(derived.items())
        ]
