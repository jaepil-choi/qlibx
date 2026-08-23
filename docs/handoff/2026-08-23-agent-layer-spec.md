# Deep Interview Spec: vqapr framework-agent bridge

## Metadata
- Interview ID: vqapr-agent-layer-2026-08-23
- Rounds: 18 (+ Round 0 topology gate, + Restate gate)
- Final Ambiguity Score: 4.4%
- Type: brownfield
- Generated: 2026-08-23
- Threshold: 0.05
- Threshold Source: default
- Initial Context Summarized: no
- Status: PASSED
- Auto-Researched Rounds: none
- Auto-Answered Rounds: none
- Architect Failures: 0
- Lateral Reviews: 2 (Round 4 at initial->progress; Round 10 at progress->refined)
- Lateral Panel Failures: 0
- Refined Rounds: 2, 6
- Closure Overrides: none
- Restated Goal: vqapr에 framework-agent 다리를 놓는다 — CLI 동사 여섯과 측정된 마찰 수정 넷으로 미션 사다리 세 칸을 CLI만으로 통과 가능하게 하고, `collector()` 진입점에서 강제되는 stage/family 레지스트리와 `vqapr.descriptors`가 실패 어휘를 코드가 소유하게 하며, 매니페스트 기반 `vqapr skill install|remove|list`가 `.agents/skills/vqapr/`의 단일 원본과 `.claude/`의 얇은 adapter를 설치·감지·제거하고, SKILL.md 본문은 언제 쓰는지와 사다리 경로만 담고 상세는 `--help`·템플릿·생성된 카탈로그에 위임해서, vqapr를 처음 보는 agent가 소스를 읽지 않고 등록 → firm characteristics → factor return을 해내는지 vqapr-testbed에서 두 번의 spawn으로 측정할 수 있게 한다.

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.96 | 0.35 | 0.336 |
| Constraint Clarity | 0.95 | 0.25 | 0.238 |
| Success Criteria | 0.96 | 0.25 | 0.240 |
| Context Clarity | 0.95 | 0.15 | 0.143 |
| **Total Clarity** | | | **0.956** |
| **Ambiguity** | | | **0.044** |

## Topology

| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| cli-surface | active | 핵심 CLI 동사 집합과 agent 대상 발견 가능성 | 동사 6개 확정(R7), 마찰 수정 4건 포함(R8), 입력은 YAML spec(R14). Build Gate 1–7·13–14가 검증 |
| skill-cli | active | `vqapr skill install|remove|list` | target·adapter 구조(R6), 루트 자동 탐지(R6), 매니페스트 소유권(R12), 원본 sha stale 감지(R16). Build Gate 8–12가 검증 |
| skill-framework-bridge | active | SKILL.md 본문 — framework 조종 절 | 분할 규칙 확정(R9), usage/remedy 권한 분할(R13), mission A 문구 포함(R18). Build Gate 9–10 + Spawn Gate가 검증 |
| descriptors | active | stage/family 레지스트리와 생성 카탈로그 | R1 강도(R5), collector() 진입점 검증(R11), `vqapr.descriptors` + 설치 시점 렌더링(R17). Build Gate 7이 검증 |
| skill-user-bridge | **deferred** | SKILL.md 중 사용자 인터뷰 절 (PIT 설명, 데이터 읽고 후보 제시) | Round 3에서 사용자 확인 후 보류. framework-agent 계층이 1순위이며 인터뷰 지침은 다음 사이클. 확인 시각 2026-08-23T07:10:00Z |
| sample-journey | **deferred** | PRD §11.4 materialize 가능한 샘플 일습 | Round 3에서 사용자 확인 후 보류. `vqapr-testbed/`가 이미 4,962종목 실데이터로 fresh-agent 검증 무대 역할을 하므로 지금 만들면 검증 무대가 둘이 된다. 확인 시각 2026-08-23T07:10:00Z |

### Locked intent (Round 0, 전부 보존)

