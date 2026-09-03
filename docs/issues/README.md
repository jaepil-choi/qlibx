# Issue ledger — 상태 한 줄씩

**작성 2026-09-02 · 갱신 2026-09-03.** 이 디렉터리에 68개 파일이 있고 **54개가 닫혔다.** 닫힌 파일을 옮기지 않는
이유는 `src/`의 docstring 103곳과 `docs/`의 154곳이 이 번호들을 **결정의 근거**로 인용하기
때문이다 — 경로를 바꾸면 그 인용이 전부 끊긴다. 대신 이 파일이 색인이다.

**읽는 법.** 열린 것만 보려면 §1을 읽는다. §2는 닫힌 것들이고, 무엇이 닫았는지만 적는다.
각 파일 안의 `**Status:**` 줄이 여전히 authority이며, 이 표는 그것을 모은 것이다.

> **이 디렉터리는 이슈 목록으로 닫히지 않았다.** 세 개의 명사(**Panel · Surface · Run**)가
> 캠페인으로 들어왔다 — records `133`(Surface), `137`(Panel), `139`(Run). 그 설계는
> `docs/design/the-panel-the-surface-and-the-run.md`에 있고,
> `docs/vqapr-architecture.md` §17이 그것을 소유자 mental model과 대조한다. **하나씩 닫으면
> 다섯 번 고치고 다섯 번 다시 열린다.**

---

## 1. 열린 것 — 열넷

| # | 제목 | 상태 (2026-09-03 재확인) | 어디로 가는가 |
|---|---|---|---|
| `023` | 하나의 digest가 그 아래에서 바뀔 수 있는 파일을 기술한다 | **절반 열림.** docs 절반은 `fix/023-narrow-the-provenance-promise`가 닫았다. 코드 절반(`show run`의 `matches`/`differs` 읽기)은 HELD — gate가 되면 `009`의 결정을 뒤집는다 | 명사 3 (Run record) |
| `027` | 아무것도 convention을 소리 내어 말하게 하지 않는다 | **REOPENED 2026-08-31 by owner.** `register`가 point-in-time convention을 묻게 해야 한다. `034`는 record `139`로 닫혔다(기록 쪽); 선언 시점에 묻는 쪽은 남아 있다 | 남은 절반 |

### 시나리오 testbed run 2가 낸 열둘 (2026-09-03, `0.3.0` wheel)

`kaist-thesis/vqapr-scenario-testbed/`에서 첫 사용자 에이전트가 논문의 FF5+MOM residual arm을 끝까지
수행하며 적은 `FINDINGS.md` 14건 중 소스에서 확인된 12건. 접수 표시는 그쪽 `FINDINGS.md` 각 항목에
남겼다. `blocked`는 없었다. **가장 무거운 셋은 `055`·`059`·`061`이었고, `061`은 record `143`이, `059`는
record `148`이 닫았다.**

| # | 제목 | 종류 | FINDINGS |
|---|---|---|---|
| `055` | `show model`이 아무도 설정하지 않는 `_aliases`·`_authored_tables`를 읽어 `reads`가 항상 비고 `records`가 선언된 표를 안 싣는다 | code | F-005 |
| `056` | `check`가 미등록 dataset 하나를 field 수만큼 반복 보고한다 | message | F-006 |
| `057` | `read_strategy_table`이 help가 말하는 root와 signature가 허용하는 `strategy_ref=None`에 빈 iterator를 낸다 | code+docs | F-007, F-012 |
| `059` | 물질화가 모든 행과 access 기록을 끝까지 메모리에 들고, lineage가 evaluation마다 전 종목을 반복하며(478MB), 진행 출력이 없다 | code | F-009 |
| `060` | `rm`에 `dataset` kind가 없는데 skill은 삭제를 약속한다 (C4/E1의 남은 절반) | code | F-011 |
| `062` | `Hold(reason)` 규칙이 skill과 docstring에서 반대다 | docs | F-001 |
| `063` | strategy scaffold가 `--dataset`/`--field`를 받고도 alias `prices`와 momentum docstring을 낸다 | docs | F-002 |
| `064` | "종가에 종가 정보로 거래"를 말할 수 없고, template 예시는 한 세션 지연을 정답으로 적는다 (`027`·`033`의 축) | docs | F-010 |
| `065` | `inputs()`가 `initial_model_memory` 전에 불리는데 아무도 말하지 않는다; 한 클래스를 여러 id로 등록할 수 없다 | docs+design | F-014 |
| `066` | 하위 디렉터리의 `register`가 두 번째 workspace를 조용히 만들고, 거절문이 어느 workspace를 봤는지 말하지 않는다 | message | F-004 |
| `067` | skill은 편집한 component가 `register --force` 없이는 거절된다고 하는데, 그 flag는 없고 plain re-register가 말없이 교체한다 (`025`·`030`의 축) | docs+message | F-017 |
| `068` | 세션당 package 시간 0.25s, 대부분 Python 행으로 fetch하는 execution snapshot 둘; run 결과에 phase별 시간이 없다 | code | F-016 |

