# 278 — 루프의 어휘는 이산 사건 시뮬레이션의 것이다: `schedule` · `ScheduledEvent` · `event_id`

| | |
|---|---|
| **작성 시각** | 2026-09-12 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M11a — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §3.2 · §4.4 · §17 "공개 어휘", 오너 결정 D4 (2026-09-11) · 옛 기록 처리 A (2026-09-12) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `271`–`277` |
| **깨지는 변화** | 예. 0.16.0에 D8(`vqapr.authoring` 삭제, record `279`)과 함께 나간다 |

---

## 왜 이 변경이 있는가

vqapr의 루프는 이벤트 주도 아키텍처(EDA)가 아니다. 이산 사건 시뮬레이션(DES)이다. 알려진 시계 둘을 한 번 정렬하고,
그 순서대로 한 번 걷는다. 그런데 이름은 다른 전통에서 왔다.

- `agenda`: SICP의 시뮬레이터에서 "시간순 대기열 전체"를 뜻한다. 선언된 규칙(`every: 1d, at: 08:00`)에도, 펼친
  시각 목록에도 이 이름이 붙어 있었다.
- `occurrence`: iCalendar의 반복 규칙이 만든 한 번을 뜻한다. 루프 안에서는 `OccurrenceEvent`로 한 번 더 감쌌다.
- `Clock.STRATEGY`: DataModel run도 이 시계를 걷는데, 이름은 전략의 것이라고 했다.

오너는 이렇게 물었다. "event driven architecture에서 occurrence라고 부르는 게 일반적이야? event라고 부르지 않고?" 결정(D4)은
DES의 이름을 쓰는 것이었다. schedule이 사건을 만들고, 체결표가 시장 사건을 만든다.

## 무엇이 어떻게 바뀌었는가

| 0.15.0 | 0.16.0 |
|---|---|
| run 선언의 `agenda:` | `schedule:` |
| `RunAgenda` · `FrozenAgenda` · `AgendaRule` · `OperationAgenda` | `RunSchedule` · `FrozenSchedule` · `ScheduleRule` · `Schedule` |
| `OperationOccurrence` + 루프의 `OccurrenceEvent` | `ScheduledEvent` 하나 (루프가 도메인 값을 그대로 정렬한다. 자기 `sort_key`를 이미 가지고 있다) |
| `AgendaId` · `OccurrenceId` · `agenda_id` · `occurrence_id` | `ScheduleId` · `EventId` · `schedule_id` · `event_id` |
| `OccurrenceTrace`, `result.occurrences` | `EventTrace`, `result.events` |
| `Clock.STRATEGY` | `Clock.SCHEDULE` |
| `call.occurrence_id` | `call.event_id` |
| `call.evaluation_time` (Call 셋) | `call.at` — 네 Call이 모두 같은 이름을 답한다(`ExecutionCall.at`은 원래 이 이름) |

- **옛 키는 거절하고 번역하지 않는다.** 선언 문서든 저장된 `workspace.yaml`이든, run에 `agenda:`가 있으면 무엇이
  무엇으로 바뀌었는지와 다시 등록하라는 fix를 말한다(오너: "전부 재등록 요구해"). 옛 키를 읽는 코드는 없다.
- **옛 기록도 거절한다(오너 결정 A, 2026-09-12).** `run.json` · `strategy.json` · `datamodel.json`의 schema가 모두 v2가
  됐다. v1 기록은 "0.16.0 전에 기록됐다. 다시 run 하라, `vqapr rm`이 옛 기록을 지운다"라는 거절을 받는다. 더 새 버전의
  기록에는 "vqapr를 올려라"라고 말한다. reader는 원래 schema가 정확히 같은지 확인하는 문이었고, 이번에는 그 거절문이
  갈 길을 말하게만 했다.
- **남긴 이름.** `ScheduledEvent.evaluation_time`(사건 자신의 시각)과 `ModelWindow.evaluation_time`(데이터 층의 창)은
  그대로다. 저자에게 보이는 시각은 `call.at` 하나다. 두 레거시 거절(0.3.0의 `agendas:` 절, 옛 top-level 절 이름)은
  옛 철자를 거절하는 코드라 옛 철자를 그대로 둔다.
- `tests/characterization/test_check_and_run_envelopes_hold.py`는 선언을 `experiments/exp_235_the_scenario_trace/`에서
  읽고 있었다. 실험은 자기가 잰 버전에 고정된 채 남는다. 그래서 새 어휘로 옮긴 사본을
  `tests/characterization/declarations/`에 두고, 테스트가 그것을 읽게 했다.
- 테스트 파일 이름 셋도 바꿨다(`test_agendas` → `test_schedules` 등). 레코드 거절을 고정하는 테스트를 새로 더했다
  (`tests/record/test_an_old_record_is_refused_with_a_rerun.py`).

## 검증

| 검사 | 결과 |
|---|---|
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1800 통과 · 5 skip (212 s). 새 레코드 거절 테스트 셋이 더해졌다 |
| showcase digest | 기준선과 경로가 다르다. showcase 컴포넌트의 바이트가 바뀌어 지문이 바뀌었기 때문이다. 지문을 떼고 내용으로 비교하면 **표 46개가 모두 같다**(숫자는 하나도 바뀌지 않았다). 다른 것은 JSON 기록뿐이다: `run.json` 18 · `strategy.json` 14 · `datamodel.json` 3(schema v2, `schedule` 블록, 지문). 기준선에만 있는 둘은 손으로 돌리는 `show_003`의 것이다. 기준선은 릴리스 때 다시 기록한다 |
| `uv run ruff check src/` | 통과 |
| `uv run pyright` | 0 errors, 0 warnings |