| ID | 상태 |
|---|---|
| `artifact:skill-md` | active — `.agents/skills/vqapr/SKILL.md` + `references/` |
| `artifact:framework-guide` | active — SKILL.md 본문의 framework 조종 절 |
| `artifact:interview-guide` | **deferred** — skill-user-bridge와 함께 보류 |
| `artifact:descriptors` | active — `vqapr.descriptors` + 렌더된 `references/stages.md` |
| `artifact:sample-journey` | **deferred** — sample-journey와 함께 보류 |
| `surface:skill-cli` | active — `vqapr skill <verb>` |
| `surface:core-cli` | active — 동사 6개 + help + 템플릿 + 실패 분류 |
| `integration:codex-target` | active — `.agents/skills/vqapr/SKILL.md` (full text) |
| `integration:claude-target` | active — `.claude/skills/vqapr-skill/SKILL.md` (adapter) |
| `constraint:no-instruction-files` | active — AGENTS.md·CLAUDE.md 불간섭 |
| `constraint:no-import` | active — `agent/`는 deterministic 경로에서 호출되지 않는다 |
| `constraint:no-drift` | active — 범위 축소됨. stage/family는 생성, reason code는 자유 |
| `constraint:idempotent` | active — 매니페스트 sha 기반 |
| `constraint:progressive-disclosure` | active — 본문은 언제 쓰는지 + 사다리만 |
| `constraint:no-auto-generate` | **deferred** — sample-journey 보류로 무효 |
| `constraint:skill-never-bypasses` | active — skill은 validation을 우회하거나 semantics를 추측하지 않는다 |

## Established Facts

| id | 사실 | 라운드 |
|---|---|---|
| f1-cli-boundary | CLI 경계는 workspace 선언 + 실행 + materialize/publish까지. IC·NAV·drawdown 등 분석은 Python public API에 남긴다 | 1 |
| f2-skill-cli-shape | skill 설치는 `vqapr skill <verb>`이며 instruction file은 수정하지 않는다 | 0 |
| f3-two-bridges | skill은 두 bridge를 담고 SKILL.md는 progressive disclosure 구조다 | 0 |
| f4-priority | 1순위는 framework-agent 계층. 사용자 인터뷰 가이드는 그 다음 | 2 |
| f5-verification-loop | 검증 루프는 qlibx 수정 → 버전 → testbed install → fresh agent spawn → mission 관찰이며 반복 가능해야 한다. 계측치는 FRICTION.md | 2 |
| f6-skill-copy-needs-update | 코드는 editable로 즉시 반영되지만 skill 리소스는 복사되므로 install/update를 다시 돌려야 한다 | 2 |
| f7-first-mission | 첫 mission은 registration에서 멈춘다 | 2 |
| f8-f001-blocked | FRICTION.md F-001이 `vqapr agent install` 부재를 blocked로 기록했고 근본 원인은 미구현 명령을 현재형으로 서술한 문서다 | 2 |

분쟁 중이거나 superseded된 사실 없음.

## Trigger Metadata

| Round | Trigger | 영향 | prior -> new | 증거 |
|---|---|---|---|---|
| 4 | **D scope expansion** | descriptors / constraints 0.50 -> 0.30 | 0.515 -> **0.535 ↑** | D2 선택으로 문서 산출물이던 컴포넌트가 프레임워크 리팩터를 포함하게 됐다. goal은 올랐으나 constraints가 더 크게 떨어져 순 상승 |
| 16 | **C scorer omission corrected** | descriptors / goal 0.92 -> 0.88 | 0.083 -> **0.094 ↑** | r15 채점이 카탈로그 산출물 형태 미정을 빠뜨렸다. 승인된 Build Gate 7번이 검증 불가능한 상태였음 |
| 17 | (16의 trigger 해소) | descriptors / goal 0.88 -> 0.95 | 0.094 -> 0.06 | F3 결정으로 해소 |

## Lateral Review Panel

**Round 4 — initial → progress.** researcher / contrarian / simplifier.
- **P1 (researcher + contrarian, 독립 합치):** arch §10.4의 "소스에서 생성해 drift를 구조적으로 불가능하게" 는 현 코드에서 성립하지 않는다. `FailureFamily`는 닫힌 enum 7개지만 code는 37개 콜사이트에서 f-string으로 조립되고 일부는 호출자 인자다. → Round 4·5에서 R1로 범위 축소.
- **P2 (contrarian):** 복사된 SKILL.md는 editable 의존에서 stale해지고, instruction file 없이 발견 가능성이 불확실하다. → Round 6에서 실측으로 절반 반증(kaist-thesis가 이미 양쪽 target을 쓴다), 절반은 adapter + 원본 sha로 해소(R6·R16).
- **P1 (simplifier):** `materialize`가 `_COMMANDS`에 없어 미션 2단계가 도달 불가 — 유일하게 우회로 없는 하드 블록. → Round 7 V2에 반영.

