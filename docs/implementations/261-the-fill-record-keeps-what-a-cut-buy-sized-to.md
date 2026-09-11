# 261 — `vqapr.fill` keeps what a buy sized to before the planner cut it to the cash

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로) |
| **이슈** | `docs/issues/report-2026-09-11-the-krx-settlement-order-is-not-written-where-an-agent-reads-so-an-agent-reported-vqapr-does-not-apply-it.md` (record 절반; skill 절반은 commit `5cef5321`) |
| **설계 근거** | 오너 판정 2026-09-11 — "열을 더한다"(대안: 문서로 충분) |
| **브랜치** | `develop` |
| **앞선 기록** | `155`(`078`: 지불 가능 수량, 현금을 남긴다), canon 6.3(큰 금액 매수 먼저) |

---

## 왜 이 변경이 있는가

incremental testbed의 opus run이 정답과 NAV·체결 8,834건을 정확히 맞추고도, 최종 보고에 "vqapr는 매도 먼저·큰 매수 먼저를
적용하지 않는다"고 썼다. 두 규칙 다 코드에 있다(`KrxExchange._settlement_order`, `planning._buy_order`). 에이전트가 볼 수
없었던 이유 둘 중 하나가 record였다: `requested_quantity`는 planner가 현금에 맞춰 매수를 깎은 **뒤**의 수량이고, 깎였다는
표시가 없었다. 자기 공식(`trunc(w × NAV / price − held)`)과 비교한 에이전트는 더 작은 숫자만 보고 이유를 못 봤다.

## 무엇이 어떻게 바뀌었는가

planner가 이미 아는 수를 끝까지 들고 간다.

- `exchange/planning.py::_apply_venue_rules`가 두 가지를 돌려준다: 지불 가능한 포지션과, 단위로 반올림한 뒤·현금 컷 **전**의
  포지션(`sized`). `plan_orders`가 요청마다 `sized_quantity = sized − 보유`를 싣는다(가격이 없는 요청은 `None`, venue 규칙이
  없으면 원래 수량 그대로).
- `domain/orders.py::OrderRequest.sized_quantity` — 새 필드, 기본 `None`.
- `domain/ledger.py::fill_entries(at, fills, orders=None)` — 체결마다 그 주문의 `sized_quantity`를 detail에 싣는다. 모든
  venue가 요청에서 체결을 만들지만 여기서 한 번에 붙이므로 venue 코드는 바뀌지 않는다. `flow/run/execution.py`가 주문
  배치를 넘긴다.
- `flow/engine/run_state.py`의 fill 행과 `flow/run/context.py`의 `vqapr.fill` 열 목록에 `sized_quantity`(문자열 Decimal,
  `requested_quantity` 옆).
- skill: analyze-result `result-tables.md`(열 목록과 뜻), `panels-from-tables.md`, make-exchange `execution-profiles.md`
  ("`sized_quantity`는 1단계, `requested_quantity`는 2단계 컷 뒤 — 둘은 현금에 깎인 매수에서만 다르다").

## 바꾸지 않은 것

planner의 결정(무엇을 얼마나 사고 누구를 깎는가), 체결, 계좌, run identity. 기존 열은 그대로이고 열 하나가 더해질 뿐이다
— 이름으로 읽는 reader는 깨지지 않는다. 0.14.5 이전 record에는 이 열이 없다(skill이 그렇게 말한다).

`tests/showcases/baseline-record-digest.json`이 fill 열 목록을 싣고 있지만 그것을 읽는 테스트·스크립트가 없어 건드리지 않았다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/exchange/test_a_cut_buy_keeps_what_it_sized_to.py` (신규, 셋) | 현금이 모자란 두 매수: 작은 쪽 `sized 10 → requested 9`, 큰 쪽 `90 → 90`; `fill_entries`가 주문에서 `sized_quantity`를 싣는다; 주문 없이는 `None` |
| `tests/exchange`, `tests/flow`, `tests/report`, `tests/cli/test_the_run_reports_what_its_orders_did.py` (`-m ""`) | 통과 |
| `test_all` (`uv run python -m pytest tests/ -q -m ""`, records `260`–`263` together) | 1788 passed, 1 skipped, 251.6 s — the record shape changed, so this is the gate |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |
