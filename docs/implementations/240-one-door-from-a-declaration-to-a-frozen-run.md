# 240 — One door from a declaration to a frozen run: `verify_run`

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 문(run) 캠페인, M2 — `docs/design/2026-09-10-one-door-for-a-run.md`, 브랜치 `redesign/one-door-run` |
| **이슈** | 없음 (오너 결정 2026-09-10: 검사관과 공증인을 `verify_source`의 모양으로 합친다) |
| **설계 근거** | 기록 `234`(데이터의 문 하나), `087`·`168`(check와 run은 같은 것을 거절한다), `077`(답 못 한 판정은 통과가 아니다) |
| **브랜치** | `redesign/one-door-run` (develop 0.13.1 + 기록 238·239 위) |
| **앞선 기록** | `087`, `168`, `238` |

---

## 왜 이 변경이 있는가

run 선언을 이름에서 값으로 푸는 길이 두 벌이었다: `judgments()`(모아서 답한다)와 `preflight_run`(첫 거절에서
멈추고 얼린다). `check`는 둘을 phase로 따로 불렀고, `run`은 `require_judged` 뒤 freeze를 불렀고, `--jobs`
worker는 **freeze만** 불렀다 — 판정을 아예 묻지 않아 `run a b --jobs 2`가 `check`와 `run a`가 거절하는 run을
돌렸다(`docs/issues/archive/015`의 틈이 문 하나 건너에서 다시 열려 있었다). 이 기록은 그 길을 함수 하나로
만든다. 사실을 한 번만 읽게 하는 것(M3·M4)은 이 문 안에서 다음 기록들이 한다.

## 무엇이 어떻게 바뀌었는가

`flow/declaration/verify.py`:

```
verify_run(workspace, definition) -> RunVerdict(failures, blocked, frozen, refusal)
RunVerdict.require_frozen() -> FrozenRun   # run이 거절하는 규칙: 판정의 거절(output_stale 제외)·blocked 먼저, 그다음 freeze의 것
```

- `check`(`cli/check.py`)의 judgments · preflight 두 phase가 **한 verdict**를 읽는다. freeze의 거절은 예외 객체
  그대로 verdict에 실려 오고 phase 루프의 기존 handler가 예전과 같이 그린다 — `VqaprError`는 자기 stage와
  `retry_precondition`을, 맨 `TypeError`/`ValueError`는 `preflight_refusal`로. 봉투는 바이트 단위로 같다(특성화
  baseline, 아래).
- `orchestration.preflight_run`(공개 문, `public.preflight_run`과 `execute`)은 `verify_run(...).require_frozen()`.
  `require_judged`는 삭제.
- `--jobs` worker 둘(`run_registered_datamodel` · `run_registered_strategy`)도 같은 문을 지난다. **행동 변화 하나**:
  배치 안의 run이 이제 판정을 받는다. 순차 `run`이 거절하는 run은 배치에서도 거절된다.

verdict가 `(Diagnosis, FrozenRun)`이 아니라 freeze의 예외를 그대로 드는 이유: 두 동사가 같은 거절을 다르게
그린다(`check`는 failure 항목, `run`은 raise). 봉투를 지키는 한 그 둘을 한 값으로 접을 수 없고, 접는 것은 이
캠페인의 마지막 결정(M5)이다.

**바꾸지 않은 것.** `judgments.py`의 judge들과 `preflight.py`의 freeze — 아직 각자 사실을 읽는다(M3·M4).
`check`의 봉투 두 가지 wart(같은 결함이 `run.output_registered`로 두 번; freeze의 거절이 판정 쪽에선
`judgment.blocked`로 한 번 더) — baseline이 그대로 고정하고 있고, 고치는 것은 봉투를 바꾸는 별도 결정이다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/characterization/test_check_and_run_envelopes_hold.py` (M1, `f6ef3e52`) | sample door의 `check`·`run` 봉투 8개, 이동 전과 바이트 단위로 같음 |
| `tests/characterization` · `tests/cli/test_check.py` · `tests/flow/declaration` · `tests/boundaries` | 198 passed, 1 skipped |
| `uv run python -m pytest tests/ -q` (fast) | 1,707 passed, 1 skipped (worker 경로 포함) |
| `uv run ruff check src/` · `uv run python -m pyright` | clean · 0 errors |
