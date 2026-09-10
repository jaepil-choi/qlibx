# 224 — Evidence keeps a summary, not a mark per name

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 루프 캠페인 P5 (`docs/refactoring/2026-09-10-the-one-loop-campaign.md`) |
| **측정** | `experiments/exp_221_the_market_clock_cost/` |
| **브랜치** | `redesign/one-loop` |
| **앞선 기록** | `223` (A framework-built view proves nothing twice) |

---

## 왜 이 변경이 있는가

exp_221이 잰 메모리 축: 끝난 run이 들고 있는 `Mark` 객체가 **점 수 × 종목 수**였다. 3,000 종목
하루면 1,167,000개, 1년 분봉이면 2.9억 개. 시간이 아니라 메모리에서 먼저 죽는 축이다.

어디에 붙어 있었나. 시장 시계의 점마다 `MarkBatch`(종목당 `Mark` 하나)가 만들어지고, 그것이

```text
ValuationEvidence.marks           → LifecycleTrace(MARKED).detail       run 끝까지
ValuationResult.marks             → MonitoringResult → HeldResult        occurrences 에 run 끝까지
MarkEvidence.marks / selected_marks  체결마다, 같은 모양
AccountCommitEvidence.execution_snapshot   체결마다 venue 행 3,000개
```

그리고 **아무도 읽지 않았다.** 그 mark는 만들어지는 순간 `vqapr.account` 행이 되어 record로
나간다(기록 `221`이 그 길을 열로 만들었다). run이 끝난 뒤 evidence에서 batch를 읽는 곳은 `src/`에
없고, 테스트 하나가 feedback의 `candidates`와 `MarkEvidence.marks`가 같은 객체인지를 볼 뿐이다.

## 무엇이 어떻게 바뀌었는가

- `domain/values.py` — `MarkSummary(total_value, marked)`, `MarkBatch.summary()`.
- `exchange/execution_table.py` — `ExecutionSnapshotSummary(target_at, rows, duplicate_instruments,
  missing_target_instruments, missing_held_instruments)`, `ExactExecutionSnapshot.summary()`. 체결이
  판정된 사실(partition)은 남고 venue의 행은 남지 않는다 — 그 행은 테이블에서 다시 읽는 것이다.
- `flow/engine/artifacts.py` — `ValuationEvidence.marks`·`MarkEvidence.marks`가 `MarkSummary`;
  `MarkEvidence.selected_marks`(SelectedMark 3,000개) → `selected: int`;
  `AccountCommitEvidence.execution_snapshot`이 요약.
- `flow/run/context.py` — `ValuationResult.marks`가 `MarkSummary`.
- `valuation.py`·`execution.py`·`compliance.py` — evidence를 만드는 자리에서 `.summary()`.
- `flow/run/context.py` — `OccurrenceTrace.state`·`DueExecutionTrace.state`(그 점의 `AcceptedRunState` 전체)
  → `root_version: int`. **이것이 진짜 보유처였다.** evidence를 요약으로 바꾼 뒤에도 `Mark`가 그대로
  남았는데, 각 trace가 그 점의 root를 들고 root가 `AccountState`를, 그것이 그 점의 `AccountMark`와
  batch를 들고 있었다. `src/`와 테스트 어디에도 `trace.state`를 읽는 곳이 없었다 — `final_state`가
  run의 권한이고, trace는 version만 말하면 된다.
  `Marked.mark`는 그대로 `MarkBatch`다: handler 사이를 한 점 안에서만 건너고 남지 않는다.

계좌의 `AccountState.marks`(`retained_marks`, 기본 1)는 손대지 않았다 — 그것이 run이 **의도적으로**
들고 있는 유일한 batch이고, 다음 점의 carry-forward가 읽는다.

## 측정 — exp_221, 3,000 종목 × 1일

| | P4 | **P5** |
|---|---|---|
| retained `Mark` | 1,167,000 | **3,000** (계좌가 든 batch 하나) |
| retained `SelectedMark` | 39,000 | **0** |
| run | 36.1 s | **39.5 s** |

점 수에 대해 O(1)이 됐고, 종목 수에 대해서는 계좌가 든 batch 하나만큼이다.

시간은 이 기록의 목표가 아니었고 바뀌지 않았다. 위 두 수는 같은 세션에서 P4 커밋(임시 worktree)과
P5 트리를 번갈아 잰 첫 회차이고, 둘째 회차는 45.7 s / 46.7 s였다 — 이 머신의 실행 간 잡음(±25%)이
두 트리의 차이(1~3 s)보다 크다. P5가 종목마다 하는 일은 없다: 점마다 `.summary()` 셋과 정수 하나다.

## 가드 — `tests/flow/run/test_a_finished_run_keeps_no_mark_per_instant.py`

AC-1 workspace(분봉 열한 점, 종목 하나)를 in-process로 돌리고, 끝난 result가 살아 있는 채로 gc
안의 `Mark`를 센다: **2개 이하**(전에는 점마다 하나). evidence 셋의 타입도 고정한다.

## 검증

```text
uv run ruff check src/                 All checks passed
uv run pyright                          0 errors
uv run pytest tests/ -q                 1647 passed, 4 skipped
showcase digest                         81/81 (show_003 제외)
```
