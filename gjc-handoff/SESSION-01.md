> **이건 세션 1(`01a031f9`)의 기록이다. 새 세션은 `README.md`(START HERE)부터 읽는다.**
> 원본은 `../kwam-enhanced-index/gjc-handoff/README.md`.

# gjc ultragoal 세션 핸드오프 — vqapr Agent-First Python API (qlibx 측)

2026-08-24 gjc ultragoal 세션 `01a031f9-aa43-703c-b219-d0e2d7a27a4d`이 이 repo에 만든 G002
부분 산출물의 핸드오프 노트다. 세션은 G002 진행 중 오너가 의도적으로 종료했다.

세션 상태 원본(goals, ledger, plans, specs, state)은 sibling repo
`kwam-enhanced-index/gjc-handoff/session-state/`에 그대로 보존돼 있다.
이 디렉터리에는 qlibx 작업에 필요한 사본만 둔다.

```
ultragoal-goals.json      5개 goal 정의와 종료 시점 상태
ultragoal-ledger.jsonl    감사 로그
ultragoal-brief.md        실행 브리프
approved-plan.md          최종 합의 계획 963줄 (승인 대기)
```

## 반드시 먼저 읽을 것 — 모델이 요구사항과 달랐다

**`approved-plan.md`를 작성하고 리뷰한 주체, 그리고 아래 코드를 지시한 리더가 모두
오너가 지정한 `claude-opus-5`가 아니었다.**

| 모델 | turn | 구간(KST) | 담당 |
|---|---|---|---|
| `claude-opus-5` | 64 | 13:14 → 14:04 | deep-interview |
| `claude-opus-4-6` | 6 | 13:51 → 13:59 | opus-5 폴백 |
| `gpt-5.6-sol` (openai-codex) | 200+ | 14:08 → 종료 | **ralplan 전 과정 + ultragoal 실행 전부** |

planner는 `gpt-5.6-terra`, architect/critic은 `gpt-5.6-sol`, 구현 워커는 `claude-sonnet-5`였다.

원인은 gjc의 모델 프로파일 활성화가 **다음 사용자 턴에 적용**되는데, 16:59:32에 예약된
`claude-opus` 프로파일이 적용될 사용자 턴이 끝내 오지 않았기 때문이다. 자세한 내용은
`kwam-enhanced-index/gjc-handoff/README.md`에 있다.

**아래 코드를 그대로 신뢰하지 말고, 재개 전에 계획과 구현을 opus-5로 재검토할지 판단하라.**

## 이 커밋에 담긴 G002 부분 산출물

gjc가 ledger에 남긴 자기 평가(`steering_accepted / annotate_ledger`, 09:35:35Z):

> G002 partial: authoring/materialization/simulation/venues contracts, v1 identity codec, and
> internal extension relocation implemented; 169 focused tests pass and ruff clean. Model runtime
> adapter executor stalled without saving implementation and was cancelled; fresh
> invocation/named-read/state-diagnostic prepared-root adapter remains resolvable work.
> G002 intentionally not checkpointed.

### 새 공개 모듈

```
src/vqapr/authoring.py        754 lines
src/vqapr/simulation.py       547 lines
src/vqapr/venues.py           196 lines
src/vqapr/materialization.py  161 lines
```

### 내부 권한 경계 (`_internal` 이동)

```
src/vqapr/_internal/__init__.py
src/vqapr/_internal/extensions/{__init__,component,fingerprint,identity,loading,registration}.py
src/vqapr/_internal/models/{__init__,agent_first}.py
```

기존 `src/vqapr/extension/` 네 파일은 본체를 `_internal/extensions/`로 옮기고 forwarding adapter만
남겼다. 순감 520줄 / 순증 61줄이며 **기존 import 경로는 아직 살아 있다.**
계획상 하드 삭제는 G004에서 일어나므로 이 커밋에서는 제거하지 않았다.

```
M src/vqapr/extension/component.py     -66 +
M src/vqapr/extension/fingerprint.py   -44 +
M src/vqapr/extension/loading.py      -285 +
M src/vqapr/extension/registration.py -186 +
```

### 새 테스트

```
tests/extension/test_agent_first_identity.py        450 lines
tests/extension/test_agent_first_internal_routes.py 194 lines
tests/models/test_agent_first_authoring.py          635 lines
tests/models/test_agent_first_run_values.py         648 lines
```

## 미완료 — 재개 지점

**model runtime adapter가 G002의 남은 작업이다.**

`src/vqapr/_internal/models/agent_first.py`(422줄)는 세션 종료 직전 마지막 워커가 저장한 것으로,
구문상 온전하지만 **테스트가 작성되지 않았고 검증되지 않았다.** 리더는 이 slice를
"tests는 다음 leader slice에서 작성한다"는 전제로 투입했고 그 다음 단계에 도달하지 못했다.

재개할 때 다음을 확인하라.

1. `agent_first.py`의 fresh invocation / named-read / state-diagnostic prepared-root adapter가
   `approved-plan.md`의 `StrategyCall` 계약과 일치하는지.
2. 해당 adapter의 테스트 작성 및 replay/state/evidence parity 증명.
3. 그 뒤에야 G002를 checkpoint하고 G003(Project transactions and atomic publication)로 넘어간다.

## 검증 상태

- 169 focused tests pass, ruff clean — **단, `agent_first.py` 추가 이전 시점의 결과다.**
- 재개 시 전체 스위트를 다시 돌려 현재 트리 기준으로 확인하라.
  이 세션은 G001을 낡은 테스트 결과로 완료 처리한 전례가 있다.

## 알려진 운영 이슈

1. 완료된 워커를 "파일을 저장하지 못했다"고 오판하고 취소한 사례가 있다. 파일은 취소 3분 전에
   이미 디스크에 있었다. 진행 판정 전 파일시스템을 재확인하라.
2. 큰 slice를 받은 sonnet-5 워커가 반복적으로 stall했다. 파일 단위로 쪼개 재투입하면 성공했다.
