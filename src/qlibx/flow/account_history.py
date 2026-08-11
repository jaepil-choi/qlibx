"""Flow-owned projection of committed Account outcomes into declared session history."""

from datetime import datetime

from qlibx.account import Account
from qlibx.account_history import (
    AccountHistoryProjection,
    AccountHistoryRecordingSpec,
    AccountHistoryRequirement,
    AccountHistoryShape,
    AccountSeriesHistoryRow,
    InstrumentPanelHistoryRow,
)


class AccountHistoryContractError(ValueError):
    """Raised before Strategy calculation when declared history is not recorded."""

    def __init__(self, code: str, context: dict[str, object]) -> None:
        self.code = code
        self.context = context
        super().__init__(code)


class ActualStateHistoryRecorder:
    """Retain only user-selected committed state at session boundaries."""

    def __init__(self, spec: AccountHistoryRecordingSpec, account: Account) -> None:
        self._spec = spec
        self._account_id = account.snapshot().account_id
        self._feedback_cursor = account.snapshot().feedback_cursor
        self._account_rows: list[AccountSeriesHistoryRow] = []
        self._panel_rows: list[InstrumentPanelHistoryRow] = []

    def validate_requirements(
        self,
        requirements: tuple[AccountHistoryRequirement, ...],
    ) -> None:
        identities = tuple(item.requirement_id for item in requirements)
        if len(identities) != len(set(identities)):
            raise AccountHistoryContractError(
                "ACCOUNT_HISTORY_REQUIREMENT_DUPLICATE",
                {"requirement_ids": identities},
            )
        recorded_series = {item.value for item in self._spec.account_series_fields}
        recorded_panel = {item.value for item in self._spec.instrument_panel_fields}
        for requirement in requirements:
            recorded = (
                recorded_series
                if requirement.shape is AccountHistoryShape.ACCOUNT_SERIES
                else recorded_panel
            )
            missing = tuple(field for field in requirement.fields if field not in recorded)
            if missing:
                raise AccountHistoryContractError(
                    "ACCOUNT_HISTORY_NOT_RECORDED",
                    {
                        "requirement_id": requirement.requirement_id,
                        "shape": requirement.shape.value,
                        "missing_fields": missing,
                        "recorded_fields": tuple(sorted(recorded)),
                    },
                )

    def record(self, session_time: datetime, account: Account) -> None:
        snapshot = account.snapshot(evaluation_time=session_time)
        feedback = account.feedback(
            self._feedback_cursor,
            snapshot.feedback_cursor - self._feedback_cursor,
        )
        realized_delta: dict[str, float] = {}
        for entry in feedback.entries:
            for instrument_id, value in entry.realized_pnl:
                realized_delta[instrument_id] = realized_delta.get(instrument_id, 0.0) + value
        self._feedback_cursor = snapshot.feedback_cursor

        if self._spec.account_series_fields:
            available = {
                "cash": snapshot.cash,
                "nav": snapshot.nav,
                "realized_pnl": sum(realized_delta.values()),
                "gross_exposure": sum(
                    abs(position.quantity * position.mark)
                    for position in snapshot.positions
                    if position.mark is not None
                ),
            }
            self._account_rows.append(
                AccountSeriesHistoryRow(
                    session_time=session_time,
                    values={
                        field.value: float(available[field.value])
                        for field in self._spec.account_series_fields
                    },
                )
            )

        if self._spec.instrument_panel_fields:
            positions = {position.instrument_id: position for position in snapshot.positions}
            instruments = tuple(sorted(set(positions) | set(realized_delta)))
            for instrument_id in instruments:
                position = positions.get(instrument_id)
                available_panel: dict[str, float | None] = {
                    "quantity": 0.0 if position is None else position.quantity,
                    "average_cost": None if position is None else position.average_cost,
                    "realized_pnl": realized_delta.get(instrument_id, 0.0),
                    "mark": None if position is None else position.mark,
                }
                self._panel_rows.append(
                    InstrumentPanelHistoryRow(
                        session_time=session_time,
                        instrument_id=instrument_id,
                        values={
                            field.value: available_panel[field.value]
                            for field in self._spec.instrument_panel_fields
                        },
                    )
                )

    def project(self, requirement: AccountHistoryRequirement) -> AccountHistoryProjection:
        self.validate_requirements((requirement,))
        if requirement.shape is AccountHistoryShape.ACCOUNT_SERIES:
            selected = self._account_rows[-requirement.lookback.rows :]
            rows = tuple(
                row.model_copy(
                    update={"values": {field: row.values[field] for field in requirement.fields}}
                )
                for row in selected
            )
        else:
            sessions = tuple(sorted({row.session_time for row in self._panel_rows}))
            selected_sessions = set(sessions[-requirement.lookback.rows :])
            instrument_filter = set(requirement.instruments)
            rows = tuple(
                row.model_copy(
                    update={"values": {field: row.values[field] for field in requirement.fields}}
                )
                for row in self._panel_rows
                if row.session_time in selected_sessions
                and (not instrument_filter or row.instrument_id in instrument_filter)
            )
        return AccountHistoryProjection(
            requirement_id=requirement.requirement_id,
            account_id=self._account_id,
            shape=requirement.shape,
            selected_fields=requirement.fields,
            requested_rows=requirement.lookback.rows,
            rows=rows,
        )


__all__ = ["AccountHistoryContractError", "ActualStateHistoryRecorder"]