**Round 10 — progress → refined.** researcher / contrarian / simplifier / architect (system shape 변경으로 architect 추가).
- **P1 (contrarian):** 순환 참조. skill은 상세를 `--help`에 위임하는데 `cli/main.py` 독스트링은 CLI가 설명하는 것을 금지하고 skill을 가리킨다. `main.py:52`는 `add_parser(name)`으로 비어 있다. → Round 13에서 usage/remedy 분할로 해소.
- **P1 (contrarian):** "fresh agent가 사다리를 완주" 기준은 look-ahead 등록을 성공으로 채점한다. → Round 10에서 Spawn Gate 채택.
- **P1 (researcher):** `run` 전체 직렬화는 새 포맷 설계다 — `object` 타입 필드 셋과 해시 재증명 페이로드. 좁은 길: `final_state.recorder_rows`만. → Round 11 N1.
- **P1 (researcher):** `materialize` 종목 정합성이 어디서도 검사되지 않아 부분 불일치가 발행되고 exit 0. FRICTION.md에 `wrong` severity가 없어 기록 불가. → Round 10·11에서 둘 다 해소.
- **P1 (architect):** `envelope.py`가 내는 `cli.usage`·`unhandled`·성공 stage는 실패 레지스트리 바깥. `Failure.__post_init__` 검증은 typed failure를 `unhandled`로 뒤집는다. `scan.py` 7 + `preflight.py` 3은 인라인 리터럴. 판정 **WATCH**. → Round 11에서 collector() 진입점 검증으로 해소.
- **P2 (contrarian):** `agent install` → `skill install` 개명 시 README를 안 고치면 F-001이 글자 그대로 재발. → Round 13 (iii).
- **P2 (contrarian):** 넷을 한 번에 출하하면 rung 2 정체가 4중 귀속 문제. → Round 14에서 두 번 spawn으로 해소.

## Goal

vqapr를 처음 보는 coding agent가 **패키지 소스를 읽지 않고** 공개 CLI와 설치된 skill만으로 dataset 등록 → DataModel firm characteristics → StrategyModel factor return을 수행할 수 있게 하고, 그것이 실제로 되는지를 `vqapr-testbed/`에서 반복 측정 가능하게 만든다.

## Constraints

- `AGENTS.md`, `CLAUDE.md` 등 instruction file은 읽지도 쓰지도 않는다. skill directory만 만들고 지운다. (`constraint:no-instruction-files`)
- `src/vqapr/agent/`는 패키지의 deterministic 경로에서 import되지 않으며 반대 방향도 없다. (`constraint:no-import`)
- SKILL.md 본문은 동사 상세를 **어디에도 중복하지 않는다.** 상세는 `--help`, 템플릿 emitter, 렌더된 카탈로그가 답한다. 본문은 하우스 스타일 80–124줄. (`constraint:progressive-disclosure`)
- 모든 skill 파일은 YAML frontmatter `name` + `description`을 갖는다. 이것이 자동 발견의 조건이다.
- 기존 `code` 문자열 값은 보존한다. 정확한 code를 참조하는 테스트 60개가 깨지면 안 된다.
- 레지스트리 검증은 `collector()` 진입점에서만 한다. `Failure.__post_init__`에는 넣지 않는다 — 실패 객체 생성 중 `ValueError`는 typed failure를 `unhandled` traceback으로 뒤집는다.
- `run` 영속화는 `final_state.recorder_rows` + manifest + finalization provenance로 한정한다. `SimulationResult` 전체 직렬화는 하지 않는다.
- `.vqapr/runs/<id>/`는 `workspace.py`의 기존 원자적 교체 규약을 따른다. 새로 발명하지 않는다.
- `materialize`와 `publish`의 입력은 `register`·`run`과 동일하게 YAML spec 파일이다.
- skill은 package validation을 우회하지 않고 missing semantics를 추측하지 않으며 근거 확인 전에 binding을 확정하지 않는다. (`constraint:skill-never-bypasses`)
- 같은 target으로 반복 설치해도 중복이나 무의미한 diff가 생기지 않고, 사용자가 수정한 생성 파일은 명시적 확인 없이 덮지 않는다. (`constraint:idempotent`)
- 구현 기록은 `docs/implementations/`에 `NNN-kebab-case-slug.md`로, `046` 다음 번호부터. 번호 재사용·재번호 금지. **행위 변경 단위로** 만들고 canon 문서 수정은 그 변경을 정당화하는 기록 안에 담는다 — `AGENTS.md`가 문서 전용 변경에 기록을 만들지 말라고 하기 때문이다.

