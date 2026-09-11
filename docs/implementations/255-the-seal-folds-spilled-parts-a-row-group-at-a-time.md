# 255 — The seal folds spilled parts into `all.parquet` a row group at a time

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로). 메모리 보고의 넷 중 둘째 |
| **이슈** | `docs/issues/report-2026-09-11-a-strategy-runs-memory-grows-with-its-orders-far-past-the-documented-per-worker-size.md` |
| **설계 근거** | 기록 `087`/`164`(행은 Arrow 버퍼, 256 MB spill 밸브, 끝에 표당 `all.parquet` 하나) |
| **브랜치** | `develop` |
| **앞선 기록** | `164`, `254` |

---

## 왜 이 변경이 있는가

`watching-and-failures.md`는 "버퍼가 256 MB를 넘으면 part를 쓴다"고 말하고, 보고자는 그것이 run의 메모리를 묶는다고
읽었다. 그렇지 않았다: `RunRecordWriter._seal`이 spill된 part를 **전부 통째로 다시 읽어**(`pq.read_table`) 버퍼와 함께
concat한 뒤 한 번에 썼다. 그래서 spill은 run 중간의 메모리는 덜어도 끝의 peak는 오히려 올렸다 — 이 세션의 측정에서
16 MB마다 spill한 run(peak 1.681 GB)이 spill하지 않은 run(1.51 GB)보다 높았다.

## 무엇이 어떻게 바뀌었는가

`_seal`이 `_write_compact`를 부른다: part들의 스키마를 `pq.read_schema`로 먼저 통일하고, `ParquetWriter` 하나에 각
part를 **row group 하나씩** 읽어 쓰고, 마지막에 버퍼(여전히 256 MB 이하)를 쓴다. part가 없으면 이전과 같은
`_write_parquet`. 원자적 교체(`.tmp` → `os.replace`)와 "compact 파일이 선 뒤에야 part를 지운다"는 순서는 그대로.

## 바꾸지 않은 것

`SPILL_BYTES`(256 MB, 기록 `164`의 결정), part 파일 이름, 읽는 쪽(`all.parquet`이 있으면 그것만 읽는다),
hard kill 뒤에는 spill된 것만 남는다는 약속.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/record/test_the_record_reads_back_typed.py::test_the_end_folds_the_parts_without_reading_any_of_them_whole` (신규) | part 둘 + 버퍼 하나, 열의 타입은 버퍼의 chunk만 앎; writer 모듈의 `pq.read_table`을 raise하게 막아도 `release`가 `all.parquet` 하나를 쓰고 행·타입이 그대로 |
| `tests/record` | 43 passed (hard-kill · 인터럽트 · compact 옆 잔여 part 테스트 포함) |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |

측정 주석: 300종목 × 1,000세션(300k fill)의 버퍼는 ~156 MB로 256 MB에 닿지 않아 이 run들에선 spill 자체가 없다.
이 기록은 spill이 일어나는 run에서 밸브가 약속대로 동작하게 하는 것이다.
