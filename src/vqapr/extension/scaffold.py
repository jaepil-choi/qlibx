"""Templates emitted by `vqapr new`.

A template must **run as written**. A skeleton that raises on the first callback teaches nothing
and cannot be executed to see the shape of a result, so the emitted file is a complete working
Strategy with exactly one marked place to change.

The template deliberately knows nothing about listings, halts, or delistings. Tradability is an
execution-time fact the callback cannot observe (architecture §10, `docs/implementations/
013-halted-names-do-not-stop-a-rebalance.md`); eligibility falls out of whether the declared
lookback is present, and the venue publishes typed zero-dealt evidence for the rest.
"""

from __future__ import annotations

from vqapr.extension.component import ComponentKind

_STRATEGY_TEMPLATE = '''"""A long-only cross-sectional Strategy. Edit the marked signal line."""

from decimal import Decimal

from vqapr import authoring as va

LOOKBACK = {lookback}  # rows per name: a five-day return needs six observations, not five


class {class_name}(va.StrategyModel):
    """Ranks the cross-section and holds the strongest names."""

    def inputs(self):
        read = va.DatasetInput(
            dataset_id="{dataset_id}", fields=("{field}",), lookback=va.RowsLookback(rows=LOOKBACK)
        )
        return {{"prices": read}}

    def decide(self, call):
        history: dict[str, list[Decimal]] = {{}}
        for row in call.read("prices"):
            value = row.values["{field}"]
            if value is not None:
                # `Decimal(str(v))`, never `Decimal(v)`: a float64 0.1 is not one tenth.
                history.setdefault(row.instrument_id, []).append(Decimal(str(value)))

        scores = {{}}
        for instrument, values in history.items():
            if len(values) >= LOOKBACK and values[0] > 0:
                # THE SIGNAL. Momentum: recent gain wins. Flip the sign for reversal.
                scores[instrument] = values[-1] / values[0] - 1

        chosen = {{name: score for name, score in scores.items() if score > 0}}
        if not chosen:
            return va.StrategyResult(decision=va.Hold(reason="no-name-scored-above-zero"))
        # Relative conviction: the package normalises, rounds and balances against cash.
        return va.StrategyResult(decision=va.Rebalance.of(long=chosen, invested="{invested}"))
'''

_DATA_MODEL_TEMPLATE = '''"""A DataModel that derives one column from declared observations."""

from __future__ import annotations

from decimal import Decimal

from vqapr.public import DataModel, DataRequirement, RowsLookback

MODEL_ID = "{component_id}"
DATASET_ID = "{dataset_id}"
LOOKBACK = {lookback}


class {class_name}(DataModel):
    """Emits one derived value per instrument at each materialization time."""

    def requirements(self):
        return (
            DataRequirement.of(
                MODEL_ID,
                DATASET_ID,
                fields=("{field}",),
                lookback=RowsLookback(rows=LOOKBACK),
            ),
        )

    def compute(self, context):
        rows = context.window.observations(self.requirements()[0]).rows
        history: dict[str, list[Decimal]] = {{}}
        for row in rows:
            value = row["{field}"]
            if value is not None:
                # `Decimal(str(v))` rather than `Decimal(v)`: a parquet float64 column arrives as
                # `float`, and money compared or subtracted across `float` and `Decimal` raises.
                # Going through `str` also avoids inheriting the binary float's exact expansion,
                # so 0.1 stays 0.1 instead of becoming 0.1000000000000000055511151231257827.
                history.setdefault(str(row["instrument"]), []).append(Decimal(str(value)))

        # ---- the one line to change -------------------------------------------------------
        # Trailing return over the declared lookback.
        derived = {{
            name: values[-1] / values[0] - Decimal(1)
            for name, values in history.items()
            if len(values) == LOOKBACK
        }}
        # -----------------------------------------------------------------------------------

        return [
            {{"instrument": name, "{output_field}": value}}
            for name, value in sorted(derived.items())
        ]
'''

_TEMPLATES = {
    ComponentKind.STRATEGY_MODEL: _STRATEGY_TEMPLATE,
    ComponentKind.DATA_MODEL: _DATA_MODEL_TEMPLATE,
}


def _class_name(component_id: str) -> str:
    parts = [part for part in component_id.replace("_", "-").split("-") if part]
    if not parts:
        raise ValueError("component_id must contain at least one alphanumeric part")
    return "".join(part[:1].upper() + part[1:] for part in parts)


def render(
    kind: ComponentKind,
    component_id: str,
    *,
    dataset_id: str,
    field: str = "close",
    lookback: int = 6,
    invested: str = "0.9",
    output_field: str = "value",
) -> str:
    """Return a runnable component source for `kind`."""
    if kind not in _TEMPLATES:
        raise ValueError(f"no template for {kind}; user authoring covers datamodel and strategy")
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    return _TEMPLATES[kind].format(
        component_id=component_id,
        class_name=_class_name(component_id),
        dataset_id=dataset_id,
        field=field,
        lookback=lookback,
        invested=invested,
        output_field=output_field,
    )