파일로 만들지 않은 것: F-003(cp949 콘솔, 에이전트 환경); F-015(`values`가 접근마다 전 컬럼을 다시 만든다 —
`061`과 같은 뿌리, record `143`이 닫았다; 그 profile 수치는 `061` 파일에 붙였다). `027`에는 그 run의 비용
annotation이 붙었다. **Phase 2(`arb-k0k5`, 2×2 grid + profiling)까지 끝난 run이며 `blocked`는 끝까지 없었다.**

### 열린 아홉에 없는 것 — 아직 파일이 없는 실환경 발견

`kwam-enhanced-index/vqapr-enhanced-index-3/VQAPR-ISSUES.md`(2026-08-31, FF5+MOM 12 book + residual
2벌을 실제로 만든 세션)가 보고했고 **이 디렉터리에 대응 파일이 없는 것들**. 2026-09-02 평가에서
확인했다.

| 실환경 id | 무엇 | 확인 |
|---|---|---|
| A3 | 여러 항목을 담은 선언 파일의 등록이 **원자적이지 않다** | **닫힘 — record `134`.** 선언 문서 하나가 lock 하나·read 하나·write 하나다; k번째에서 거절되면 workspace는 byte-identical이고 테스트가 그것을 단언한다. (이전 진단:) `declarations.py::_apply`가 섹션마다 `Workspace.create(...).register_*()`를 따로 부르고, 각각이 자기 lock + read-modify-write를 돈다. k번째에서 실패하면 1..k-1은 남고, 등록은 immutable이므로 수정본을 다시 넣을 수 없다. **그 세션에서 가장 비쌌던 항목** |
| A4 | run 기록 **19GB / 12 run**, 끝날 때 한 번에 쓴다 | **닫힘 — record `135`.** (이전 진단:) `vqapr.account`가 valuation마다 보유 종목 전부를 JSONL 한 행씩. 실제로 읽히는 것은 `_ACCOUNT` 행 0.07% |
| A5 | 프레임워크가 **자기가 경고한 tz 함정에 빠지는 포맷으로** 출력을 낸다 | **닫힘 — record `135`.** (이전 진단:) JSONL run 기록을 `read_json_auto`로 읽으면 9시간 밀린 tz-aware 값이 나오고, 그 패널이 등록을 **통과한다** |
| A6 | 큰 run은 `vqapr show run`으로 읽을 수 없다 | **닫힘 — record `135`.** (이전 진단:) 26만~260만 행 JSON이 stdout으로. 문서화된 표면을 우회하게 되고, 그 우회가 A5를 만든다 |
| A7 | 등록이 id는 지키는데 그 id가 가리키는 **파일 내용**은 안 지킨다 | **닫힘 — record `139`.** `run.json`이 run이 읽은 source마다 parquet 바이트의 sha256을 든다. (이전 진단:) `023`의 이웃이지만 같지 않다 — `023`은 run record의 digest, 이것은 dataset 등록에 digest가 없다는 것 |
| C4 / E1 | 등록 취소가 없고, workspace에 소유권 개념이 없다 | **취소 절반 닫힘 — record `139`.** `vqapr rm <kind> <id>`가 `Workspace.remove()`를 부르고, `rm run`/`rm strategy`가 기록을 지운다. 소유권 개념은 없다 |
| C5 | `--out /dev/null`이 Windows에서 `nul.py`를 만든다 | papercut |
| B1 | `type()`으로 만든 StrategyModel이 `__module__ == 'abc'`가 되고 거절 메시지가 아무 데도 안 가리킨다 | papercut, 메시지 문제 |

---

## 2. 닫힌 것 — 쉰넷

