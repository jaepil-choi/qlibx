# 267 — strategy scaffold가 에이전트가 찾아보던 부품을 제자리에 전부 보인다

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 한 읽기 (`redesign/one-reading`), M4 — 계획 `.agent/plans/active/one-reading-campaign.md` |
| **이슈** | `docs/issues/report-2026-09-11-feature-request-copyable-strategy-recipes-shipped-with-the-package.md` (대체), `docs/issues/report-2026-09-11-adding-one-strategy-to-an-existing-workspace-still-costs-agents-more-than-a-pandas-project.md`, `docs/issues/report-2026-09-11-a-decide-after-close-strategy-cannot-log-its-last-fill-from-a-callback.md` |
| **설계 근거** | 오너 판정 2026-09-11 — "`--recipe`는 반대, `new` 했을 때 template이 자세하게 주석이 달려 나오면 된다" |
| **브랜치** | `redesign/one-reading` |
| **앞선 기록** | Step 7(AC-A1: scaffold 40줄 천장), `215`(opening memory `{}`), `251`(calendar 창) |

---

## 왜 이 변경이 있는가

기존 workspace에 전략 하나를 더하는 A/B에서 vqapr 쪽 비용이 pandas의 1.8배(opus) · 3.8배(sonnet)였고, 그 차이의 대부분이
authoring API를 손으로 읽는 데 갔다(B-1 pydoc 84 KB, B-2 `help()` 41 KB). 두 에이전트 다 `vqapr new strategy`를 돌리고
파일을 버렸다. scaffold가 읽기 하나와 `Rebalance` 하나만 보이고, 나머지는 끝의 주석 두 줄("state는 `self.memory`에",
"표는 `tables()`에 선언")로만 가리켰기 때문이다. 대화 기록으로 확인한 조회는:

- 자기 표에 쓰기(`self.recorder.append`) — B-1 25 KB, B-2 12 KB. B-2는 `call.recorder`라고 썼다가 run이 죽었고,
  그 반쯤 쓰인 record가 나중에 exporter에서 "strategy record가 둘"로 다시 나왔다.
- 상태 들고 다니기(`self.memory`), 두 번째 데이터셋, bool 필드는 `.current()`(B-3은 `matrix()`에서 거절).
- 체결 가격을 콜백에서 기록하다 마지막 날의 체결을 잃음(B-2, 6행).

testbed는 복사할 레시피 네 개와 `new strategy --recipe`를 요청했다. 오너는 그것을 문 두 개로 보고 거절했다: 같은 필요를
`new strategy`와 `--recipe`가 나눠 갖고, 레시피 절반은 전략 코드가 아니다(시계는 run 선언의 것, 체결가 조인은 export의
것). scaffold가 이미 "계약에서 생성되고 · 테스트되고 · 그대로 돈다"를 가지므로, 그 한 파일에 이름표를 붙인다.

## 무엇이 어떻게 바뀌었는가

`extension/scaffold.py::_STRATEGY_TEMPLATE` (rows·calendar 두 flavour 모두):

| 부품 | 형태 | 이유 |
|---|---|---|
| 두 번째 데이터셋 | `inputs()` 안의 주석 예시 + `.current()`(이름 → 값, bool 포함)와 `matrix()`(숫자 창)의 구분 | 두 번째 dataset id가 있어야 돌므로 주석 |
| 자기 표 | `DECISIONS = "decisions"`, `tables()`가 `va.TableSpec(DECISIONS, ("instrument", "action", "score"))`, `decide()`가 `self.recorder.append` | 실제 코드 — "그대로 돈다" 테스트가 검증 |
| 상태 | `self.memory["held"]`로 지난 결정의 종목을 들고, 그 차집합(`held ^ chosen`)으로 `enter`·`exit`를 기록 | 실제 코드. `Hold` 앞이 아니라 뒤 — `Hold`는 책을 그대로 두므로 그때 `exit`를 쓰면 틀린다 |
| 체결 사실 | "결정을 기록하라. 가격·수량·비용은 `vqapr.fill`(export의 fills.csv); 체결은 콜백 뒤에 오고 마지막 체결 뒤엔 콜백이 없다" | last-fill 피드백 |

