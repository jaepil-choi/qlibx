# 205 — A decision fills at the next market-clock instant

| | |
|---|---|
| **작성 시각** | 2026-09-09 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M5 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md` 1d) — **Stage 1 완료** |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §3 (시장 시계 = execution table의 모든 timestamp) · §3.5 (체결 시각 어휘) |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `204` (전략 시계는 거래일 위의 규칙이다) |

---

## 왜 이 변경이 있는가

M4가 매 분 판단하는 전략을 **선언**할 수 있게 했지만, 그 결정이 언제 체결되는지는 아직 옛 어휘가
정했다: `fill: {selector: same_day | next_eligible, at: HH:MM, timezone, trade_price}`. 그 어휘로는
"다음 분에 체결"을 말할 수 없다 — `at` 하나가 하루의 시각 하나를 고르고 `selector`는 그 시각이 오늘인지
내일인지를 고른다. 1분 격자에서 09:03의 결정은 09:04에 체결돼야 하는데, 옛 어휘로는 `at`을 09:04로
못 박는 수밖에 없고, 그러면 09:04의 결정은 갈 곳이 없다.

설계 §3.5의 답은 어휘를 늘리는 것이 아니라 **기본값을 바꾸는 것**이다:

> **기본: 결정 이후 첫 시장 시계 점.** 그 위에 선택적 손잡이 셋 — `at`(하루 중 시각으로 후보를 좁힌다) ·
> `after`(최소 경과) · `within`(최대 허용 간격, 넘으면 실패).

시장 시계는 execution table이 가진 모든 timestamp다(§3). 결정 이후 첫 번째 점이 곧 다음 분이고, 일별
테이블에서는 다음 날의 행이다. `SAME_DAY`와 `NEXT_ELIGIBLE`의 차이 — *"놓쳤을 때 다음 날로 넘기나"* — 는
`within`이 흡수하고, *"오늘 15:20이냐 내일 15:20이냐"*는 "결정 이후 첫 번째"가 자동으로 가른다.

---

## 무엇이 어떻게 바뀌었는가

### 선언

```yaml
execution:
  dataset: krx-daily
  trade_price: close      # 어느 가격으로 — 시각 선택이 아니므로 fill 밖으로 올라왔다
  fill:                   # 선택.  없으면 "결정 이후 첫 execution instant"
    at: "15:30"           #   run 의 timezone 으로 읽은 벽시계가 이것인 instant 만
    # after: "10m"        #   결정으로부터 최소 이만큼 뒤
    # within: "1d"        #   결정으로부터 최대 이만큼 안.  없으면 preflight 가 거절
