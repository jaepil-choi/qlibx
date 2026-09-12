# 254 — The run envelope and the published allocation stream the record, a batch at a time

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로). 메모리 보고의 넷 중 첫째 |
| **이슈** | `docs/issues/report-2026-09-11-a-strategy-runs-memory-grows-with-its-orders-far-past-the-documented-per-worker-size.md` |
| **설계 근거** | 기록 `087`/`164`(행은 Arrow로 들고 끝에 한 번 쓴다), `210`(stored run의 allocation은 record에서 읽어 publish), `record/reader.py::read_table`(배치 generator) |
| **브랜치** | `develop` |
| **앞선 기록** | `114`, `210` |

---

## 왜 이 변경이 있는가

309종목을 매 세션 거래하는 일봉 전략 run의 private 메모리가 fill 수에 선형으로 자라 460k fill에서 ≥ 3.7 GB였다
(문서의 크기 규칙은 ~0.2 GB). 이 세션의 측정(`scratchpad/mem`, 합성 300종목 × 1,030세션, `vqapr run`과 같은 경로)에서
**peak는 루프가 아니라 run이 끝난 뒤**였다: `cli/run.py::_strategy_envelope`가
`fill_summary(tuple(read_typed_table(... vqapr.fill ...)))`로 **모든 fill 행을 Python dict로 한꺼번에** 올렸고
(300k fill에서 +0.50 GB, fill당 ~1.7 KB), `_publish_allocation`도 `vqapr.weight` 전체를 dict 리스트로 만든 뒤에야
타입을 매겼다(+0.14–0.23 GB). 둘 다 run이 아직 쥐고 있는 증거 위에 얹혔다.

## 무엇이 어떻게 바뀌었는가

- `analysis/execution.py::fill_summary`가 아무 iterable이나 한 번 걷는다(`orders`는 셈). CLI는 reader의 generator를
  그대로 넘긴다 — reader는 원래 parquet를 배치로 흘린다.
- `flow/orchestration.py::_publish_allocation`이 `itertools.batched`로 5만 행씩 `RunOutput.append`에 넘긴다.
  `RunOutput`은 받은 것을 Arrow로 든다. 빈 표면 이전처럼 아무것도 publish하지 않는다.

## 바꾸지 않은 것

envelope의 `fills` 블록 내용과 publish된 dataset의 행·타입. `fill_summary(rows)`를 부르는 `report/measure.py`.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/cli/test_commands.py tests/report tests/cli/test_the_run_reports_what_its_orders_did.py tests/flow` | 208 passed |
| 메모리, `trade-500`(300종목 × 500세션, 150k fill, 한 프로세스, `vqapr run`의 in-process 경로) | peak private 1.503·1.518 GB → **1.428 GB**; peak 단계는 여전히 envelope이지만 fill dict 전체는 없다 |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