- `authoring/context.py::StrategyModelContext.__getattr__`: 없는 이름에만 불린다. `recorder` · `memory` · `tables`면
  "`self.<name>`을 decide() 안에서 쓰라"고, 그 외에는 원래 문장으로 `AttributeError`.
- skill: make-strategy "Start from the scaffold"에 "pydoc 전에 emitted 파일을 읽어라"와 무엇이 어디 있는지, 결정과 체결의
  구분.

## 바꾸지 않은 것

신호(모멘텀 placeholder), 창의 선언과 guard, `Rebalance.of(long=..., invested=...)`, 기본 flavour의 줄들
(`test_the_rows_strategy_scaffold_is_what_it_always_was`). 0 비중은 다루지 않았다 — record `260`(다른 세션)의 판정 대상이다.
`vqapr new run`의 시계는 run 선언 쪽(record `259`)이다.

## 트레이드오프

AC-A1의 40줄 천장은 "ceremony가 사라졌다"의 증거였고, 이 변경으로 파일은 62줄(rows) · 70줄(calendar)이 된다. 천장의
뜻을 지켜 **코드 줄**을 센다: rows 37줄(≤ 40 그대로), 파일 전체는 ≤ 80으로 따로 묶어 이름표가 매뉴얼로 자라지 않게
한다. 두 테스트(`test_authoring_contract.py`, `test_scaffold_runs_unedited.py`)가 그렇게 바뀌었다.

scaffold가 표 하나를 기본으로 쓰므로, scaffold 그대로 돈 run의 record에 `decisions` 표가 생긴다(`vqapr export`는
`tables/decisions.csv`로 쓴다). 저자가 필요 없으면 `tables()`와 기록 몇 줄을 지우면 된다.

run 밖에서 `decide()`를 손으로 부르는 코드는 이제 run이 하는 두 가지를 먼저 해야 한다: `memory = {}`(record `215`의
opening memory)와 `tables()`로 만든 `InvocationRecorder`. 이전 scaffold는 둘 다 쓰지 않아서 `None`인 채로 돌았다.
scaffold에 `None` 방어를 넣는 대신 테스트가 run과 같이 준비하게 했다 — 방어 코드는 저자에게 ceremony로 읽힌다.

## 검증

| 검사 | 결과 |
|---|---|
| `tests/extension/test_authoring_contract.py` | 코드 37줄 ≤ 40, 파일 ≤ 80; banned 토큰 없음; `call.recorder`·`call.memory`가 `self.`를 말하고 다른 이름은 원래 문장 |
| `tests/extension/test_scaffold_runs_unedited.py` (slow) | 수정 없이 register · check · run, 체결; 그리고 `show strategy scaffold/alpha --table decisions`가 행을 돌려주고 `action`은 `enter`/`exit`뿐 |
| `tests/cli/test_export_writes_a_record_as_files.py` | CLI fixture run의 export에 `tables/decisions.csv`, 행 하나: A `enter` |
| rows · calendar 두 flavour | `compile` 통과; 코드 37 · 42줄, 전체 62 · 70줄 |
| `tests/extension/test_scaffold_runs_on_real_dtypes.py` (두 strategy 테스트) | `_prime_like_the_run`(memory `{}` + recorder)으로 run처럼 준비; calendar 쪽은 결정 뒤 `memory == {"held": ["A", "B"]}` |
| `tests/extension/test_the_scaffold_offers_both_lookbacks.py` | calendar scaffold에 `RowsLookback`이 없다 — 두 번째 읽기 예시는 `lookback=<as above>` |
| `tests/cli/test_commands.py::test_show_strategy_reads_back_the_tables_a_run_recorded` | 기록된 표에 `decisions` |
| `uv run ruff check`, `uv run python -m pyright` (scaffold · context) | 통과, 0 errors |
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1778 통과, 5 skip (409.3 s). 첫 시도의 여섯 실패 중 넷은 위 세 테스트, 하나(`test_concurrent_force_runs_never_blend_two_runs_into_one_record`)는 부하 중 경합으로 단독 재실행에서 통과, 하나(`show_004`)는 worktree에 없는 gitignored `data/DW` — main checkout의 것을 junction으로 잇고 통과 |
