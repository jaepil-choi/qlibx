# 256 — A run with a record keeps what its fills produced in the record, not in memory

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 수정 (오너 지시로 `develop` 위에서 바로). 메모리 보고의 넷 중 셋째 |
| **이슈** | `docs/issues/report-2026-09-11-a-strategy-runs-memory-grows-with-its-orders-far-past-the-documented-per-worker-size.md` |
| **설계 근거** | 기록 `221`(sink가 있는 run은 recorder 행을 루트에 두지 않는다), `224`(trace는 루트를 들지 않는다 — 한 순간의 장부가 run 끝까지 매달리던 것) |
| **브랜치** | `develop` |
| **앞선 기록** | `221`, `224`, `254`, `255` |

---

## 왜 이 변경이 있는가

측정(합성 300종목, 매 세션 300 fill, `vqapr run`의 경로)에서 루프 동안 자란 메모리의 가장 큰 몫 — fill당 ~1.4 KB — 은
**한 객체 그래프**였다: fill마다의 commit·mark·feedback 증거(`DueExecutionEvidence`와 그 안의 `Fill`·`OrderRequest`·
`FillCost`·`Decimal`들). 그리고 그것을 **세 곳이 함께** 붙들었다:

1. 루트의 `lifecycle_trace` — `ACCOUNT_COMMITTED`·`MARKED`·`MONITORED`·`FEEDBACK_PUBLISHED` 항목의 `detail`;
2. 루트의 `feedback` — fill마다 `DueExecutionEvidence`를 덧붙이고 줄이지 않음(src에 읽는 곳이 없다);
3. `SimulationResult.occurrences`의 `DueExecutionTrace.result`.

셋 중 하나나 둘만 끊으면 아무것도 풀리지 않았고(측정), 셋을 다 끊어야 fill당 1.37 KB가 사라졌다. record가 있는 run에서
fill은 만들어지는 순간 `vqapr.fill` 행이다 — 기록 `221`이 행에 대해 세운 규칙("sink가 있으면 루트는 들지 않는다")이
그 증거에는 적용되지 않았던 것이다.

## 무엇이 어떻게 바뀌었는가

- `flow/engine/run_state.py`: `RunStateRepository.keeps_evidence`(= sink가 없다). 없으면(=record가 있으면)
  `_advance`가 fill 쪽 항목을 **kind만** 남긴다(kind마다 공유하는 `_BARE` 항목), `prepare_feedback`은 `feedback`을
  쌓지 않는다. 결정 항목(`NO_DECISION`·`ACCEPTED_INTENT`)의 `CallbackEvidence`는 **남긴다** —
  `callback_evidence(result)`가 in-process 호출자가 전략의 결정을 읽는 길이고, showcase 006·007·008이
  `store_root`를 준 run에서 그것을 읽는다.
- `flow/run/context.py`: `InstantOutcome(account_version, monitoring)`과 `DueExecutionResult.outcome()` ·
  `HeldResult.outcome()`. `flow/run/loop.py::MarketClock.at`이 record가 있는 run에선 trace에 outcome만 싣는다.
  `report`와 `monitoring`은 그대로 답하므로 record의 `contract` 블록(`contract_report`)과 monitoring 테스트가 읽는 것은 같다.

**새 옵션을 만들지 않았다.** 무엇을 드는가는 "record가 있는가" 하나로 정해진다(`221`과 같은 문). record 없이 도는
in-process run은 모든 증거를 이전처럼 든다.

## 바꾸지 않은 것

lifecycle의 kind 순서와 개수(showcase 001·003과 테스트들이 센다), `occurrences`의 길이와 종류, `callback_evidence`,
record의 내용, record 없는 run의 결과 전부.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/flow/run/test_a_stored_run_keeps_no_fill_evidence.py` (신규, 샘플 journey) | record 있는 run: fill 쪽 항목 detail 없음, `feedback == ()`, 시장 trace가 `InstantOutcome`, `gc` 후 `DueExecutionEvidence` 0개, `callback_evidence`는 `CallbackEvidence`들. record 없는 run: 전부 그대로 |
| `tests/flow tests/acceptance tests/boundaries tests/compliance tests/cli` | 589 passed (stored sink로 monitoring을 읽는 `test_monitoring_findings_reach_the_record` 포함) |
| 메모리, 합성 300종목(`scratchpad/mem/measure.py`, 한 프로세스, record 있는 `vqapr run` 경로) | `trade-500`(150k fill): 1.503·1.518 → 1.428(`254`) → **1.286 GB**. `trade-1000`(300k fill): 1.961·1.944·1.952 → **1.425 GB**, peak working set 1.10 → 0.66 GB. Hold 바닥(0.96 GB) 위의 증가가 fill당 3.3 → 1.6 KB. 이 run들은 spill하지 않으므로 `255`는 이 수치에 들지 않는다 |
| 같은 머신 A/B, `trade-1000`, 교대로 두 번씩 — `efeb0f49`(record `253`, `254` 이전)를 `git archive`로 떠서 `PYTHONPATH`로 | base **1.944 · 1.938 GB** / head(`254`–`256`) **1.441 · 1.427 GB**. 루프 끝 private 1.55 → 1.31 GB; base의 peak는 envelope의 fill 전체 읽기, head의 peak는 publish/envelope 단계. wall 26–29 s로 양쪽 같음(앞선 16.5 s → 26 s는 공유 머신의 부하였다) |
| `uv run ruff check src/` · `uv run python -m pyright` (바뀐 파일) | clean · 0 errors |

남은 fill당 몫(추정, 측정의 분해에서): writer의 Arrow 버퍼 ~0.5 KB(설계상 256 MB에서 spill), 결정의
`CallbackEvidence` ~0.2 KB, 할당기 단편화 추정 ~0.4 KB.
