# Issue ledger — 상태 한 줄씩

**작성 2026-09-02 · 갱신 2026-09-04.** 이 디렉터리에 86개 파일이 있고 **75개가 닫혔다.** 닫힌 파일을 옮기지 않는
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

## 1. 열린 것 — 열하나 (`023`·`027` + 실환경 아홉 `078`~`086`)

| # | 제목 | 상태 (2026-09-03 재확인) | 어디로 가는가 |
|---|---|---|---|
| `023` | 하나의 digest가 그 아래에서 바뀔 수 있는 파일을 기술한다 | **절반 열림.** docs 절반은 `fix/023-narrow-the-provenance-promise`가 닫았다. 코드 절반(`show run`의 `matches`/`differs` 읽기)은 HELD — gate가 되면 `009`의 결정을 뒤집는다 | 명사 3 (Run record) |
| `027` | 아무것도 convention을 소리 내어 말하게 하지 않는다 | **REOPENED 2026-08-31 by owner.** `register`가 point-in-time convention을 묻게 해야 한다. `034`는 record `139`로 닫혔다(기록 쪽); 선언 시점에 묻는 쪽은 남아 있다 | 남은 절반 |

### 실환경 세션이 낸 아홉 (2026-09-04, `0.4.1` wheel) — 전부 열려 있다

`kwam-enhanced-index/vqapr-enhanced-index-3/VQAPR-ISSUES.md`(A~C절). 계약만 들고 `0.4.1` 위에
디렉터리를 다시 세우고, 알파 30개를 만들고, 그중 다섯을 앙상블해 비용이 붙는 venue에서 북 3개를
돌린 세션이다. **testbed가 아니라 실제 작업**이라 결함을 일부러 재현하지 않았고, 그래서 여기 있는
것은 전부 일하다 부딪힌 것이다. 아홉 전부 2026-09-04에 이 브랜치 소스에서 확인했고, `078`·`079`는
여기서 재현까지 했다. 접수 표시는 그쪽 `VQAPR-ISSUES.md` 각 항목에 남겼다.

**셋(`078`·`079`·`083`)이 같은 모양이다 — 진단이 검사한 적 없는 원인을 단정한다.** `077`이 판정
층에서 닫은 것과 같은 결함이고, 그 파일의 규칙("원인을 모르면 지어내지 말 것")이 아직 메시지 층
전체에는 적용되지 않았다는 증거다.

| # | 제목 | 무게 | 실환경 |
|---|---|---|---|
| `078` | 지불 가능 수량 추정이 **category-driven venue가 쓰지 말라고 안내받은 채널**에서 비용을 읽고, 안 맞으면 venue를 탓한다 | **가장 무겁다.** `terms_by_kind`를 쓴 venue는 큰 주문을 발주하지 못한다. 우회(정수주)는 우연히 맞았을 뿐이고 가격이 싸지면 다시 거부된다. 올바른 철자가 `krx.py:452`에 이미 있다 — `013`의 재발 | C4 |
| `079` | materialized dataset의 schema가 **첫 세션이 추론한 것**이고, 거부는 다른 것을 지목한다 | 무겁다. `Decimal`을 내보내는 DataModel은 세션마다 precision이 달라져 중간에 죽고, `fix`대로 해도 안 고쳐진다 | A1 |
| `080` | 크래시한 datamodel run이 **아무도 열거하지 않고 아무도 지우지 못하는** record 디렉터리를 남긴다 | `074`가 strategy에 준 것을 datamodel은 못 받았다. skill이 광고하는 "디렉터리를 세라"가 그래서 틀린 수를 준다 | A5 |
| `081` | run 정의를 withdraw하면 그 record를 **열거하는 명령이 없어진다** | `rm run`이 요구하는 id를 기억으로만 댈 수 있는 상태로 거부들이 안내한다. `run_ids()`는 이미 있다 | B1 |
| `082` | "이 dataset을 읽는 게 누구인가"에 답하는 것이 없고, dataset이 자기를 만든 run을 대지 못한다 | 실측 36.3초/질문. 등록 시점에 `inputs()`를 평가하므로 정보는 이미 있다 | B2 |
| `083` | `show model`은 component 세 종류를 읽는데 거부는 하나만 댄다 — 게다가 `unhandled` | 메시지 한 줄이 가장 유용한 조회 verb를 안 쓰게 만든다. 바로 옆에 구조화된 거부가 이미 있다 | B3 |
| `084` | run 정의는 재등록이 거부되는데, **거부도 skill도 그것을 가능케 하는 verb를 대지 않는다** | `rm run-definition` 후 재등록이 답인데 `fix`의 선택지에 없다. `_merge_keyed`가 record `139`보다 오래됐다 | C1 (+A4) |
| `085` | fill 요약이 reason은 세고 instrument는 안 센다 — **한 번도 체결 안 된 종목이 안 보인다** | `039`의 다른 축. 20% 슬리브가 82번 전부 미체결이었는데 요약은 `ok: true` | C5 |
| `086` | constraint에 허용오차가 없어 양자화 잔여가 위반으로 잡히고, `fix`는 bound를 넓히라고 한다 | shipped `single_name_cap`과 scaffold 둘 다 해당. 진짜 위반(4.89%p)과 같은 카운터에 섞인다 | C6 |

