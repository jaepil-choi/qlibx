# 237 — The ordering judgment asks about the occurrences inside the run

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 없음 — testbed 보고 하나를 닫는 bounded fix |
| **이슈** | `docs/issues/099` — 닫는다 |
| **설계 근거** | 설계 §3.4: run의 agenda는 하나이고 preflight가 `[start, end]`로 얼린다(`_freeze_agenda`). 판단은 run이 걷는 것과 같은 occurrence에 대해 답해야 한다 |
| **브랜치** | `develop` (0.13.0 stamped 뒤) |
| **앞선 기록** | `148` (run의 agenda 하나), `069` (`derived_agenda`가 날짜로 자른다), `077` (답하지 못한 판단은 blocked) |

---

## 왜 이 변경이 있는가

enhanced-index testbed(0.11.0 wheel)의 보고. 16:00에 찍히는 datamodel 출력을 읽어 거래하는 일간 전략은
그 stamp 뒤인 **16:30에 결정**하고 `fill.at: 15:30`으로 **다음 세션 종가에 체결**한다. 마지막 데이터
날의 16:30 결정은 체결할 다음 세션이 없으므로 run은 그 앞에서 끝나야 하고, 그 날 15:30 체결(전날
결정의)은 포함해야 한다. 옳은 `end`는 정확히 하나의 종류 — 마지막 체결과 마지막 결정 사이, 예컨대
`2026-07-28T16:00` — 인데, 그 `end`만 `vqapr check`가 500 `judgment.blocked`로 죽었다:

```
execution_ordering could not answer: ValueError: decision_time must not be after end_time
```

`end`를 그 날 23:59로 두면 412 `execution.not_after_decision`이 제대로 나온다. 즉 옳은 선언만
거절되고, 그것도 이유를 말하지 못한 채였다. 보고자는 설계를 바꿔(15:29에 매일 결정, 입력이 새
cross-section을 냈을 때만 새 book) 우회했고, 분기마다 바뀌는 입력을 위해 매 세션 호출되는 비용을 냈다.

`develop`(0.13.0)에서 그대로 재현된다. 원인은 agenda를 읽는 자리 하나뿐이다.

## 무엇이 어떻게 바뀌었는가

`derived_agenda`(`flow/declaration/preflight.py`)는 record `069` 이후 occurrence를 만들기 전에
**venue-local 날짜**로 세션을 자른다 — `[start, end]`의 상위집합을 남기고, 그 주석이 그렇게 말한다.
preflight는 그것을 `_freeze_agenda`가 `inclusive_slice(start, end)`로 얼린 뒤 `_validate_execution_targets`에
넘기고, run은 얼린 것을 걷는다. `judgments.py`의 `_first_decision`도 `start <= moment <= end`로 거른다.

`_judge_execution_ordering` 하나만 `agenda().occurrences`를 그대로 순회했다. `end` 날의 16:30
occurrence가 `end` 뒤에 있는 채로 `select_target`에 들어갔고, `select_target`은 계약대로
`decision_time > end_time`을 `ValueError`로 거절했다. 판단이 답하지 못했으니 `077`의 규칙대로 blocked,
status 500.

변경은 그 한 줄이다: 판단이 `agenda().inclusive_slice(definition.start, definition.end)`를 순회한다.
preflight가 얼리는 것과 같은 조각이므로 `check`와 `run`이 같은 agenda를 본다. `select_target`의
계약 검사는 그대로 둔다 — 호출자가 계약을 지키게 된 것이지, 계약이 틀린 것이 아니다.

바꾸지 않은 것. envelope에서 `ok: false`·`failures: []`·원인은 `blocked`에 있는 모양은 `cli/check.py`가
주석으로 설계한 것이다(답하지 못한 판단은 실패도 통과도 아니다). 보고자의 세 번째 청 — `failures`만
읽는 호출자가 `blocked`를 놓친다 — 는 이 record의 범위 밖이며, 별도로 판정할 일이다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/cli/test_check.py::test_an_end_between_the_last_fill_and_the_last_decision_is_answered` (신규) | 16:30 결정·15:30 체결, 이틀. `end`가 마지막 날 16:00 → `[]`; 15:30(마지막 체결과 같은 순간) → `[]`; 23:59 → `["execution.not_after_decision"]`. 수정 전엔 앞의 두 경우가 보고의 `ValueError`로 죽는 것을 확인 |
| `tests/cli`·`tests/qa`·`tests/flow`·`tests/characterization` | 564 passed, 6 deselected (202 s) |
| ruff (바뀐 두 파일) · pyright (`judgments.py`) | clean (남은 E501 넷은 `test_check.py`의 기존 줄) · 0 |