| # | 닫은 것 |
|---|---|
| `001` | 문서 계약 정렬 (PRD·Architecture) |
| `002` | CLOSED 2026-08-29 |
| `003` | record `035` |
| `004` | CLOSED 2026-08-20 — owner: template은 통과해야 한다 |
| `005` | record `043` |
| `006` | CLOSED 2026-08-21 |
| `007` | SUPERSEDED by `008` |
| `008` | CLOSED 2026-08-28 |
| `009` | CLOSED 2026-08-28 — fingerprint는 gate가 아니라 receipt |
| `010` | record `066` |
| `011` | CLOSED 2026-08-29 — 아홉 항목 전부 |
| `012` | CLOSED 2026-08-29 |
| `013` | CLOSED 2026-08-29 |
| `014` | CLOSED 2026-08-29 |
| `015` | record `087` |
| `016` | record `088` |
| `017` | 양쪽 절반 다 |
| `018` | record `090` |
| `019` | record `089` |
| `020` | `fix/020-krx-is-long-only` |
| `021` | `fix/021-skill-names-public` |
| `022` | record `093` |
| `024` | record `094` |
| `025` | CLOSED |
| `026` | CLOSED |
| `028` | record `097` |
| `029` | record `098` |
| `030` | CLOSED 2026-09-01, 양쪽 항목 |
| `031` | CLOSED 2026-08-31 |
| `032` | CLOSED 2026-09-01 |
| `033` | CLOSED 2026-08-31 — **semantics 버그가 아니라 steering 버그로** 닫혔다. §15-6 / Panel 설계 §7-1이 그 축을 다시 연다 |
| `034` | record `139` — `run.json`이 execution input id와 fill 선언(selector·local time·timezone·trade price·identity)을 든다. 규약이 다른 두 run은 거기서 갈린다 |
| `035` | 전반 record `119`(읽기 경로는 검증하지 않는다), 후반 record `137`(panel grain은 run당 한 번 `Panel`로 물질화되고 읽기는 슬라이스; `read(alias, field)`가 2d 창을 준다) |
| `036` | records `126`·`128`·`130`·`131`·`132`·`133` — 세 역할이 class 하나씩, scaffold 셋이 한 문법, `_internal/`에 bridge 0. "Both are authored the same way"가 서술이 됐다 |
| `040` | record `138` — `strategy_configs`가 agenda가 아니라 strategy(component id)로 키잉된다; 한 agenda를 세 전략이 가리키고 셋 다 등록된다; 충돌은 한 전략이 agenda 둘을 대는 것이고 거절은 그 전략을 이름으로 댄다; 옛 shape 문서는 한 release 동안 읽히고 앞으로 쓰인다 |
| `037` | record `099` |
| `038` | record `123` |
| `039` | record `102` |
| `041` | record `102` |
| `042` | CLOSED 2026-08-31 |
| `043` | CLOSED 2026-09-01 (record `108`) |
| `044` | CLOSED 2026-09-01 (record `119`) |
| `045` | record `123` |
| `046` | 후반 record `120`(왕복 2→1), 전반 record `136`(alias 하나 = statement 하나; `declared_rows`의 Python join 삭제) |
| `047` | record `129` — 두 connection factory가 하나의 `_configure`를 지난다 |
| `048` | CLOSED 2026-09-01, docs-only |
| `049` | **CLOSED 2026-09-03** — 측정을 이 repo의 `experiments/exp_049_the_measurement/`가 잰다. rows 372.57s · expr(같은 long 파일, expression 필드) 5.04s · wide 2.46s, anti-join 0. rows/expr **73.9x**, rows/wide **151.5x** |
| `051` | record `130` — contract 블록이 monitoring 관측을 걷는다. 그 전엔 **모든 기록에서 비어 있었다** |
| `052` | CLOSED 2026-09-03 — showcase 여덟이 `tests/showcases/`의 slow 테스트로 `test_all`에 들어간다 (삭제 캠페인 Step 0, harness-only). `show_003`은 `data/DW`(repo 밖) 때문에 release 전 손으로 |
| `053` | record `141` — `InstantsLookback(n)`이 instant를 센다 (`dense_rank` over `available_at`, proof도 `DISTINCT` instant). `grain: rows`의 calendar window는 ruling 대기, 이슈 아님 |
| `054` | record `142` — 프레임워크가 만든 행은 `Observation._framework_row`로 검증 없이 생성. 저자가 손으로 만드는 것은 그대로 검증. 읽기 6.68s → 2.10s (80 names) |
| `061` | record `143` — `PanelWindow.values`가 lazy mapping; `latest()`·`counts()`는 Arrow에서. 창 하나가 컬럼 하나를 요청될 때만 변환 |
| `058` | record `146` — fill 행의 `event_time`도 전략 agenda의 zone으로; 기록 표가 parquet이라 zone이 파일에 실린다 |
| `050` | CLOSED 2026-09-01 |

---

## 3. 출하된 wheel과 develop이 갈린다

`kwam-enhanced-index/vqapr-final-testbed/KNOWN-ISSUES.md`는 **`0.2.0a2` wheel 기준**으로 열 개를
싣고 있고, 그 목록의 규칙은 *"the list must be exactly the open set"*이다. **2026-09-02 기준으로
그중 넷이 develop에서 이미 닫혔다** — `K-030`(=`030`), `K-032`(=`032`), `K-038`(=`038`),
`K-043`(=`043`).

그 파일 자신의 규칙대로라면 **닫힌 항목이 목록에 남아 있으면 진짜 finding을 억누른다.** 다음
testbed run 전에 wheel을 다시 빌드하고 `KNOWN-ISSUES.md`를 이 디렉터리에서 재생성해야 한다.

**2026-09-03: `0.3.0` wheel이 빌드됐다** (`dist/vqapr-0.3.0-py3-none-any.whl`, 캠페인 전체 포함).
`vqapr-final-testbed/` 디렉터리는 2026-09-03 기준 `kwam-enhanced-index/` 아래에 없다 — 그 testbed를
다시 세운다면 `KNOWN-ISSUES.md`는 이 파일의 §1(다섯)에서 다시 만든다. `vqapr-enhanced-index-3`은
`vqapr==0.2.0a2` wheel에 pin되어 있고, `0.3.0`은 그 프로젝트의 등록(grain)과 모델(`read(alias, field)` /
`rows(alias)`)을 전부 깨는 breaking release다 — 옮기는 것은 그 프로젝트의 몫이다.