파일로 만들지 않은 것: A2(`store_root`가 JSON에서는 문자열인데 `strategy_refs`는 `Path`를 요구한다
— skill 문구 한 줄, 보고자 본인이 결함에서 내렸다); A3(0.3.0 대비 실측 개선과 **숫자가 그대로
재현된다**는 확인 — `annual-fundamentals` 1,193초→6.2초, factor book 6개가 한 run `--jobs 6`으로
141초, SMB/HML/CMA와 RMRF 상관까지 0.3.0 수치와 일치); B4·C2·C3(잘 돼 있다는 기록 — `rm`의 참조
거부, `check.lookback.uncovered`가 답을 그대로 들고 있는 것, `terms_by_kind`+roster가 문서대로
동작하는 것). A4는 `084`의 뒷절로 들어갔다.

`086`을 쓸 수 있게 하려고 `authoring.py`와 `constraints/findings.py`의 `docs/issues/086` 인용
두 곳을 `docs/implementations/086`으로 고쳤다 — 원래부터 오타였고(이 디렉터리에 `086`은 없었다),
그대로 두면 새 파일과 충돌한다.

### 시나리오 testbed run 4가 낸 넷 (2026-09-04, `0.4.0` wheel — 논문 재현 완주) — 전부 닫혔다

같은 testbed에서 네 번째 에이전트가 **같은 고정 명세**(FF residual arm, `K ∈ {0,1,3,5}` × {OU+Thresh,
Fourier+FFN})를 `vqapr-0.4.0` wheel(`0d6e6d59`, record `149` 이전 빌드)로 **끝까지 수행**하며 적은
`FINDINGS.md` F-001~F-011. 소스 확인 2026-09-04, 이 브랜치 기준. `blocked`가 처음으로 하나 나왔다(F-009).
F-001은 record `149`가 이미 닫았고(skill `remove` → `rm`), F-003·F-011은 `No`, F-005·F-010은 `071`에
두 번째 증거로 붙였다(F-010은 run 3 F-018과 같은 거절의 재발). 접수 표시는 그쪽 `FINDINGS.md` 각 항목에
남겼다. **`073`·`074`는 `071`과 함께 record `150`이 2026-09-04에 한 브랜치
(`fix/073-the-run-reports-per-strategy`)로 닫았다** — 워커의 거절이 outcome으로 돌아오고, run은 전략마다
status를 보고하며 한 전략의 거절이 나머지를 멈추지 않고, `list strategies --run`이 진행 중 전략을 보여준다.

