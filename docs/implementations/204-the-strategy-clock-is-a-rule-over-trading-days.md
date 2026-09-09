# 204 — The strategy clock is a rule over trading days

| | |
|---|---|
| **작성 시각** | 2026-09-09 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M4 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md` 1c) |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §3.2 (전략 시계는 execution table에서 유도되지 않는다) · §3.3 (날짜는 유도해도 되고, 시각은 안 된다) · §3.4 (agenda 어휘) |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `203` (주문은 선언된 종목을 부른다) |

---

## 왜 이 변경이 있는가

run은 지금까지 `sessions_from: <dataset>`(또는 `sessions:` 목록)과 `at: HH:MM` 하나로 자기 시계를
말했다. 하루에 한 번, 데이터셋이 가진 날마다. 그것으로는 설계 §3이 요구하는 두 가지를 말할 수 없었다:

- **매 분 판단하는 전략.** 1분 execution table 위에서 09:00부터 15:20까지 매 분 결정하는 전략을
  선언할 어휘가 없었다. `sessions`는 날짜의 목록이고 `at`은 시각 하나다.
- **월간 전략이 매일 불리지 않을 권리.** 월 1회 전략은 매 세션 불려서 스스로 `Hold`를 돌려줘야
  했고, 스킬은 그것을 *"a monthly rebalance is a rule inside the strategy"*라고 가르쳤다. 전략의
  시계가 전략 파일 안에 숨는 것이다.

그리고 한 가지가 원칙과 어긋나 있었다: `sessions_from`은 **어떤 dataset이든** 날짜의 출처가 될 수
있었다. 설계 §3.3은 *"execution table에 행이 있는 날이 거래일이다"*라고 정했다 — 거래일은 시장의
사실이고 시장의 사실은 venue 테이블이 답한다. 관측 데이터셋의 날짜로 거래일을 대신하면 데이터가
빠진 날에 전략이 침묵하고, 데이터가 있는 휴일에 전략이 깨어난다.

---

## 무엇이 어떻게 바뀌었는가

### 선언: `agenda:` 블록 하나

```yaml
runs:
  my-run:
    timezone: Asia/Seoul
    agenda:
      every: 1d              # 1d | 2d | 1w | 1M — 거래일을 고른다. at 과 짝
      at: "15:29"            #   시각 하나 또는 목록
    # agenda:
    #   every: 5m            # 1m | 5m | 1h — 하루 안의 시점을 고른다. from/to 와 짝
    #   from: "09:00"
    #   to: "15:20"
    # agenda:
    #   every: 1d
    #   at: "16:00"
    #   days_from: prices    # datamodel run 만 — venue 가 없으니 날짜의 출처를 이름으로 댄다
```

`at`·`sessions`·`sessions_from`은 run 층에서 사라졌다. 옛 spelling은 읽지 않는다 — 로더가 세 키를
만나면 `agenda:`로 옮기라는 한 문장으로 거절한다 (`_from_the_stored_spelling`). M2에서는 옛 spelling을
계속 읽었는데, 이번엔 안 그런 이유가 있다: 옛 `sessions_from`을 strategy run에서 `days_from`으로
끌어올리면 **틀린 날짜 출처를 조용히 보존**하는 것이고, 버리면 조용히 의미가 바뀌는 것이다. 어느 쪽도
말 없이 해선 안 된다. 다시 등록하는 것이 옳다.

### 날짜는 데이터가, 시각은 규칙이

```
strategy run     거래일 = execution.dataset 에 행이 있는 날.   선언할 것이 없다
datamodel run    거래일 = agenda.days_from 에 행이 있는 날.    venue 가 없으므로 이름을 댄다
둘 다            시각   = agenda 규칙.  테이블의 밀도와 무관
```

`derived_agenda`(preflight)가 그 출처의 `evaluation_times`를 읽어 venue-local 날짜로 접고, 기간
`[start, end]`으로 자르고, 규칙을 전개한다. **`UC-TIME-002`의 보장이 여기서 지켜진다** — 1분 테이블과
일별 테이블은 같은 날짜 집합을 가지므로 같은 agenda가 나온다. 새 도메인 테스트가 그것을 identity로
고정한다.

strategy run이 `days_from`을 적으면 거절하고(*"its trading days are the days its execution table has
rows for"*), datamodel run이 안 적으면 거절한다. `writes`와 `days_from`이 같아도 거절한다 —
만들려는 dataset에서 날짜를 가져올 수 없다.

### 도메인: `AgendaRule` + `OperationAgenda.expand`

`domain/agendas.py`에 규칙이 값으로 들어갔다. `every`는 `^(\d+)([mhdwM])$` — 개수와 단위.

```
d / w / M   날 단위.  at 필수(하나 이상, 중복 불가), from/to 거절
            Nd: 거래일 N개마다.  Nw: 매 N번째 ISO 주의 첫 거래일.  NM: 매 N번째 달의 첫 거래일