## Non-Goals

- 사용자 인터뷰 지침(PIT 설명, 데이터 읽고 후보 제시 절차) — 다음 사이클.
- PRD §11.4 sample journey — testbed가 그 역할을 한다.
- reason code 전수 열거 및 그에 대한 런타임 강제 — R1이 stage/family까지만 조인다.
- `SimulationResult` 전체 직렬화와 재개 가능한 run(UC-RECOVERY-001).
- `preflight` 단독 동사, 선언 제거 동사(`unregister`).
- `vqapr describe` 런타임 조회 동사 — Round 4에서 탈락.
- 분석 함수(IC, NAV, drawdown, returns)의 CLI화 — Python public API에 남는다.
- 전체 논문 replication — factor replication까지만.

## Acceptance Criteria

### Build Gate — 우리가 spawn 전에 검증한다. 빈 디렉터리에서 30분, 소스 열람 없이.

- [ ] 1. `mkdir t && cd t && vqapr list datasets` → `ok:true`, `stage:"workspace.list"`, `count:0`, exit 0
- [ ] 2. `vqapr --help` → `new register materialize run publish list skill` 전부 나열, 각각 한 줄 설명 포함
- [ ] 3. 7개 동사 각각 `vqapr <verb> --help` → 비어 있지 않은 description. 맨 usage 줄만 찍히는 동사가 하나도 없다
- [ ] 4. `vqapr new run-spec > spec.yaml` → `run.py:_REQUIRED`의 8개 키가 전부 들어 있다
- [ ] 5. `vqapr run nope.yaml` → `ok:false`이고 `stage != "unhandled"`, `traceback`/`detail` 키 없음
- [ ] 6. 템플릿 그대로 `vqapr run spec.yaml` → `ok:false`, `stage`가 등록된 stage이고 `failures[].code`가 그 stage로 시작
- [ ] 7. `python -c "import vqapr.descriptors as d; print(len(d.STAGES))"` → 1 이상. `vqapr list datasets`의 `stage` 값이 그 집합의 원소
- [ ] 8. `vqapr skill install --target both --dry-run` → 해석된 루트가 `.git` 루트로 출력되고 exit 0, `git status --porcelain` 불변
- [ ] 9. `vqapr skill install --target both` → `.agents/skills/vqapr/SKILL.md` 존재, `.claude/skills/vqapr-skill/SKILL.md` 존재하고 20줄 이하이며 `.agents/skills/vqapr` 문자열 포함
- [ ] 10. `head -1 .agents/skills/vqapr/SKILL.md` → `---`, `name:`과 `description:` 포함, 총 80–124줄
- [ ] 11. `git status --porcelain AGENTS.md CLAUDE.md` → 비어 있음
- [ ] 12. `vqapr skill list` → 양쪽 target `installed:true`. `vqapr skill remove --target both && vqapr skill list` → 양쪽 `installed:false`, `git status --porcelain` 깨끗
- [ ] 12b. SKILL.md를 한 줄 수정한 뒤 `vqapr skill remove` → 그 파일은 지워지지 않고 보고됨. `--force`면 지워짐
- [ ] 12c. 원본 `src/vqapr/agent/skill/SKILL.md`를 수정하고 버전은 그대로 → `vqapr skill list`가 stale로 보고
- [ ] 13. rung 1–3: `adjusted_prices.parquet` 등록 → `vqapr materialize` → `vqapr run` → 전부 `ok:true`, envelope에 `run_id` 포함
- [ ] 14. **새 셸에서** `vqapr publish <run_id>` → `ok:true`. *(지배 항목 — 통과하면 4·6·13과 사다리 세 칸, cold-process 경계가 전부 성립한다)*