| # | 제목 | 상태 | kind | testbed |
|---|---|---|---|---|
| `075` | 신호가 정한 대로 나뉜 signed book은 `Rebalance.of`로 못 만들고, 직접 생성은 docstring 셋을 조립해야 한다 | **닫힘 2026-09-04 — record `154`.** `Rebalance.signed(weights, *, gross=1)`가 부호 있는 가중치를 받아 long/short 비율을 신호가 정한 대로 둔다(`gross=2`가 교과서 $1/$1). `of`는 `rescale`을 부르고, 그 결과 gross가 정확해졌다 — 전엔 short 쪽 잔차가 long 이름에 얹혔다. `Budget`·`Rebalance` docstring과 skill이 값을 댄다 | docs/API | F-002 (+F-010 원인) |
| `076` | preflight가 fresh instance의 payload를 왕복시키는데 docstring도 거절도 그것을 말하지 않는다 | **닫힘 2026-09-04 — record `152`.** 세 단계가 각자 이름을 대고(`save_payload on a fresh instance` / `load_payload of those bytes on a second fresh instance` / `save_payload again`), `preflight_refusal`이 `__cause__` 사슬을 `observed`에 싣고, `run`이 preflight `ValueError`를 `check`의 stage·code로 낸다(`unhandled` 아님). docstring 둘과 skill이 왕복을 말한다 | message/docs | F-004 |

### 시나리오 testbed run 3이 낸 둘 (2026-09-04, `0.3.0`에서 관측, `0.4.0`에서 코드 동일) — 전부 닫혔다

같은 testbed에서 세 번째 에이전트가 **고정 명세**(외부 참조 구현과 대조하기 위한 FF residual arm,
`K ∈ {0,1,3,5}` × 두 정책)를 수행하며 적은 `FINDINGS.md` F-018~F-020. 소스 확인 2026-09-04.
F-019는 에이전트 본인의 실수(`No`)라 단독으로 접수하지 않고 `072`의 두 번째 증거로 넣었다.
**`071`은 record `150`이 닫았다**(거절이 값·경계·전략·사용자 프레임을 댄다; 한 전략의 거절이 run을
멈추지 않는다). 남은 signed-book 절반은 `075`다.

| # | 제목 | 상태 | kind | testbed |
|---|---|---|---|---|
| `072` | panel window에 cross-section accessor가 없어 `latest()`가 낡은 행을 현재 행으로 승격시킨다 | **닫힘 2026-09-04 — record `151`.** `PanelWindow.current()`가 마지막 instant의 단면(행 없는 이름은 부재); `latest()`는 뜻을 지키고 docstring이 그것을 말한다; skill·scaffold·`read()` docstring 셋이 둘을 구분한다 | docs/API | F-020 (+F-019) |

이 둘은 **vqapr 안에서는 보이지 않는다**는 성질을 공유한다. 관련된 값이 전부 결정 시점에 합법적으로
가용했으므로 point-in-time 검사가 울릴 수 없고, 둘 다 외부 명세가 요구한
*가중치×수익률 대 패키지 자체 회계* 대조에서만 잡혔다. 접수 표시는 testbed의 `FINDINGS.md`가 아니라
여기에만 있다 — 그 파일은 run 4 스테이징 때 초기화되었고, 사본은
`kaist-thesis/docs/handoff/2026-09-04-vqapr-testbed-run3-findings.md`에 있다.

### 시나리오 testbed run 2가 낸 열둘 (2026-09-03, `0.3.0` wheel) — 전부 닫혔다

`kaist-thesis/vqapr-scenario-testbed/`에서 첫 사용자 에이전트가 논문의 FF5+MOM residual arm을 끝까지
수행하며 적은 `FINDINGS.md` 14건 중 소스에서 확인된 12건. 접수 표시는 그쪽 `FINDINGS.md` 각 항목에
남겼다. `blocked`는 없었다. **가장 무거운 셋은 `055`·`059`·`061`이었고, `061`은 record `143`이, `059`는
record `148`이 닫았다.** `064`는 2026-09-04 소유자가 **won't fix**로 닫았다 — 종가 데이터로 그 종가에
거래하는 것은 forward-looking이고, 체결이 콜백보다 strictly 늦어야 한다는 규칙이 프레임워크의 의도다.
**나머지 아홉(`055`·`056`·`057`·`060`·`062`·`063`·`066`·`067`·`068`)은 record `149`가 2026-09-04에
한 브랜치(`fix/0.4.0-open-issues`)로 닫았고, `065`는 docs 절반을 같은 record가, 설계 절반을 2026-09-04 소유자 판정이 닫았다.**

