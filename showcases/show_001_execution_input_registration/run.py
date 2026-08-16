from __future__ import annotations

import hashlib
import html
import json
import shutil
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import duckdb

from vqapr.public import (
    ComponentKind,
    ComponentRef,
    DataRequirement,
    DatasetRegistration,
    ExecutionInputRegistration,
    ExecutionTableSpec,
    FillConvention,
    FillSelector,
    LocalInstantDeclaration,
    MonitoringPolicy,
    OperationAgenda,
    OperationOccurrence,
    OperationRole,
    RowsLookback,
    SourceSpec,
    StrategyConfig,
    ValuationConfig,
    VqaprError,
    register_agenda,
    register_component,
    register_dataset,
    register_execution_input,
    register_monitoring_policy,
    register_strategy_config,
    register_valuation_config,
)

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
PROJECT = OUTPUTS / "project"
VERIFIED_AGAINST = "vqapr-0.1.0+implementation-008-working-tree"
LAST_VERIFIED_AT = "2026-08-16"


def _reset_outputs() -> None:
    if OUTPUTS.exists():
        shutil.rmtree(OUTPUTS)
    OUTPUTS.mkdir(parents=True)


def _write_parquets() -> tuple[Path, Path, Path]:
    observation = OUTPUTS / "observation_price_daily.parquet"
    execution = OUTPUTS / "execution_krx_daily.parquet"
    invalid = OUTPUTS / "invalid_execution_price.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (
                SELECT * FROM (VALUES
                  (DATE '2024-03-05', TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A',  99.0, 100.0),
                  (DATE '2024-03-05', TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B',  48.0,  50.0),
                  (DATE '2024-03-06', TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', 101.0, 103.0),
                  (DATE '2024-03-06', TIMESTAMPTZ '2024-03-06 15:30:00+09', 'B',  51.0,  51.0),
                  (DATE '2024-03-07', TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', 104.0, 105.0),
                  (DATE '2024-03-07', TIMESTAMPTZ '2024-03-07 15:30:00+09', 'B',  52.0,  53.0)
                ) AS t(session_date, available_at, instrument, open, close)
            ) TO '{observation.as_posix()}' (FORMAT PARQUET)"""
        )
        con.execute(
            f"""COPY (
                SELECT * FROM (VALUES
                  (TIMESTAMPTZ '2024-03-05 10:00:00+09', 'A', true,  98.0,  99.0),
                  (TIMESTAMPTZ '2024-03-05 10:00:00+09', 'B', true,  47.0,  48.0),
                  (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', true,  99.0, 100.0),
                  (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B', true,  48.0,  50.0),
                  (TIMESTAMPTZ '2024-03-06 10:00:00+09', 'A', true, 100.0, 101.0),
                  (TIMESTAMPTZ '2024-03-06 10:00:00+09', 'B', true,  50.0,  50.0),
                  (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', true, 101.0, 103.0),
                  (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'B', false, 51.0,  51.0),
                  (TIMESTAMPTZ '2024-03-07 10:00:00+09', 'A', true, 103.0, 104.0),
                  (TIMESTAMPTZ '2024-03-07 10:00:00+09', 'B', true,  51.0,  52.0),
                  (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', true, 104.0, 105.0),
                  (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'B', true,  52.0,  53.0)
                ) AS t(trade_at, instrument, is_tradable, open, close)
            ) TO '{execution.as_posix()}' (FORMAT PARQUET)"""
        )
        con.execute(
            f"""COPY (
                SELECT TIMESTAMPTZ '2024-03-05 15:30:00+09' AS trade_at,
                       'A' AS instrument, true AS is_tradable,
                       99.0 AS open, CAST('NaN' AS DOUBLE) AS close
            ) TO '{invalid.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return observation, execution, invalid


def _execution_registration(
    raw_id: str,
    source: SourceSpec,
    *,
    trade_price: str,
) -> ExecutionInputRegistration:
    return ExecutionInputRegistration.of(
        raw_id,
        ExecutionTableSpec(
            source=source,
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"open": "open", "close": "close"},
        ),
        FillConvention(
            selector=FillSelector.NEXT_ELIGIBLE,
            local_time=time(15, 30),
            timezone="Asia/Seoul",
            trade_price=trade_price,
        ),
    )


def _rows(path: Path, *, selected: str | None = None) -> list[dict[str, object]]:
    con = duckdb.connect()
    try:
        if selected is None:
            cursor = con.execute(f"SELECT * FROM read_parquet('{path.as_posix()}') ORDER BY ALL")
        else:
            field = '"' + selected.replace('"', '""') + '"'
            cursor = con.execute(
                f"SELECT trade_at, instrument, is_tradable, {field} AS selected_price "
                f"FROM read_parquet('{path.as_posix()}') ORDER BY trade_at, instrument"
            )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    finally:
        con.close()


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[union-attr]
    return value


def _normalized(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{key: _json_value(value) for key, value in row.items()} for row in rows]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _agenda(agenda_id: str, role: OperationRole, local_time: time) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=agenda_id,
        role=role,
        timezone="Asia/Seoul",
        occurrences=tuple(
            OperationOccurrence(
                f"{agenda_id}-{day}",
                role,
                LocalInstantDeclaration(date(2024, 3, day), local_time, "Asia/Seoul", 0, "+09:00"),
            )
            for day in (5, 6, 7)
        ),
        provenance="show_001 explicit finite agenda",
    )


def _strategy_config() -> StrategyConfig:
    return StrategyConfig(
        ComponentRef.of(
            "showcase-strategy",
            ComponentKind.STRATEGY_MODEL,
            "strategy.py",
            "ShowcaseStrategy",
            fingerprint="0" * 64,
        ),
        "showcase-strategy",
        OperationRole.STRATEGY_CALLBACK,
    )


def _table(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "<p>No rows.</p>"
    columns = list(rows[0])
    head = "".join(f"<th>{html.escape(str(column))}</th>" for column in columns)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{html.escape(str(row[column]))}</td>" for column in columns)
        + "</tr>"
        for row in rows
    )
    return (
        "<div class='table-wrap'><table><thead><tr>"
        f"{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _report(trace: dict[str, object], workspace_text: str) -> str:
    observation_rows = trace["observation_rows"]
    execution_rows = trace["execution_rows"]
    close_rows = trace["close_binding_rows"]
    open_rows = trace["open_binding_rows"]
    agendas = trace["agendas"]
    invalid = trace["invalid_registration"]
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VQAPR execution input registration</title>
<style>
body {{
  font-family: system-ui, sans-serif; max-width: 1180px; margin: 0 auto;
  padding: 32px; color: #172033; background: #f5f7fb;
}}
h1, h2 {{ color: #102a43; }}
.card {{
  background: white; border: 1px solid #d8e1eb; border-radius: 12px;
  padding: 20px; margin: 18px 0;
}}
.ok {{ color: #087f5b; font-weight: 700; }}
.bad {{ color: #c92a2a; font-weight: 700; }}
code, pre {{ font-family: ui-monospace, monospace; }}
pre {{
  white-space: pre-wrap; background: #102a43; color: #e6edf3;
  padding: 16px; border-radius: 8px; overflow: auto;
}}
.table-wrap {{ overflow: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
th, td {{
  padding: 8px; border-bottom: 1px solid #e5e9f0;
  text-align: left; white-space: nowrap;
}}
th {{ background: #edf2f7; }}
.grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}}
</style>
</head>
<body>
<p><strong>VQAPR / show_001</strong></p>
<h1>Execution input registration evidence</h1>
<p>
실제 parquet을 observation과 execution으로 따로 만들고,
서로 다른 등록 계약으로 workspace에 보존한 증거다.
</p>
<div class="grid">
<div class="card"><b>Observation registration</b><p class="ok">PASS</p></div>
<div class="card"><b>Execution registrations</b><p class="ok">close + open PASS</p></div>
<div class="card">
<b>Invalid selected price</b><p class="bad">REJECTED WITHOUT MUTATION</p>
</div>
</div>
<section class="card">
<h2>1. Observation parquet</h2>{_table(observation_rows)}
</section>
<section class="card">
<h2>2. Separate execution parquet</h2>{_table(execution_rows)}
</section>
<section class="card">
<h2>3. Explicit operation agendas</h2>
<p>
Strategy, valuation, and monitoring occurrences are finite declarations. The
10:00 rows remain non-selected execution input density; they do not create callbacks.
</p>
<pre>{html.escape(json.dumps(agendas, indent=2, ensure_ascii=False))}</pre>
</section>
<section class="card">
<h2>4. Selected close binding</h2>{_table(close_rows)}
</section>
<section class="card">
<h2>5. Selected open binding</h2>
<p>
같은 15:30 execution instant에서 다른 물리 가격 field를 선택한 예이며
next-open 의미를 주장하지 않는다.
</p>
{_table(open_rows)}
</section>
<section class="card">
<h2>6. Persisted workspace</h2><pre>{html.escape(workspace_text)}</pre>
</section>
<section class="card">
<h2>7. Invalid close price</h2>
<pre>{html.escape(json.dumps(invalid, indent=2, ensure_ascii=False))}</pre>
</section>
<section class="card">
<h2>Boundary</h2>
<p>
<b>Not implemented here:</b> OrderBatch, FillBatch, Account.commit,
valuation, portfolio return.
</p>
</section>
<footer>Last verified at {LAST_VERIFIED_AT}. Verified against {VERIFIED_AGAINST}.</footer>
</body></html>"""


def main() -> None:
    _reset_outputs()
    observation_path, execution_path, invalid_path = _write_parquets()

    observation_source = SourceSpec.of("price-observation", observation_path)
    observation_registration = DatasetRegistration.of(
        "price_daily",
        "price-observation",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"open": "open", "close": "close", "session_date": "session_date"},
    )
    observation_created = register_dataset(PROJECT, observation_registration, observation_source)

    execution_source = SourceSpec.of("krx-execution", execution_path)
    close_registration = _execution_registration(
        "krx-daily-close", execution_source, trade_price="close"
    )
    open_registration = _execution_registration(
        "krx-daily-open-field", execution_source, trade_price="open"
    )
    close_created = register_execution_input(PROJECT, close_registration)
    open_created = register_execution_input(PROJECT, open_registration)
    close_retry = register_execution_input(PROJECT, close_registration)
    strategy_agenda = _agenda("showcase-strategy", OperationRole.STRATEGY_CALLBACK, time(4, 0))
    valuation_agenda = _agenda("showcase-valuation", OperationRole.VALUATION, time(16, 0))
    monitoring_agenda = _agenda("showcase-monitoring", OperationRole.MONITORING, time(17, 0))
    strategy_config = _strategy_config()
    valuation_config = ValuationConfig(
        "showcase-valuation",
        OperationRole.VALUATION,
        DataRequirement.of(
            "showcase-valuation",
            "price_daily",
            fields=("close",),
            lookback=RowsLookback(1),
        ),
    )
    monitoring_policy = MonitoringPolicy("showcase-monitoring", OperationRole.MONITORING)
    agenda_created = {
        agenda.agenda_id: register_agenda(PROJECT, agenda)
        for agenda in (strategy_agenda, valuation_agenda, monitoring_agenda)
    }
    register_component(PROJECT, strategy_config.component)
    strategy_config_created = register_strategy_config(PROJECT, strategy_config)
    valuation_config_created = register_valuation_config(PROJECT, valuation_config)
    monitoring_policy_created = register_monitoring_policy(PROJECT, monitoring_policy)

    workspace_path = PROJECT / ".vqapr" / "workspace.yaml"
    workspace_before_invalid = workspace_path.read_bytes()
    bad_registration = _execution_registration(
        "invalid-close",
        SourceSpec.of("invalid-execution", invalid_path),
        trade_price="close",
    )
    try:
        register_execution_input(PROJECT, bad_registration)
    except VqaprError as error:
        invalid_error = error.as_dict()
        invalid_error.pop("correlation_id", None)
    else:
        raise AssertionError("invalid selected close price unexpectedly registered")
    workspace_unchanged = workspace_path.read_bytes() == workspace_before_invalid
    if not workspace_unchanged:
        raise AssertionError("failed execution registration mutated the workspace")

    agendas = {
        agenda.agenda_id: [
            {
                "occurrence_id": occurrence.occurrence_id,
                "role": occurrence.role.value,
                "evaluation_time": occurrence.evaluation_time.isoformat(),
            }
            for occurrence in agenda.occurrences
        ]
        for agenda in (strategy_agenda, valuation_agenda, monitoring_agenda)
    }
    workspace_text = workspace_path.read_text(encoding="utf-8")
    shutil.copyfile(workspace_path, OUTPUTS / "workspace.yaml")

    trace: dict[str, object] = {
        "status": "current",
        "last_verified_at": LAST_VERIFIED_AT,
        "verified_against": VERIFIED_AGAINST,
        "registrations": {
            "observation_created": observation_created,
            "close_execution_created": close_created,
            "open_execution_created": open_created,
            "identical_close_retry_created": close_retry,
            "agendas_created": agenda_created,
            "strategy_config_created": strategy_config_created,
            "valuation_config_created": valuation_config_created,
            "monitoring_policy_created": monitoring_policy_created,
        },
        "source_sha256": {
            observation_path.name: _sha256(observation_path),
            execution_path.name: _sha256(execution_path),
            invalid_path.name: _sha256(invalid_path),
        },
        "observation_rows": _normalized(_rows(observation_path)),
        "execution_rows": _normalized(_rows(execution_path)),
        "close_binding_rows": _normalized(_rows(execution_path, selected="close")),
        "open_binding_rows": _normalized(_rows(execution_path, selected="open")),
        "agendas": agendas,
        "invalid_registration": {
            "workspace_unchanged": workspace_unchanged,
            "error": invalid_error,
        },
        "limitations": [
            "No order planning or fill generation is implemented by this showcase.",
            "No Account mutation, valuation, or portfolio return is claimed.",
        ],
    }
    (OUTPUTS / "trace.json").write_text(
        json.dumps(trace, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUTPUTS / "report.html").write_text(_report(trace, workspace_text), encoding="utf-8")
    print(OUTPUTS / "report.html")


if __name__ == "__main__":
    main()