m / h       하루 안.  from·to 필수(from ≤ to), at 거절
            선택된 모든 거래일에 from 부터 to 까지 N분/N시간 간격, 양 끝 포함
```

`expand(agenda_id, days, rule, timezone)`이 날짜를 접고(같은 날은 한 번), `rule.select_days`로 고르고,
`rule.times()`를 곱해 occurrence를 만든다. occurrence id는 **한 가지 꼴** `{agenda_id}-{date}T{HHMM}`
— 하루에 하나든 390개든 같은 규칙이다. `daily(...)`는 `expand(rule=AgendaRule("1d", (at,)))`의
얇은 포장으로 남았다. fold·offset은 전과 같이 `declare_local_instant`가 증명하고, 없는 시각(봄
DST)·두 번 오는 시각(가을 DST)은 거절한다.

`AgendaRule("1M", ...)`은 **달의 첫 거래일**이다. 마지막 거래일 어휘(`last`)는 안 넣었다 — 설계가
네 단어를 정했고, 필요가 확인되면 그때 단어를 늘린다.

### 표면

```
project/run.py          RunAgenda(every, at, from, to, days_from)  — pydantic, `from` 은 alias
                        RunDefinition.agenda 필수.  agenda_id = "<run_id>.agenda"
                        spoken(): "the model is called every 1d at 15:29:00 Asia/Seoul, over the
                                   days its execution table has rows for, ..."
document / store /      sessions_from 참조 검사 → agenda.days_from
references / registration   `rm dataset` 차단 사유 "(agenda.days_from)".  sibling 규칙의 source key
                        `runs.<id>.agenda.days_from`.  run_invalid requirement 문장
cli/new.py              run 템플릿과 datamodel 스캐폴드가 agenda 블록을 emit
sample                  agenda: {every: 1d, at: CALLBACK}
public                  RunAgenda export
skills                  run-declaration.md 의 "Sessions and the wall time" → "The strategy clock:
                        agenda".  SKILL.md 의 "monthly rebalance is a rule inside the strategy" 철회.
                        running-a-datamodel.md · deleting.md · correcting-a-registration.md ·
                        records-and-tweaks.md
