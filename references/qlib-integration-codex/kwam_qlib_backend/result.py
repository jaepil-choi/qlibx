from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd


def empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})


@dataclass
class BackendRunResult:
    """Backend-neutral observable view over one real Qlib account run."""

    decision_weights: pd.DataFrame
    order_rows: pd.DataFrame
    fill_rows: pd.DataFrame
    position_rows: pd.DataFrame
    account_rows: pd.DataFrame
    signal_rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    observation_rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    research_rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    feedback_rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    state_rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    selected_rules: pd.Series = field(default_factory=lambda: pd.Series(dtype="object"))
    extra_tables: Mapping[str, pd.DataFrame] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)

    def decision_weight(self, date: pd.Timestamp, instrument: str) -> float:
        if instrument not in self.decision_weights.columns:
            return 0.0
        return float(self.decision_weights.loc[pd.Timestamp(date), instrument])

    def selected_rule(self, date: pd.Timestamp) -> str | None:
        value = self.selected_rules.get(pd.Timestamp(date))
        return None if value is None or pd.isna(value) else str(value)

    def position_quantity(self, date: pd.Timestamp, instrument: str) -> int:
        rows = self.position_rows
        if rows.empty:
            return 0
        match = rows.loc[
            rows["trade_date"].eq(pd.Timestamp(date))
            & rows["instrument_id"].eq(instrument),
            "held_quantity",
        ]
        return 0 if match.empty else int(match.iloc[-1])

    def cash(self, date: pd.Timestamp) -> float:
        return float(self.account_rows.loc[pd.Timestamp(date), "cash"])

    def nav(self, date: pd.Timestamp) -> float:
        return float(self.account_rows.loc[pd.Timestamp(date), "nav"])

    def portfolio_return(self, date: pd.Timestamp) -> float:
        return float(self.account_rows.loc[pd.Timestamp(date), "portfolio_return"])

    def orders(self, date: pd.Timestamp | None = None) -> pd.DataFrame:
        if date is None or self.order_rows.empty:
            return self.order_rows.copy()
        return self.order_rows.loc[
            self.order_rows["trade_date"].eq(pd.Timestamp(date))
        ].copy()

    def fills(self, date: pd.Timestamp | None = None) -> pd.DataFrame:
        if date is None or self.fill_rows.empty:
            return self.fill_rows.copy()
        return self.fill_rows.loc[
            self.fill_rows["trade_date"].eq(pd.Timestamp(date))
        ].copy()

    def positions(self) -> pd.DataFrame:
        return self.position_rows.copy()

    def account_daily(self) -> pd.DataFrame:
        return self.account_rows.copy()

    def signals(self) -> pd.DataFrame:
        return self.signal_rows.copy()

    def observation_audit(self) -> pd.DataFrame:
        return self.observation_rows.copy()

    def research_evaluations(self) -> pd.DataFrame:
        return self.research_rows.copy()

    def feedback_audit(self) -> pd.DataFrame:
        return self.feedback_rows.copy()

    def state_audit(self) -> pd.DataFrame:
        return self.state_rows.copy()

    def backend_evidence(self) -> Mapping[str, Any]:
        evidence = dict(self.evidence)
        evidence.setdefault("result_hash", self.result_hash())
        return evidence

    def result_hash(self) -> str:
        digest = hashlib.sha256()
        for name, frame in (
            ("portfolio_targets", self.decision_weights),
            ("signals", self.signal_rows),
            ("orders", self.order_rows),
            ("fills", self.fill_rows),
            ("positions", self.position_rows),
            ("account_daily", self.account_rows),
            ("observations", self.observation_rows),
            ("research", self.research_rows),
            ("feedback", self.feedback_rows),
            ("state", self.state_rows),
            ("selected_rules", self.selected_rules.to_frame("selected_rule")),
            *tuple(sorted(self.extra_tables.items())),
        ):
            _update_frame_hash(digest, name, frame)
        return digest.hexdigest()


def _update_frame_hash(
    digest: Any, name: str, frame: pd.DataFrame
) -> None:
    normalized = frame.copy()
    normalized = normalized.reindex(
        sorted(normalized.columns, key=lambda value: str(value)), axis=1
    )
    metadata = {
        "name": name,
        "index_names": [_json_value(value) for value in normalized.index.names],
        "index": [_json_value(value) for value in normalized.index.tolist()],
        "columns": [_json_value(value) for value in normalized.columns.tolist()],
        "dtypes": [str(dtype) for dtype in normalized.dtypes],
    }
    digest.update(
        json.dumps(
            metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    for column in normalized.columns:
        if normalized[column].dtype == "object":
            normalized[column] = normalized[column].map(
                lambda value: json.dumps(
                    _json_value(value),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
    values = pd.util.hash_pandas_object(
        normalized.reset_index(drop=True), index=False
    )
    digest.update(values.values.tobytes())


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return {"type": "null"}
    if isinstance(value, pd.Timestamp):
        return {"type": "timestamp", "value": value.isoformat()}
    if isinstance(value, pd.Timedelta):
        return {"type": "timedelta", "value": value.isoformat()}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if isinstance(value, int):
        return {"type": "int", "value": str(value)}
    if isinstance(value, float):
        if math.isnan(value):
            return {"type": "float", "value": "nan"}
        if math.isinf(value):
            return {"type": "float", "value": "inf" if value > 0 else "-inf"}
        return {"type": "float", "value": value.hex()}
    if isinstance(value, str):
        return {"type": "str", "value": value}
    if isinstance(value, Mapping):
        items = [(_json_value(key), _json_value(item)) for key, item in value.items()]
        items.sort(key=lambda item: json.dumps(item[0], sort_keys=True))
        return {"type": "mapping", "value": items}
    if isinstance(value, (list, tuple)):
        return {
            "type": type(value).__name__,
            "value": [_json_value(item) for item in value],
        }
    scalar = getattr(value, "item", None)
    if callable(scalar):
        try:
            return _json_value(scalar())
        except (TypeError, ValueError):
            pass
    return {
        "type": f"{type(value).__module__}.{type(value).__qualname__}",
        "value": repr(value),
    }


ORDER_COLUMNS = [
    "trade_date",
    "order_id",
    "instrument_id",
    "direction",
    "requested_quantity",
    "raw_target_quantity",
    "target_quantity",
    "lot_size",
    "lot_rounding_quantity",
]
FILL_COLUMNS = [
    "trade_date",
    "fill_id",
    "order_id",
    "instrument_id",
    "filled_quantity",
    "trade_price",
    "trade_value",
    "trade_cost",
    "reason",
    "reason_code",
    "blocked_by",
    "quantity_after_tradability",
    "quantity_after_volume",
    "quantity_after_position",
    "quantity_after_cash",
    "quantity_after_lot",
    "asset_class",
    "execution_policy",
    "effective_cost_rate",
    "short_enabled",
]
POSITION_COLUMNS = [
    "trade_date",
    "instrument_id",
    "held_quantity",
    "market_value",
    "asset_class",
]
ACCOUNT_COLUMNS = ["cash", "nav", "portfolio_return", "trade_cost", "turnover"]
