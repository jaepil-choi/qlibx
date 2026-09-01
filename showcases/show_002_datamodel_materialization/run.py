from __future__ import annotations

import hashlib
import html
import json
import shutil
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from vqapr.domain.errors import VqaprError
from vqapr.public import (
    DatasetRegistration,
    MaterializationSpec,
    SourceSpec,
    materialize,
    register_data_model,
    register_dataset,
)

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "show002_models.py"
OUTPUTS = ROOT / "outputs"
PROJECT = OUTPUTS / "project"
LAST_VERIFIED_AT = "2026-09-01"
VERIFIED_AGAINST = "vqapr-0.2.0a2+develop"
KST = ZoneInfo("Asia/Seoul")


def _reset_outputs() -> None:
    if OUTPUTS.exists():
        shutil.rmtree(OUTPUTS)
    OUTPUTS.mkdir(parents=True)


def _write_input() -> Path:
    target = OUTPUTS / "price_daily.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (
                SELECT * FROM (VALUES
                  (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'A', 100.0),
                  (TIMESTAMPTZ '2024-03-05 15:30:00+09', 'B',  50.0),
                  (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'A', 103.0),
                  (TIMESTAMPTZ '2024-03-06 15:30:00+09', 'B',  51.0),
                  (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'A', 105.0),
                  (TIMESTAMPTZ '2024-03-07 15:30:00+09', 'B',  53.0),
                  (TIMESTAMPTZ '2024-03-08 15:30:00+09', 'A', 999.0),
                  (TIMESTAMPTZ '2024-03-08 15:30:00+09', 'B', 999.0)
                ) AS t(available_at, instrument, close)
            ) TO '{target.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    return target


def _rows(path: Path) -> list[dict[str, object]]:
    con = duckdb.connect()
    try:
        cursor = con.execute(
            f"SELECT * FROM read_parquet('{path.as_posix()}') ORDER BY available_at, instrument"
        )
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
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


INSTRUMENTS = ("A", "B")