showcases 8개           sessions=/at= → agenda=RunAgenda(...).  datamodel run 은 days_from="price_daily"
```

---

## 무엇을 잃었나

- **`sessions:` 리터럴 목록.** 날짜를 손으로 적는 길이 없어졌다. 설계 §3.4: *"요구는 run 시작
  시점에 완전히 결정되어 있는 것이지, 사람이 목록을 타이핑하는 것이 아니다."* 특정 날짜 몇 개에만
  결정하고 싶다면 기간(`start`/`end`)과 `every`로 말하거나, 그 날짜를 가진 dataset을 등록하고
  datamodel run으로 만든다. showcase 전부가 `sessions[k:]` 꼴의 연속 슬라이스였고 `start`/`end`로
  같은 뜻이 됐다.
- **strategy run의 `sessions_from`.** 관측 데이터셋의 날짜를 거래일로 쓰던 것. 이제 execution
  table이 답한다.
- **옛 spelling 호환.** 위의 이유로 안 읽는다. 2026-09-09 이전 워크스페이스는 다시 등록한다.
- **agenda의 이름.** `agenda_id`와 occurrence id 꼴이 바뀌어 `strategy.json`·`datamodel.json`의
  `agenda` 블록이 움직였다. run identity는 이름을 접지 않으므로 `run.json`과 테이블은 그대로다.
- 테스트 픽스처가 "날짜 목록"에서 "행이 있는 테이블"로 옮겨 갔다: `test_check`의 `_venue_dataset`,
  `test_check_collects`의 `_run_ready`가 placeholder 대신 진짜 parquet을 쓰고, `test_preflight`의
  `_execution_exchange`가 `days`를 받는다.

---

## 검증

```
uv run python -m pytest tests/ -q -m ""       1634 passed  (신규 15: 도메인 규칙 9 · preflight 재작성 3 · run 2 · 기타)
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
python -m tests.characterization.refusal_codes 재생성 (run_invalid 문장 하나)
scripts/showcase_record_digest.py --check      17/81 changed → 원인 확인 후 다시 잡음 → 81/81
```

**digest 17건은 전부 `strategy.json`·`datamodel.json`이고, 그 안의 `agenda` 블록이다** —
`agenda_id`가 `<run>.sessions`에서 `<run>.agenda`로, `content_identity`가 occurrence id 꼴을 따라
움직였다. **`run.json`과 테이블은 한 건도 안 바뀌었다.** run identity(`declared_digest`)는 agenda의
내용(zone과 local instant)만 접고 이름은 접지 않으므로(`FrozenAgenda.encoded`, 2026-09-03 owner
ruling) 모든 record 행의 `run_id`가 그대로다. M2 발견의 예측("identity가 움직인다")은 이번엔
틀렸다 — 좋은 쪽으로. 기준선을 다시 잡았다.

**첫 스위트에서 15건 + 4 error가 떨어졌고 전부 sweep의 잔여였다**: 서브프로세스 RUNNER 문자열
안의 import, `_lookahead_run(at=...)` 같은 헬퍼 오버라이드, "sessions dataset"을 망가뜨리던 테스트가
이제 execution table을 망가뜨려야 하는 것, 그리고 `sessions=(4, 6, 8)`을 `every: 2d`로 옮긴 것 하나.

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **기계 sweep은 중첩된 `at=`을 훔친다.** `RunDefinition(...)` 안의 `at=`/`sessions=`를 `agenda=`로
  옮기는 스크립트가 처음엔 같은 블록 안 `RunFill(at=time(15, 30))`의 `at`까지 집어 agenda에 넣고
  fill에서 지웠다 (show_006, 그리고 dict 판에서는 `"fill": {"at": ...}`). 되돌리고 **호출의 자기
  들여쓰기 층에서만** 키워드를 보게 고쳤다; dict/yaml 판은 같은 들여쓰기 형제에 `trade_price`/
  `selector`가 있으면 fill로 보고 건너뛴다. 감사 방법: diff에서 지워진 줄 중 `fill`·`trade_price`·
  `selector`를 담은 것이 0이어야 한다.
- **UTC로 만든 시각을 서울 날짜로 접으면 하루가 늘어난다.** `UC-TIME-002` 테스트의 첫 판이 09:00–
  15:29 UTC 분 격자를 만들었고, 그것은 KST로 18:00–00:29 — 이틀에 걸친다. 격자는 venue zone으로
  만들어야 한다.
- **`_judge` 헬퍼는 agenda를 먼저 만든다.** `test_check`에서 venue 테이블 없이 `_judge`를 부르면
  `my-exec` lookup에서 올라온다 — 옛 `sessions=` 리터럴이 그 의존을 감추고 있었다. 이제 두 테스트가
  `_venue_dataset`을 먼저 부른다.

---

## 다음 기록이 이어받을 것

- **M5 (체결 시각 어휘).** `RunFill(selector, at, timezone)`이 아직 옛 어휘다. 매 분 agenda(`every:
  1m`)는 이제 선언되지만 `same_day at 15:30` fill과 만나면 15:30 이후의 결정이
  `execution.not_after_decision`에 걸린다 — 설계 §3.5의 *"결정 이후 첫 시장 시계 점"*이 그 답이고
  그것이 M5다.
- `_judge_execution_ordering`은 occurrence의 `local_time >= fill.at`으로 본다. 하루 여러 시각이 되면서
  같은 논리가 시각마다 적용될 뿐 바뀌지 않았다; M5에서 fill이 "다음 시장 시계 점"이 되면 이 판정은
  "결정 뒤에 시장 시계 점이 하나라도 있는가"로 바뀐다.
- `AgendaRule.select_days`의 `Nw`/`NM`은 "첫 거래일"이다. `last`는 필요가 확인되면.
