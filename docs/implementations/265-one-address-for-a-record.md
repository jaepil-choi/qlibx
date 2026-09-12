# 265 — record를 부르는 주소가 하나다: `str` store와 CLI의 `<run>/<strategy>` 형식

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 한 읽기 (`redesign/one-reading`), M2 — 계획 `.agent/plans/active/one-reading-campaign.md` |
| **이슈** | `docs/issues/report-2026-09-11-feature-request-an-export-command-that-writes-a-strategy-record-as-csv.md` (그 exporter들이 부딪힌 주소 오류 둘) |
| **설계 근거** | 오너 판정 2026-09-11 — "주소 하나"(Python reader가 CLI 형식과 `str`을 받는다) |
| **브랜치** | `redesign/one-reading` |
| **앞선 기록** | `docs/issues/archive/057`(없는 record는 이름으로 거절), `139`(run 아래 strategy member) |

---

## 왜 이 변경이 있는가

한 record를 부르는 방법이 둘이었다. CLI는 `vqapr show strategy <run-id>/<strategy-id>@<fp8>` — 인자 하나 — 이고
store는 경로 문자열이다. Python reader(`read_strategy_table`, `strategy_report`, ...)는 run과 ref를 따로 받고 store는
`Path`만 받았다. incremental testbed에서:

- B-2(sonnet)가 CLI 형식을 그대로 `strategy_report(store, "run/gap-reversal-enhanced@cb36869a")`에 넘겼고
  `RunRecordMissing: no run '…/…@cb36869a'` — 있는 record가 없다고 거절됐다.
- B-1(opus)이 `read_strategy_table(".vqapr", ...)`에 문자열을 넘겼고 reader 안에서
  `TypeError: unsupported operand type(s) for /: 'str' and 'str'`가 났다. 문서는 store가 `Path`여야 한다고 말하지
  않는다.

## 무엇이 어떻게 바뀌었는가

`record/reader.py::record_address(root, run_id, strategy_ref=None) -> (Path, run_id, ref)` 하나가 두 철자를 읽는다.

- `root`는 `str`이든 `Path`든 `Path`로.
- `run_id`에 `/`가 있으면 CLI 형식이다: 앞은 run, 뒤는 ref(`<id>@<fp8>`이나 bare `<id>`). run id는 디렉터리
  이름이라 `/`를 가질 수 없으므로 잘못 읽힐 수 없다.
- 두 곳에서 다른 ref를 주면(`"r/mom"`과 `strategy_ref="rev"`) 하나를 고르지 않고 거절한다. `"r/"`처럼 빈 쪽이
  있으면 형식을 말하며 거절한다. 둘 다 `RunRecordMissing`(= 잘못된 인자, 기존 거절과 같은 종류).

이 함수를 모든 reader 문이 먼저 지난다: `resolve_strategy_ref`, `read_table`(= `read_strategy_table`), `table_ids`,
`strategy_refs`, `read_run_record`(strategy 주소면 그 run을 읽는다), `read_strategy_record`, `strategy_report`,
`run_report`. `read_strategy_record`는 이제 table 읽기와 같은 해석(`resolve_strategy_ref`)을 거쳐 bare id와 "run의
유일한 strategy"도 받는다 — `strategy_ref`가 선택 인자가 됐다. `run_report`는 run의 모든 strategy를 보고하므로
strategy 주소를 받으면 `strategy_report`나 `benchmark=`를 말하며 거절한다.

skill: analyze-result `reading-a-record.md`의 "From Python"에 `str`/`Path` 둘 다와 CLI 형식이 된다는 것.

## 바꾸지 않은 것

기존 호출(`(Path, run_id, ref)`)의 결과는 한 자리도 바뀌지 않는다. 해석 규칙(정확한 ref, bare id는 하나일 때,
`None`은 유일한 strategy일 때)과 그 거절문도 그대로다. CLI의 `resolve_member`는 `InputError` envelope를 내는
자기 문이라 그대로 두었다.

## 트레이드오프

한 인자가 두 모양을 받게 됐다. 대안은 CLI 형식을 거절문으로만 안내하는 것이었는데, 그러면 에이전트가 한 턴을 더
쓴다(B-2는 이 한 번에 4턴, 약 875k context). run id에 `/`가 없다는 사실 위에 서 있으므로 모호함은 없다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/record/test_one_address_reads_a_record.py` (신규, 셋) | `str` store + `r1/mom@deadbeef` · `r1/mom` · 분리 인자가 같은 행; `strategy_refs(..., "r1/mom")`은 그 run; `read_strategy_record` 네 주소가 같은 record; 두 ref는 거절, `"r1/"`은 형식을 말하며 거절 |
| `tests/report/test_the_report_reads_the_record_back.py::test_a_report_takes_the_address_the_cli_writes` (신규) | `strategy_report(str(store), "r/s@…")`·bare id가 분리 인자와 같은 `as_record()`; `run_report`는 `str` store를 받고 strategy 주소는 거절 |
| `tests/record`, `tests/report`, `tests/cli/test_commands.py` 등 (`-m ""`) | 90 통과 |
| `uv run python -m pyright` (reader · report · run_state) | 0 errors |
| `uv run python -m pytest tests/ -q` | 1743 통과, 6 skip, 29 deselected (150.4 s) |