### Spawn Gate — spawn된 agent가 측정한다. FRICTION.md와 transcript가 계측기.

- [ ] vqapr 귀책 `blocked` 항목 **0건**
- [ ] `slowed` 항목 **2건 이하**
- [ ] `qlibx/src/` 열람 **0회**, 열람했다면 스스로 `F-` 항목으로 기록(감사 가능해야 함)
- [ ] 각 rung의 **첫 호출이 3회 시도 안에 성공**
- [ ] rung 1: 등록 결과가 사전 실측한 행수·기간·종목수와 일치
- [ ] rung 2: characteristic 패널의 (date, instrument) 커버리지 비율이 사전 선언값과 일치
- [ ] rung 3: 같은 프로세스에서 publish한 산출물과 cold 프로세스 재적재 후 publish한 산출물이 **바이트 동일**
- [ ] FRICTION.md에 `wrong` severity가 신설되어 있고, 조용한 오답이 기록 가능하다

### 선행 작업 (spawn 전 필수)

- [ ] `adjusted_prices.parquet`의 행수·기간·종목수를 실측하고 동결한다
- [ ] rung 2 커버리지 비율 목표값을 계산하고 동결한다
- [ ] `scan.py` 7개 + `preflight.py` 3개 인라인 stage 리터럴을 명명 상수로 끌어올린다 (레지스트리 선행 조건)
- [ ] `MISSION-A.md`를 쓴다: rung 1 정지, 소스 열람 금지, 마찰 기록 의무, 정지 조건 명시
- [ ] canon 수정 4건과 각각의 구현 기록

## Deferrals

- **skill-user-bridge** — 사용자 확인 보류(R3). framework-agent 계층 우선.
- **sample-journey** — 사용자 확인 보류(R3). testbed 중복 회피.
- **MISSION-B.md** — agent A의 friction log를 읽은 뒤에 쓴다(R18). 미리 쓰면 A가 발견할 것을 예단한다.
- **reason code 전수 열거(R2/R3)** — R1 선택. reason drift는 잡히지 않으며 이것은 **알려진 한계**로 남는다.
- **Convergence Pacing** — min-round floor, score-drop cap, dampening 없음. 양방향 채점이 pacing 기제다.

## Assumptions Exposed & Resolved

| 가정 | 도전 | 결론 |
|---|---|---|
| arch §10.4대로 error catalog를 소스에서 생성할 수 있다 | Researcher+Contrarian: code가 37개 콜사이트 f-string, 레지스트리 없음 | 거짓. R1로 stage/family까지만 생성 |
| descriptors 리팩터는 거대하다 | 실측: `*_STAGE` 상수 25개, code는 이미 `<stage>.<reason>` 구조, 콜사이트 37개 | 작다. R1은 상수 25개 + `collector()` 시그니처 |
| instruction file을 안 건드리면 skill이 발견 안 될 수 있다 | 실측: kaist-thesis가 이미 `.claude/`+`.agents/` 양쪽으로 운용 중 | 거짓. 단 frontmatter가 발견의 조건 |
| 두 target에 같은 본문을 복사하면 된다 | 실측: 기존 `paper-search`·`bok-ecos-api` 두 사본의 sha가 이미 다름 | 거짓. adapter로 단일 원본 |
| `publish`는 독립 동사로 만들 수 있다 | `publish_run_record`가 `result`를 메모리 객체로 받고 `run`은 아무것도 안 남긴다 | 조건부. `run`이 `recorder_rows`를 영속화해야 성립 |
| `run` 결과 영속화는 작은 추가다 | Researcher: `object` 타입 필드 셋 + 해시 재증명 페이로드, 직렬화기 부재 | 전체는 새 포맷 설계. 좁은 범위만 |
| SKILL.md가 `--help`에 위임하면 된다 | Contrarian: `main.py` 독스트링이 CLI의 설명을 금지하고 skill을 가리킨다. 순환 | 권한을 갈랐다. CLI=usage, skill=remedy |
| "fresh agent가 사다리 완주"면 성공이다 | Contrarian: look-ahead 등록도, 12번 시행착오도, 소스 열람도 통과시킨다 | Spawn Gate로 교체 |
| 이웃 replication의 숫자를 rung 3 기준으로 쓸 수 있다 | 275,711 잔차행과 Sharpe 0.352는 PCA 잔차 위 트레이딩 정책 — 우리 사다리와 다른 파이프라인 | 못 쓴다. rung 3은 자기일관성 검사 |
| 버전을 올리면 stale을 감지할 수 있다 | editable 의존에서 버전 안 올리고 내용만 바뀌면 매니페스트가 최신이라 보고 | 원본 sha도 저장 |
| `agent install`을 `skill install`로 개명하면 F-001이 해결된다 | F-001의 근본 원인은 명령 부재가 아니라 현재형으로 쓰인 미구현 문서 | README를 같은 변경에서 고친다 |