| # | 제목 | 종류 | FINDINGS |
|---|---|---|---|
| `065` | `inputs()`가 `initial_model_memory` 전에 불리는데 아무도 말하지 않는다 — **닫힘.** docs 절반은 record `149`, 설계 절반은 2026-09-04 소유자 판정(한 모양 캠페인 A1): **전략 하나 = 파일 하나.** 상수만 달라도 새 파일이며, 같은 파일의 재등록은 기록에 tuning으로 읽힌다. config 채널은 만들지 않는다 | design | F-014 |

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

## 2. 닫힌 것 — 일흔둘

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
| `055` `056` `057` `060` `062` `063` `066` `067` `068` `069` `070` | **record `149`, 2026-09-04, 한 브랜치.** skill이 코드를 따라간다(`062`·`067`), scaffold alias가 dataset을 따른다(`063`), 미등록 dataset은 한 번만 보고(`056`), 없는 record는 이름을 대며 거절(`057`), 모든 envelope에 `workspace_root`와 상위 workspace 발견 시 거절(`066`), `show model`은 모델의 선언을 읽는다(`055`), `vqapr rm dataset`(`060`), 파생 agenda는 날짜로 먼저 자르고 명령당 한 번(`069`), `run`은 workspace를 한 번 연다(`070`), snapshot은 Arrow이고 기록에 `timing` 블록(`068`) |
| `072` | record `151` — `PanelWindow.current()`, 한 모양 캠페인 Step 1 |
| `075` | record `154` — signed book이 신호대로 나뉜다(`Rebalance.signed`), `of`는 `rescale`을 부른다, 한 모양 캠페인 Step 3 |
| `077` | record `153` — 답하지 못한 판정은 통과가 아니다(agenda는 호출로, `datasets`는 멤버당 판정, helper의 `try` 다섯 제거), 한 모양 캠페인 Step 2b |
| `076` | record `152` — preflight 거절 문 하나(단계 이름·`__cause__` 사슬·`run`도 `check`의 stage), 한 모양 캠페인 Step 2 |
| `065` | docs 절반 record `149`; 설계 절반 **2026-09-04 소유자 판정 — 전략 하나 = 파일 하나**, config 채널 없음 (한 모양 캠페인 A1) |
| `064` | **CLOSED 2026-09-04 — WON'T FIX, 소유자 판정.** 종가 데이터로 그 종가에 거래하는 것은 look-ahead다. 체결은 콜백보다 strictly 늦다는 규칙이 의도이며 `same_close`는 만들지 않는다. 다시 열지 말 것 |
| `071` `073` `074` | **record `150`, 2026-09-04, 한 브랜치.** `Rebalance` 거절 다섯이 값과 경계를 댄다(`071`); `SimulationFailure`가 `component_id`와 저자 파일의 프레임(`source.file`/`line`, `key_path: strategies.<id>`)을 든다(`071`); `--jobs` 워커는 예외 대신 `StrategyOutcome`을 돌려주고 `run`은 전략마다 outcome을 내며 한 전략의 거절이 나머지를 멈추지 않는다 — envelope는 `ok:false`, `stage: run.strategy_failed`, 전략별 `status`(`073`); `list strategies --run`이 record 없는 디렉터리를 `running`/`unfinished`로 `chunks`·`last_event_time`·`lock.refreshed_ago`와 함께 보여주고 skill에 "Watching a long run"이 있다(`074`) |

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