```

`selector`·fill의 `timezone`·fill 안의 `trade_price`는 사라졌다. 로더가 셋 중 하나를 만나면 어디로
갔는지 한 문장으로 거절한다 (M4와 같은 결정: 옛 spelling을 조용히 옮기면 뜻이 바뀐다 — `same_day`는
`within`보다 엄격했고 `next_eligible`은 아무 제한도 없었다). `after`/`within`은 `agenda.every`와 같은
문법 `10m`·`2h`·`1d`이고, `after > within`이면 어떤 instant도 만족할 수 없으므로 선언에서 거절한다.

### 도메인: `FillRule`

`exchange/conventions.py`가 다시 쓰였다. `FillConvention`·`FillSelector`·`resolve_local_target`·
`validate_calendar`·fold/offset 증명이 전부 나갔고 `FillRule(trade_price, timezone, at, after, within)`
하나가 남았다.

```
후보   = horizon 에서 결정보다 엄격히 뒤인 instant 들 (bisect, 재스캔 없음)
after  → 결정 + after 보다 앞선 후보를 건너뛴다
within → 결정 + within (그리고 run end) 을 넘는 첫 후보에서 None
at     → run timezone 으로 읽은 벽시계가 at 이 아닌 후보를 건너뛴다
target = 남은 첫 후보
```

**fold/offset 증명이 사라진 이유가 이 변경의 핵심이다.** 옛 convention은 벽시계로부터 instant를
**구성**했으므로 그 벽시계가 그날 존재하는지·두 번 오는지 증명해야 했다. 새 규칙은 테이블의 **실재하는
instant를 거른다.** 가을 DST의 01:30은 두 개의 instant고, 결정 뒤의 첫 것이 이긴다 — 결정적이고
선언할 것이 없다. 봄 DST의 02:30은 아무 instant도 안 맞고, 다음 날의 02:30이 잡힌다. 새 테스트 둘이
그것을 고정한다.

### 판정과 preflight

- `_validate_execution_targets`(preflight)는 그대로 "모든 occurrence에 target이 있는가"를 묻고,
  observed가 `selector=...` 대신 `fill=<규칙 문장>`을 싣는다.
- `_judge_execution_ordering`(`check`)이 **테이블에게 묻는다.** 옛 판정은 occurrence의 벽시계와 fill의
  벽시계를 비교했다(`local_time >= fill_at`). 새 판정은 horizon을 한 번 읽고 occurrence마다
  `select_target`이 `None`인지 본다 — 코드 `execution.not_after_decision`은 유지, 뜻은 *"결정 뒤에 규칙이
  허락하는 시장 시계 점이 있는가"*. 하루 마지막 instant에 내린 결정에 `at`이 그 instant를 가리키면 다음
  날까지 없고, `within`이 그것을 막을 수 있다 — 옛 판정이 못 보던 경우다.

### 표면

```
project/run.py          RunExecution(dataset, trade_price, fill?) · RunFill(at?, after?, within?) · rule(timezone)
record (freeze.py)      execution.fill = {at, after, within, timezone, trade_price, declaration_identity}
registration.py         selector 의 closed-set 특별 처리 삭제.  run_invalid requirement 문장
public                  FillRule (FillConvention · FillSelector 퇴역).  ExactExecutionTarget 에서 selector 필드 삭제
cli/new.py              템플릿 fill 블록: trade_price 위로, at 하나와 after/within 주석
sample                  execution: {dataset, trade_price: close, fill: {at: CLOSE}}
tests/showcases         32개 파일 sweep (RunFill/FillConvention/dict/yaml 네 꼴)
```

### AC-1 — 매 분 판단·매 분 체결

`tests/acceptance/test_a_minute_strategy_fills_at_the_next_minute.py`: 09:00–09:10 1분 테이블, `agenda:
{every: 1m, from: 09:00, to: 09:05}`, **fill 블록 없음.** 여섯 결정이 매 분 내려지고 각각 **다음 분**에
체결된다(09:01 … 09:06). 첫 체결만 매수, 나머지는 `dealt_quantity: 0` — 동일 시각 우선순위(EXECUTE →
DECIDE)와 pending 교체 규칙은 이미 옳았다는 M0의 발견 그대로다. 옛 일별 종가 체결은 `fill: {at: "15:30"}`
으로 같은 결과를 낸다 (AC-2: showcase 6개의 테이블 digest가 그대로다 — 아래 검증).

---

## 무엇을 잃었나

- `FillSelector`·`FillConvention`·fold/offset. `LocalInstantDeclaration`의 fold/offset은 agenda 쪽에
  그대로 있다 — 그쪽은 벽시계로부터 instant를 **만들기** 때문에 증명이 필요하다. 체결 쪽은 이제 만들지
  않는다.
- `tests/exchange/test_fill_convention.py`의 DST 증명 테스트 둘 → "두 번 오는 벽시계는 두 후보" · "없는
  벽시계는 다음 날"로 교체.
- `tests/cli/test_a_closed_set_refusal_names_the_set.py`와 `test_agent_surface`의 selector closed-set
  사례 → 계좌 mode로 재지정 (closed-set 거절의 모양을 두 키에서 증명한다는 목적은 그대로).

---

## 검증

```
uv run python -m pytest tests/ -q -m ""       1642 passed  (신규 8: FillRule 7 · AC-1 acceptance 1)
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
scripts/showcase_record_digest.py --check      60/81 changed → 원인 확인 후 다시 잡음 → 81/81
```

**digest 60건은 M2와 같은 한 열이다.** strategy run 넷(005·006·007·008)의 `run.json`과 모든 테이블,
행·열은 같고 digest만. `FrozenRun.identity`가 fill 선언(`declaration_identity`)을 접으므로 `run_id`
열이 움직였다. datamodel showcase(002·004)는 fill이 없어 한 건도 안 움직였다.

**AC-2를 M2식 추론으로 끝내지 않았다.** M4 커밋을 임시 worktree(`git worktree add … HEAD`)에
꺼내 `show_005`를 다시 돌리고, 현재 출력과 **`run_id` 열을 뺀 채** 테이블 넷(`vqapr.account` 126행 ·
`vqapr.fill` 105행 · `vqapr.weight` 105행 · `alpha.signal` 105행)을 논리 digest로 비교했다 — **넷 다
동일.** `run.json`에서 다른 키는 `declared_digest`와 `execution`(fill 블록의 모양) 둘뿐. 옛
`same_day at 15:30`과 새 `at: "15:30"`은 일별 격자에서 같은 체결을 낸다. 그 뒤 기준선을 다시 잡았다.

**첫 스위트에서 3건이 떨어졌다**: 손상된 execution table 앞에서 두 agenda 의존 판정이 다른 이유로
막혔던 것(ordering 판정이 horizon을 agenda보다 먼저 읽었다 — agenda를 먼저 묻게 순서를 바꿨다), spoken
문장의 단어(`same_day` → `first execution instant`), 그리고 sweep이 은퇴 섹션 테스트의 yaml
한 줄까지 고쳐 버린 것.

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **`within: 1d`는 옛 `same_day`가 아니다.** 16:00의 결정에서 다음 날 15:30까지는 23.5시간 — `1d` 안이다.
  옛 `same_day`를 정확히 원하면 `within`을 하루보다 짧게(예: `12h`) 준다. 테스트의 첫 판이 여기서
  틀렸고, 그 사실 자체를 테스트 주석으로 남겼다.
- **모듈 통째 재작성 뒤 슬라이스 편집은 위험하다.** `RunFill`부터 `_naive_wall_time`까지를 잘라 새
  블록으로 바꾸다 M4가 그 사이에 넣은 `RunAgenda`를 함께 지웠다. ruff의 F821이 잡았고 `git show HEAD:`
  에서 복원했다. 두 마커 사이를 바꿀 때는 그 사이에 다른 것이 없는지 먼저 센다.
- **sweep은 이번엔 한 번에 됐다** — M4의 교훈(자기 들여쓰기 층, 형제 키로 fill 판별)을 그대로 썼고,
  지워진 줄에 `fill`/`trade_price`/`selector`가 0인지로 감사했다.

---

## 다음 기록이 이어받을 것

- **Stage 1이 끝났다.** 선언과 preflight가 설계 §2–§3·§6.2–6.3을 말한다. Stage 2(M6·M7)는 척추다:
  시장 시계를 1급으로 — `PendingValuation` 제거, VALUATION을 시장 시계의 단계로, 단계 순서
  ACCRUE → EXECUTE → VALUATION → COMPLIANCE → DECIDE 고정.
- `ExecutionHorizon`은 이제 instant 튜플과 `after()` 하나다. M6에서 시장 시계 자체가 되기에 딱 맞는
  크기다.
- `judgments._judge_execution_ordering`이 `bound_execution_table`을 import한다 — judgments →
  preflight 방향은 이미 있던 의존이라 층 위반은 아니지만, M12(`Prepared*` 통합)에서 두 모듈의 경계를
  다시 볼 때 함께 본다.