## Technical Context

- **CLI**: `src/vqapr/cli/{main,envelope,new,register,run,list_}.py`. `_COMMANDS`가 동사 레지스트리(`main.py:19-24`). `envelope.py`가 단일 JSON 줄 + exit 0/1을 보장하고 `UsageError`로 argparse까지 봉투 안으로 넣는다. 서브파서는 `add_parser(name)`으로 help 없음(`main.py:52`).
- **오류**: `src/vqapr/domain/errors.py` — `FailureFamily` 닫힌 enum 7개(19-28), `Failure.code`는 `<stage>.<reason>` 점 경로(독스트링 명시), `collector(stage, family)`가 진입점. `.bounded()` 콜사이트 37개 / 11파일. `*_STAGE` 명명 상수 25개+, 인라인 리터럴 `scan.py` 7 + `preflight.py` 3. tests에서 정확한 code 참조 60건.
- **public 표면**: `src/vqapr/public.py` `__all__` 105개. `materialize(project_root, component_id, MaterializationSpec(dataset_id, value_fields), *, evaluation_times, instruments)`. `Workspace.instruments()`(302-315), `Workspace.evaluation_times()`(317-338)가 전체 distinct 집합을 준다 — 기본값으로 쓰면 무한정 실행. `_evaluation_times`(216-226)·`_instruments`(241-248)는 빈/중복/naive를 거부하지만 **소속 검사는 없다**. 전량 불일치만 `materialize.output.empty`(893-900).
- **run 결과**: `SimulationResult` = `occurrences` + `final_state`(`flow/simulation.py:195-198`). `AcceptedRunState.__post_init__`이 모든 ref 해시를 페이로드에 대해 재증명(`run_state.py:96-101`). 직렬화기 없음. `publish_run_record`가 소비하는 것은 `final_state.recorder_rows`(`run_state.py:123-135`). 기존 아티팩트 writer는 `materialize.py`의 `.vqapr/materialized/<stem>.parquet` + `.lineage.json`뿐.
- **agent 층**: `src/vqapr/agent/` — 빈 `__init__.py` + `skill/README.md` + `sample/README.md`. `SKILL.md` 없음, `targets.py` 없음, `descriptors.py` 없음. README가 `vqapr agent install`을 현재형으로 서술.
- **testbed**: `C:/Users/chlje/DevProjects/kaist-thesis/vqapr-testbed/`. `kaist-thesis/pyproject.toml`이 `vqapr = { path = "../qlibx", editable = true }`. skill은 리포 루트 `kaist-thesis/.agents/skills/`·`.claude/skills/`에 산다(testbed 하위가 아니다). 기존 skill 2개는 frontmatter 보유, 80~124줄, 두 사본의 sha 상이. 데이터는 `data/kaist_pilot/canonical/common/korean_equity/adjusted_prices.parquet`, 2015-01-02~2026-07-20, 4,962종목, 배당 미포함. GPU 함정: 일반 `uv sync`가 vendor ROCm torch를 CPU 빌드로 교체(F-002).
- **PRD/canon 근거**: §2.6(package는 판정, skill은 대화), §11.1(stage 기준 guidance 조회), §11.2(normative entrypoint 경로), §11.3(preview/apply/update/remove, fingerprint), §11.4(sample), arch §10.4(agent 층은 호출되지 않음, descriptors 생성). UC-FACADE-001, UC-AGENT-001/002, UC-ERROR-001, UC-RESEARCH-001, UC-ARTIFACT-001, UC-ONBOARD-001, UC-MODEL-001, UC-FACTOR-001, UC-RECOVERY-001.

## Ontology (Key Entities)

| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| Skill | core domain | SKILL.md body, frontmatter, when-to-use, mission ladder | Skill owns remedy; CLI owns usage |
| Skill Manifest | core domain | package version, install timestamp, sha256 per generated file, source sha | defines what vqapr owns; remove consults it |
| Adapter | core domain | frontmatter, pointer path | points at the codex-target SKILL.md |
| Target | external system | kind, skill_directory, entrypoint | receives a Skill or an Adapter |
| Install Root | core domain | auto-detected via .git, --into override, dry-run resolved path | contains the Target directories |
| CLI Verb | core domain | new, register, materialize, run, publish, list, skill | owns its own usage text; materialize/publish take a YAML spec |
| Run Artifact | core domain | run id, recorder rows, manifest, finalization provenance | publish consumes it in a cold process |
| Template Emitter | core domain | declaration template, run spec template | replaces hand-written spec examples in the Skill |
| Workspace Declaration | core domain | datasets, components, agendas, execution_inputs, configs | register creates it |
| Descriptor | core domain | stage, family, schema | generated from the Stage Registry |
| Stage Registry | core domain | failure stages, success stages, cli stages | enforced at collector() entry, never inside Failure |
| Build Gate | core domain | 14 command-to-observable items | verified by us before a spawn |
| Spawn Gate | core domain | zero attributable blocked, <=2 slowed, zero source reads, three-try first invocation, rung 1-2 exact numbers, rung 3 byte-identical round trip | measured by FRICTION.md and the transcript |
| Friction Entry | supporting | doing, expected, got, cost, fix, severity blocked/slowed/surprised/wrong | measures the Skill and the CLI |
| Testbed | external system | path, FRICTION.md, editable vqapr dep | hosts a Fresh Agent |
| Fresh Agent | core domain | knows only installed package and skill | Agent A stops after rung 1; Agent B does rungs 2-3 |
| Mission | core domain | register dataset, materialize firm characteristics, produce factor return | split across two spawns |

## Ontology Convergence

| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 8 | 8 | - | - | N/A |
| 2 | 12 | 4 | 0 | 8 | 66.7% |
| 3 | 9 | 0 | 0 | 9 | 100% (3 removed by deferral) |
| 4 | 10 | 1 | 0 | 9 | 90% |
| 5 | 10 | 0 | 1 | 9 | 100% |
| 6 | 12 | 2 | 0 | 10 | 83.3% |
| 7 | 13 | 1 | 0 | 12 | 92.3% |
| 8 | 13 | 0 | 0 | 13 | 100% |
| 9 | 14 | 1 | 0 | 13 | 92.9% |
| 10 | 16 | 2 | 0 | 14 | 87.5% |
| 11 | 16 | 0 | 0 | 16 | 100% |
| 12 | 17 | 1 | 0 | 16 | 94.1% |
| 13–18 | 17 | 0 | 0 | 17 | 100% |

여섯 라운드 연속 새 엔티티 없음 — 도메인 모델 수렴.

## Interview Transcript

<details>
<summary>Full Q&A (18 rounds + Round 0)</summary>

### Round 0 — Topology
**Q:** 최상위 컴포넌트와 locked intent 확인 (1차: 5개 / 2차 수정본: 6개)
**A:** 1차에서 자유 응답으로 수정 — instruction file 불간섭, `vqapr skill <verb>` 형태, skill이 framework-agent와 agent-user 두 bridge를 모두 담음. 2차 수정본에 "이대로 맞다".

### Round 1 — cli-surface / goal
**Q:** public API에는 있는데 CLI로 못 하는 것들을 놓고, CLI가 어디까지 덮어야 하나?
**A:** B — 워크스페이스 + 실행 + materialize/publish까지. 분석은 Python.
**Ambiguity:** 100% → 73.5%

### Round 2 — skill-framework-bridge / criteria (refine gate)
**Q:** framework-agent 우선순위와 vqapr-testbed 검증 루프 해석 확인
**A:** 맞다 — 이대로 진행
**Ambiguity:** 73.5% → 65.5%

### Round 3 — sample-journey / goal
**Q:** 후순위 세 컴포넌트가 이번 스펙 안인가 밖인가?
**A:** B — 공통 셋 + descriptors, 나머지 defer. 추가로 미션 사다리 명시.
**Ambiguity:** 65.5% → 51.5%

