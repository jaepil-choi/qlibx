# 264 — `vqapr.fill`과 `vqapr.weight`가 숫자를 숫자로 기록한다

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 한 읽기 (`redesign/one-reading`), M1 — 계획 `.agent/plans/active/one-reading-campaign.md` |
| **이슈** | `docs/issues/report-2026-09-11-feature-request-an-export-command-that-writes-a-strategy-record-as-csv.md` (그 요청이 부딪힌 결함) |
| **설계 근거** | 오너 판정 2026-09-11 — 쓰는 곳에서 고치고, 옛 record도 열 이름으로 되돌린다(대안: 새 record만) |
| **브랜치** | `redesign/one-reading` |
| **앞선 기록** | `146`(표가 parquet, `Decimal`은 `vqapr.type: decimal` 태그가 붙은 텍스트), `135` |

---

## 왜 이 변경이 있는가

incremental testbed의 B 에이전트 셋이 모두 자기 exporter를 짰고, 셋 다 record를 읽는 자리에서 넘어졌다. B-2는
`reading-a-record.md`의 "`nav`는 `Decimal`로 온다"를 모든 숫자로 일반화했다가 `Decimal += str`, B-3은 `str < int`.
문서(`panels-from-tables.md`)는 "어떤 숫자는 텍스트로 온다"고 적어 두었지만, 그것은 문서가 쓰는 쪽의 결함을 대신
설명하고 있던 것이다.

원인은 두 writer였다. `record/schema.py::_arrow_type`은 값이 `Decimal`일 때만 열에 decimal 태그를 붙이는데:

- `flow/run/callback.py::_record_defaults`가 `"weight": str(weight)`로 썼다.
- `flow/engine/run_state.py::_fill_rows`가 ledger `detail`의 텍스트(`domain/ledger.py::_fill_entry`가 다섯 숫자를 모두
  `str`로 둔다)를 그대로 옮기고 `cash_delta`도 `str(entry.cash)`로 썼다.

그래서 이 열들은 태그 없는 문자열로 기록되었고, 어느 reader도 숫자로 되돌릴 수 없었다. 같은 표 옆의
`vqapr.account`는 `Decimal`을 그대로 넘겨서 `nav`만 숫자로 돌아왔다.

## 무엇이 어떻게 바뀌었는가

- `run_state._fill_rows`: `requested_quantity` · `sized_quantity`(record `261`이 더한 열) · `dealt_quantity` ·
  `price` · `commission` · `tax`는
  `_number(detail[...])`(= `Decimal(str(v))`, `None`은 `None`), `cash_delta`는 `entry.cash`(이미 `Decimal`).
- `callback._record_defaults`: `"weight": weight`(`PortfolioTarget.weight`는 `Decimal`).
- `record/reader.py::RECORDED_AS_TEXT`: 264 이전 record가 태그 없는 텍스트로 가진 패키지 열 — `vqapr.fill`의 일곱
  (`sized_quantity` 포함: 261과 264 사이의 개발 중 record가 그것을 텍스트로 가진다), `vqapr.weight.weight`. `read_table`이 표 id로 골라 `schema._python_rows(batch, recorded_as_text)`에 넘기고, 그 열이
  태그 없는 `string`일 때만 `Decimal`로 되돌린다. 저자가 만든 표의 같은 이름 열은 저자의 텍스트이므로 그대로다.
- skill: analyze-result `panels-from-tables.md`("모든 숫자가 `Decimal`로 온다, `.astype(float)`은 그리는 자리에서만"),
  `reading-a-record.md`("모든 숫자", 그리고 generator라서 `list(...)`로 센다 — B-2가 `len()`에서 넘어졌다).

## 바꾸지 않은 것

- ledger의 `detail`은 텍스트 그대로다. 표의 행을 만드는 한 자리에서 숫자로 바꾼다 — `Decimal(str(d))`는 정확하고,
  ledger는 다른 세션이 `sized_quantity`(record `261`)로 고치는 중이다.
- parquet의 바이트는 태그 말고 같다: `Decimal`은 원래 쓰던 것과 같은 텍스트(`str(Decimal)`)로 기록된다. 그래서
  `vqapr show strategy --table`의 JSON(`Decimal`을 텍스트로 인코딩)도, duckdb로 읽는 쪽의 `CAST`도 그대로다.
- run identity, 체결, 계좌.

## 트레이드오프

reader가 열 이름 목록 하나를 들고 있게 되었다. 대안(새 record만 고친다)은 더 단순하지만 옛 record는 계속 텍스트를
돌려주고, 한 store 안에서 두 record가 다른 타입을 돌려준다. 오너가 목록 쪽을 골랐다. 목록은 패키지 표의 이름으로만
열리므로 저자의 표에는 닿지 않는다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/record/test_the_record_reads_back_typed.py::test_a_record_written_before_264_reads_its_text_numbers_back_as_decimal` (신규) | 태그 없는 텍스트의 `vqapr.fill`·`vqapr.weight`가 `Decimal`로; 저자 표 `notes`의 같은 이름 열은 텍스트로 |
| `tests/report/test_a_real_run_reports_and_adds_up.py` (slow, 확장) | 샘플 journey의 새 record: fill 다섯 열·`weight`가 `Decimal`, parquet의 `commission`·`weight`에 `vqapr.type: decimal` |
| `tests/report/test_the_report_reads_the_record_back.py` | 텍스트 fill 행 fixture(= 옛 record 모양)로 report가 그대로 맞는다 |
| fill/weight 표를 읽는 16개 파일 (`-m ""`) | 117 통과 |
| `uv run python -m pytest tests/ -q` | 1739 통과, 6 skip, 29 deselected (180.9 s) |
| `uv run ruff check` (바뀐 파일) | 통과 |