def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    lineage = trace["reversal_materialization"]["lineage"]  # type: ignore[index]
    rejection = trace["forgery_rejection"]
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VQAPR DataModel materialization</title>
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
.flow {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }}
.node {{ background: #e7f5ff; border: 1px solid #74c0fc; padding: 12px; border-radius: 8px; }}
.arrow {{ font-size: 24px; color: #4263eb; }}
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
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px;
}}
</style>
</head>
<body>
<p><strong>VQAPR / show_002</strong></p>
<h1>DataModel materialization evidence</h1>
<p>실제 등록 parquet을 PIT 창으로 읽고, 계산값을 다시 등록 가능한 parquet으로 만든 증거다.</p>
<section class="card">
<h2>실행 흐름</h2>
<div class="flow">
<span class="node">price_daily<br>registered parquet</span><span class="arrow">→</span>
<span class="node">RowsLookback(2)<br>ReversalFeatureModel</span><span class="arrow">→</span>
<span class="node">reversal_features<br>derived parquet</span><span class="arrow">→</span>
<span class="node">RowsLookback(1)<br>AbsoluteScoreModel</span><span class="arrow">→</span>
<span class="node">absolute_scores<br>derived parquet</span>
</div>
<p><b>Exchange, session calendar, Account는 이 흐름에 들어오지 않는다.</b></p>
</section>
<div class="grid">
<div class="card"><b>PIT future exclusion</b><p class="ok">PASS — 999 excluded</p></div>
<div class="card"><b>Package timestamp ownership</b><p class="ok">PASS</p></div>
<div class="card"><b>Derived dataset reread</b><p class="ok">PASS</p></div>
<div class="card"><b>Forged available_at</b><p class="bad">REJECTED WITHOUT MUTATION</p></div>
</div>
<section class="card">
<h2>1. 등록한 원천 데이터</h2>
<p>3월 8일의 999는 두 evaluation time보다 미래이므로 모델 입력에 들어가면 안 된다.</p>
{_table(trace["input_rows"])}
</section>
<section class="card">
<h2>2. DataModel 결과</h2>
<p>old_close/new_close를 함께 남겨 모델이 실제로 본 두 관측치를 직접 확인할 수 있다.</p>
{_table(trace["reversal_materialization"]["rows"])}
</section>
<section class="card">
<h2>3. Package-owned available_at와 access lineage</h2>
<pre>{html.escape(json.dumps(lineage, indent=2, ensure_ascii=False))}</pre>
</section>
<section class="card">
<h2>4. 파생 결과를 같은 alias 경로로 다시 읽은 결과</h2>
{_table(trace["derived_reread"]["rows"])}
</section>
<section class="card">
<h2>5. Persisted workspace</h2>
<pre>{html.escape(workspace_text)}</pre>
</section>
<section class="card">
<h2>6. Producer timestamp forgery rejection</h2>
<pre>{html.escape(json.dumps(rejection, indent=2, ensure_ascii=False))}</pre>
</section>
<section class="card">
<h2>Artifact SHA-256</h2>
<pre>{html.escape(json.dumps(trace["sha256"], indent=2, ensure_ascii=False))}</pre>
</section>
<section class="card">
<h2>Boundary</h2>
<p><b>Not implemented here:</b> StrategyModel session callback, execution, orders, fills,
Account commit, valuation, and performance.</p>
</section>
<footer>Last verified at {LAST_VERIFIED_AT}. Verified against {VERIFIED_AGAINST}.</footer>
</body></html>"""


def main() -> None:
    _reset_outputs()
    input_path = _write_input()

    input_created = register_dataset(
        PROJECT,
        DatasetRegistration.of(
            "price_daily",
            "show002-prices",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("show002-prices", input_path),
    )

    # The framework serves its own registered and derived datasets: no hand-rolled
    # point-in-time filtering or lookback trimming in showcase code.
    reversal_ref = register_data_model(
        PROJECT, "reversal-features", MODELS, "ReversalFeatureModel"
    )
    absolute_ref = register_data_model(PROJECT, "absolute-scores", MODELS, "AbsoluteScoreModel")
    register_data_model(PROJECT, "forging-model", MODELS, "ForgingModel")

    evaluation_times = (
        datetime(2024, 3, 6, 16, tzinfo=KST),
        datetime(2024, 3, 7, 16, tzinfo=KST),
    )
    reversal = materialize(
        PROJECT,
        "reversal-features",
        MaterializationSpec.of(
            "reversal_features", value_fields=("old_close", "new_close", "score")
        ),
        evaluation_times=evaluation_times,
        instruments=INSTRUMENTS,
    )
    reversal_rows = _normalized(_rows(reversal.output_path))
    reversal_lineage = json.loads(reversal.lineage_path.read_text(encoding="utf-8"))

    absolute = materialize(
        PROJECT,
        "absolute-scores",
        MaterializationSpec.of("absolute_scores", value_fields=("abs_score",)),
        evaluation_times=(evaluation_times[-1],),
        instruments=INSTRUMENTS,
    )
    absolute_rows = _normalized(_rows(absolute.output_path))
    absolute_lineage = json.loads(absolute.lineage_path.read_text(encoding="utf-8"))

    # Snapshotted AFTER every component is registered, so what this compares is the
    # materialization's effect alone. A refused materialization must register no output dataset.
    workspace_path = PROJECT / ".vqapr" / "workspace.yaml"
    before_forgery = workspace_path.read_bytes()
    forged_output = PROJECT / ".vqapr" / "materialized" / "forged_features.parquet"
    try:
        materialize(
            PROJECT,
            "forging-model",
            MaterializationSpec.of(
                "forged_features", value_fields=("old_close", "new_close", "score")
            ),
            evaluation_times=evaluation_times,
            instruments=INSTRUMENTS,
        )
    except VqaprError as error:
        forgery_error = {
            "type": type(error).__name__,
            "codes": [failure.code for failure in error.failures],
            "message": str(error),
        }
        if "available_at" not in str(error):
            raise AssertionError(
                "forgery rejection did not name the reserved field 'available_at'"
            ) from error
    else:
        raise AssertionError("producer-controlled available_at was unexpectedly accepted")
    workspace_unchanged = workspace_path.read_bytes() == before_forgery
    if not workspace_unchanged:
        raise AssertionError("failed materialization exposed partial workspace state")
    forged_output_absent = not forged_output.exists()
    if not forged_output_absent:
        raise AssertionError("failed materialization exposed partial output state")

    old_new_values = {
        float(row[field]) for row in reversal_rows for field in ("old_close", "new_close")
    }
    pit_future_excluded = 999.0 not in old_new_values
    if not pit_future_excluded:
        raise AssertionError("future 999 value leaked into DataModel output")
    # Compared as instants, not as strings: the parquet round trip is free to hand back the same
    # moment in a different offset, and a string comparison would call that a mismatch.
    package_timestamps_match = [
        datetime.fromisoformat(str(row["available_at"])) for row in reversal_rows
    ] == [
        evaluation_times[0],
        evaluation_times[0],
        evaluation_times[1],
        evaluation_times[1],
    ]
    if not package_timestamps_match:
        raise AssertionError("derived available_at values do not match evaluation times")

    shutil.copyfile(workspace_path, OUTPUTS / "workspace.yaml")
    workspace_text = workspace_path.read_text(encoding="utf-8")
    paths = {
        "price_daily.parquet": input_path,
        "workspace.yaml": OUTPUTS / "workspace.yaml",
    }
    trace: dict[str, object] = {
        "status": "current",
        "last_verified_at": LAST_VERIFIED_AT,
        "verified_against": VERIFIED_AGAINST,
        "registration": {
            "input_created": input_created,
            "reversal_authority_id": str(reversal_ref.component_id),
            "reversal_fingerprint": reversal_ref.fingerprint,
            "absolute_authority_id": str(absolute_ref.component_id),
            "absolute_fingerprint": absolute_ref.fingerprint,
        },
        "evaluation_times": [value.isoformat() for value in evaluation_times],
        "input_rows": _normalized(_rows(input_path)),
        "reversal_materialization": {
            "dataset_id": "reversal_features",
            "rows": reversal_rows,
            "lineage": reversal_lineage,
            "pit_future_excluded": pit_future_excluded,
            "package_timestamps_match": package_timestamps_match,
        },
        "derived_reread": {
            "dataset_id": "absolute_scores",
            "rows": absolute_rows,
            "lineage": absolute_lineage,
        },
        "forgery_rejection": {
            "workspace_unchanged": workspace_unchanged,
            "output_absent": forged_output_absent,
            "error": forgery_error,
        },
        "sha256": {name: _sha256(path) for name, path in paths.items()},
        "limitations": [
            "No StrategyModel session callback or execution input participates in materialization.",
            "No orders, fills, Account mutation, valuation, or performance are claimed.",
        ],
    }
    (OUTPUTS / "trace.json").write_text(
        json.dumps(trace, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUTPUTS / "report.html").write_text(
        _report(trace, workspace_text),
        encoding="utf-8",
    )
    print(OUTPUTS / "report.html")


if __name__ == "__main__":
    main()