### Round 4 — descriptors / criteria (lateral panel)
**Q:** descriptors를 어떤 모양으로 할 것인가? (생성 전제가 거짓이라는 panel 증거 제시)
**A:** D2 — stage/code 레지스트리 리팩터를 먼저 한다
**Ambiguity:** 51.5% → **53.5% ↑** (trigger D)

### Round 5 — descriptors / constraints
**Q:** 레지스트리가 어느 정도로 조이나?
**A:** R1 — stage/family만 선언, 콜사이트 불간섭
**Ambiguity:** 53.5% → 44.25%

### Round 6 — skill-cli / goal (refine gate)
**Q:** `vqapr skill install`이 어디에 설치하나?
**A:** `--target codex|claude|both`, claude는 adapter, agents에 full text. 루트는 `.git` 자동 탐지, `--into` 덮어쓰기, dry-run이 경로 출력.
**Ambiguity:** 44.25% → 42.75%

### Round 7 — cli-surface / constraints
**Q:** 최종 동사 집합은?
**A:** V2 — materialize + publish 추가, run이 `.vqapr/runs/<id>/`에 영속화
**Ambiguity:** 42.75% → 38.5%

### Round 8 — cli-surface / constraints
**Q:** 측정된 마찰 4건이 이번 사이클인가?
**A:** 넷 다 포함
**Ambiguity:** 38.5% → 38.5% (flat — skill-framework-bridge가 최솟값을 붙들고 있었다)

### Round 9 — skill-framework-bridge / constraints
**Q:** SKILL.md는 어디서 끝나고 references/는 어디서 시작하나?
**A:** P1 본문 + P3 위임 — 사다리는 본문에, 동사 상세는 어디에도 중복 없이
**Ambiguity:** 38.5% → 26.5% (milestone: progress → refined)

### Round 10 — criteria (lateral panel 2)
**Q:** 무엇이 완성을 증명하나?
**A:** C3 — Build Gate와 Spawn Gate 둘 다 + FRICTION.md에 `wrong` severity 신설
**Ambiguity:** 26.5% → 21.5%

### Round 11 — descriptors / constraints
**Q:** panel 지적 3건 (영속화 범위 / 종목 정합성 / 레지스트리 경계)
**A:** N1 — 좁은 영속화 + 정합성 검사 추가 + `collector()`에서 검증, 성공·CLI stage는 별도 선언
**Ambiguity:** 21.5% → 15.5%

### Round 12 — skill-cli / constraints
**Q:** `vqapr skill`은 무엇을 자기 것으로 아나?
**A:** O1 매니페스트 + `--force`
**Ambiguity:** 15.5% → 14.25%

### Round 13 — skill-framework-bridge / goal
**Q:** canon 문서 수정 권한은?
**A:** 네 건 전부 + 각각 구현 기록
**Ambiguity:** 14.25% → 11.25%

### Round 14 — skill-framework-bridge / context
**Q:** 일회성 fresh-agent 측정을 어떻게 쓰나?
**A:** 넷 다 출하하되 두 번 spawn (A는 rung 1 정지, B는 rung 2-3)
**Ambiguity:** 11.25% → 9.3%

### Round 15 — Spawn Gate / criteria
**Q:** rung 3의 사전 선언 숫자는?
**A:** N1 — rung 1-2만 숫자, rung 3은 바이트 동일 자기일관성 검사
**Ambiguity:** 9.3% → 8.3%

### Round 16 — skill-cli / context
**Q:** editable 의존에서 stale을 어떻게 감지하나?
**A:** 둘 다 — 원본 sha가 정확성, 버전 올림이 사람용 신호
**Ambiguity:** 8.3% → **9.4% ↑** (trigger C, 채점 누락 정정)

### Round 17 — descriptors / goal
**Q:** 생성된 카탈로그의 형태는?
**A:** F3 — `vqapr.descriptors`가 코드 진실, `skill install`이 `references/stages.md` 렌더링
**Ambiguity:** 9.4% → 6.0%

### Round 18 — verification loop / criteria
**Q:** mission 문구가 이 스펙의 산출물인가?
**A:** agent A 것만. B는 A의 friction log를 읽고 쓴다.
**Ambiguity:** 6.0% → **4.4%** (임계값 통과)

### Restate gate
**A:** Yes, crystallize

</details>
