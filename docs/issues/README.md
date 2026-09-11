# Issue ledger — 상태 한 줄씩

**작성 2026-09-02 · 갱신 2026-09-11.** 98개 중 **93개가 닫혔고, 닫힌 것은 `archive/`로 옮겼다.**
이 디렉터리에 평평하게 남는 것은 아직 열린 둘 — `023`(절반)과 `035`(판정만 남음) — 과, 2026-09-10에
닫혔지만 그 record들이 인용하는 동안 한 릴리스만 여기 두는 `089`–`094`다(0.11.0 릴리스 때 archive로).

**옮기면서 인용을 같이 고쳤다.** `src/`·`docs/`·`tests/`·`scripts/`의 481개 파일이 이 번호들을
**결정의 근거**로 인용하고 있었고, 그 1,036곳을 `docs/issues/NNN` → `docs/issues/archive/NNN`으로
기계적으로 재작성했다. 인용은 하나도 끊기지 않는다 — 옮기지 않는 근거였던 것이 그 재작성으로
사라졌다. 새 인용을 쓸 때는 **닫힌 이슈는 `docs/issues/archive/NNN`**, 열린 둘은
`docs/issues/NNN`이다.

**읽는 법.** 열린 것만 보려면 §1을 읽는다. §2는 닫힌 것들이고, 무엇이 닫았는지만 적는다.
각 파일 안의 `**Status:**` 줄이 여전히 authority이며, 이 표는 그것을 모은 것이다.

**testbed가 보내온 보고는 번호를 받지 않는다.** `report-issue-dev` skill이 쓰는 파일은
`docs/issues/report-YYYY-MM-DD-<slug>.md`로 이 디렉터리에 평평하게 도착한다. 번호는 소유자가
분류한 뒤에만 붙는다 — 여러 testbed가 동시에 번호를 고르면 충돌하고, 아직 판정되지 않은 보고에
`src/`가 인용할 번호를 주면 그 번호가 무엇을 뜻하는지 알 수 없게 된다.

> **이 디렉터리는 이슈 목록으로 닫히지 않았다.** 세 개의 명사(**Panel · Surface · Run**)가
> 캠페인으로 들어왔다 — records `133`(Surface), `137`(Panel), `139`(Run). 그 설계는
> `docs/design/the-panel-the-surface-and-the-run.md`에 있고,
> `docs/vqapr-architecture.md` §17이 그것을 소유자 mental model과 대조한다. **하나씩 닫으면
> 다섯 번 고치고 다섯 번 다시 열린다.**

---

## 1. 열린 것 — 하나 (`023`; `087`은 record `164`, `078`은 record `155`, `079`·`083`·`084`·`085`는 `156`, `080`·`081`은 `157`, `086`은 `158`, `027`·`082`는 `160`이 닫았다)

| # | 제목 | 상태 (2026-09-03 재확인) | 어디로 가는가 |
|---|---|---|---|
| `023` | 하나의 digest가 그 아래에서 바뀔 수 있는 파일을 기술한다 | **절반 열림.** docs 절반은 `fix/023-narrow-the-provenance-promise`가 닫았다. 코드 절반(`show run`의 `matches`/`differs` 읽기)은 HELD — gate가 되면 `009`의 결정을 뒤집는다 | 명사 3 (Run record) |
| ~~`027`~~ | 아무것도 convention을 소리 내어 말하게 하지 않는다 | **닫힘 2026-09-05 — record `160`.** `register`가 `spoken`으로 PIT 개념마다 한 문장을 말한다(dataset의 `available_at`, execution input의 `trade_at`과 fill 규약, run의 `at`·`timezone`); 없으면 아무 말도 안 한다 | 닫힘 |
| ~~`088`~~ | `DOUBLE`로 등록된 field가 모델에 `Decimal`로 도착한다 — 아무도 그것이 무엇인지 선언하지 않았다 | **닫힘 2026-09-08 — record `173`.** 오너 판정: user가 `field_types`를 선언하고 등록이 `DESCRIBE`와 1회 대조해 불일치를 이름으로 거부한다(`049`의 "author는 타입을 쓰지 않는다"와 `079`의 A안 기각을 번복). `DECIMAL`은 잴 수는 있어도 선언할 수 없어 등록에서 `field_decimal`, DataModel 출력은 첫 세션에서 `field_type`으로 거부. 샘플 panel은 float64. 열린 것: DataModel `value_fields`의 선언 타입 | 닫힘 |
| ~~`087`~~ | 끝난 run이 occurrence마다 parquet 파일 하나를 남긴다 — 표 하나가 8 KB짜리 607개 | **닫힘 2026-09-07 — record `164`.** writer가 행을 Arrow로 메모리에 들고 run이 끝날 때(정상·예외·인터럽트) 표당 `all.parquet` 하나를 쓴다; 256 MB spill 밸브; hard kill은 spill분만 남는다(오너가 record 135의 약속 축소를 수용). 매 loop 물리 IO 0. 샘플 journey 7.8→5.4 s, 파일 1,465→3 | 닫힘 |

### 오너가 0.11.0 척추 트레이스에서 연 셋 (2026-09-10, `095`–`097`) — 계획 `.agent/plans/active/one-door-campaign.md`

| # | 제목 | 상태 | 어디로 가는가 |
|---|---|---|---|
| ~~`095`~~ | 물리 읽기의 검증에 문이 하나가 아니다 — 모듈 셋, 집행표는 세 번 스캔 | **닫힘 2026-09-10 — record `234`.** `data/validation.py` 한 문(`verify_source` · `require_verified` · `verify_roster`); 등록이 `source_digest`와 `execution_prices`를 두고 preflight·run·check는 digest만 대조(`dataset.source_changed` · `dataset.unverified`); `validate_execution_table`과 세 diagnosis 삭제; 같은 선언으로 다시 등록하면 측정만 갈린다; 경계 테스트가 스캔 커널을 한 모듈에 묶는다 | 닫힘 |
| ~~`096`~~ | panel 읽기가 종목 순회 Python 루프다 — sample 전략이 for loop을 도는 이유 | **닫힘 2026-09-10 — records `232`·`233`.** 필드마다 name-major Arrow 블록 하나, `PanelWindow.matrix()`, 벡터화된 `counts`/`current`/`latest`, `scan.observation_table`; sample 전략·scaffold 둘·skill reference가 행렬 위에서 계산(`Decimal`은 `Rebalance` 경계에서만). 3,000종목 decide 8.8→1.5 ms, panel build 10.7→1.2 ms | 닫힘 |
| ~~`097`~~ | `flow/engine/loop.py`의 추상 루프에 서브클래스가 하나뿐 | **닫힘 2026-09-10 — record `231`.** `EventLoop` 삭제, `RunLoop.run`이 걷기; `strategy_loop`/`datamodel_loop`는 `RunLoop`를 돌려주는 함수; `flow/engine/loop.py`는 이벤트 타입만 | 닫힘 |

### 2026-09-11의 번호 없는 보고 넷 — incremental testbed(`0.14.4` wheel, `b8b47e6c`) — 접수

기존 workspace에 전략 하나를 더하는 A/B(`kwam-enhanced-index/vqapr-incr-testbed`). 넷 다 소스에서 확인했다.

| 파일 | 제목 | 상태 | 닫은 것 |
|---|---|---|---|
| `report-2026-09-11-a-decide-after-close-run-is-refused-on-every-friday-...` | decide-after-close run이 `within: 1d`로 금요일마다 거절되고, 같은 occurrence의 두 번째 거절이 run end를 가리킨다 | **접수.** 두 문(`judgments`의 ordering, `preflight`의 target)이 같은 occurrence를 각자 거절 | — |
| `report-2026-09-11-rebalance-of-refuses-a-zero-weight-...` | `Rebalance.of`가 `signed`는 받는 0 비중을 거절하고, 0으로 두는 법을 말하지 않는다 | **접수 — 오너 판정 대기**(0을 받을지, 거절문만 고칠지) | — |
| `report-2026-09-11-the-krx-settlement-order-is-not-written-...` | KRX 체결 순서(매도 먼저, 큰 매수 먼저)가 agent가 읽는 곳에 없다 | **접수.** skill 절반은 바로; record의 trim 표시는 record 모양이 바뀌어 오너 판정 대기 | — |
| `report-2026-09-11-adding-one-strategy-...-costs-agents-more-...` | 기존 workspace에 전략 하나를 더해도 pandas보다 1.3–3.8배 | **접수 — 오너 판정 대기**(측정; 실행 가능한 예제/scaffold 옵션은 제품 방향) | — |

### 2026-09-11의 번호 없는 보고 하나 — demo testbed(`0.14.4`, `b8b47e6c`) — 접수 후 닫힘

| 파일 | 제목 | 상태 | 닫은 것 |
|---|---|---|---|
| ~~`report-2026-09-11-skill-install-writes-into-the-enclosing-repositorys-git-root-...`~~ | `skill install`이 프로젝트가 아니라 그것을 감싼 저장소의 `.git` 루트에 쓰고, `--project-root .`로는 바꿀 수 없다 | **닫힘 2026-09-11 — record `258`.** 루트가 하나: skill은 workspace root(현재 디렉터리, 또는 `--project-root`)에 깔리고 — 다른 모든 명령과 stale 검사(`upgrade_note`)가 보는 곳 — `--into`가 다른 곳을 댄다. `.git` 걷기와 `argument.no_git_root` 삭제. 깨지는 변화 한 줄(git 루트 아래 workspace의 옛 사본은 `skill remove --into <git 루트>`)은 다음 릴리스 노트에 | 코드 + skill + PRD |

### 2026-09-11의 번호 없는 보고 아홉 — testbed(`0.14.2` wheel): A/B testbed · FF3 testbed · enhanced-index-3 — 일곱 닫힘, 하나 다른 세션, 하나 보류

오너가 번호 없이 바로 고치게 했다(develop 위, records `249`–`257`). 월말 발화는 `on: last`, 옆 모듈 import는 "한 파일
원칙 유지 + 거절문과 skill", BLAS 스레드는 "`--jobs` 워커만 1"을 오너가 골랐다. 메모리 보고는 측정
(`scratchpad/mem`, 합성 300종목)으로 원인을 넷으로 나눴고 넷 다 고쳤다.

| 파일 | 제목 | 상태 | 닫은 것 |
|---|---|---|---|
| ~~`report-2026-09-11-a-jobs-batch-writes-no-run-record-...`~~ | `--jobs` 배치가 run record를 쓰지 않아 `show run`이 완료된 run을 거절 | **닫힘 — record `249`.** `run.json`을 `_run_member`(순차 경로와 워커가 모두 지나는 몸체)에서 쓴다 | 코드 |
| ~~`report-2026-09-11-a-usage-refusal-names-only-vqapr-help-...`~~ | usage 거절의 `fix`가 `vqapr --help`만 댄다 | **닫힘 — record `250`.** 인식 못 한 인자는 그것이 따라온 하위 명령이 거절: `fix`에 그 usage 한 줄과 `vqapr <cmd> --help`, `observed`에 거절된 토큰 | 코드 |
| ~~`report-2026-09-11-new-help-points-a-strategy-at-calendar-lookback-...`~~ | `new --help`가 strategy에 `--calendar-lookback`을 권하고 `new strategy`는 거절 | **닫힘 — record `251`.** strategy scaffold가 calendar 창과 그 창의 guard를 낸다; `--instants-lookback` strategy는 InputError | 코드 |
| ~~`report-2026-09-11-register-by-kind-refuses-...-shared-base-...`~~ | `register <kind>`가 공유 base를 상속한 전략을 거절하고, `fix`가 이미 있는 클래스를 요구 | **닫힘 — record `252`.** 파싱이 못 찾으면 로드한 모듈에서 객체로 판정(YAML route와 같은 판정) | 코드 |
| ~~`report-2026-09-11-a-component-cannot-import-a-module-beside-it-...`~~ | 옆 모듈 import가 502이고 `fix`가 이유를 말하지 않는다 | **닫힘 — record `252`.** 한 파일 원칙은 그대로(fingerprint가 그 파일만 덮는다); 옆에 실제로 있는 모듈이면 `fix`가 이유와 길을 말하고 skill 둘이 같은 말 | 메시지 + skill |
| ~~`report-2026-09-11-an-agenda-cannot-fire-on-the-last-trading-day-of-a-month`~~ | agenda가 월 마지막 거래일에 발화할 수 없다 | **닫힘 — record `253`.** `agenda.on: last`(`w`·`M`); 끝났다고 보이는 달만, `end` 뒤 세션으로 판정하되 발화는 없음; `first`만 쓰던 run의 identity는 그대로 | 코드 + skill |
| ~~`report-2026-09-11-a-strategy-runs-memory-grows-...`~~ | 일봉 전략 run의 메모리가 주문 수에 비례해 문서 규칙을 크게 넘는다 | **닫힘 — records `254`–`257`.** envelope·publish가 record를 배치로 흘림(`254`); spill 부분을 한 번에 다시 읽지 않는 seal(`255`); record가 있는 run은 fill 쪽 증거를 루트·trace·`feedback`에 들지 않음(`256`); `--jobs` 워커는 BLAS 1스레드(`257`) | 코드 + skill |
| `report-2026-09-11-the-skills-lead-agents-to-conclude-a-factor-return-series-...` | skill을 따른 에이전트들이 factor 수익률은 vqapr로 못 만든다고 결론 | **다른 세션이 skill로 다룸** (commit `421316b7` 등, `experiments/exp_250`). 이 묶음에선 코드 변경 없음 | skill |
| `report-2026-09-11-a-smaller-model-does-not-finish-...` | 작은 모델(haiku)이 framework 경로를 끝내지 못하고 끝냈다고 보고 | **보류 — 2026-09-11 오너 판정.** vqapr 결함인지 불분명; 제안(진행 표시, `list runs`의 started 상태, factor leg의 짧은 경로)은 열려 있다. 참고: record `249` 뒤로 중단된 run도 `run.json`을 남긴다 | — |

### 2026-09-10의 번호 없는 보고 일곱 — testbed(`0.11.0` wheel) 다섯, 0.12.0 시나리오 트레이스 하나, testbed(`0.13.0` wheel) 하나 — 전부 닫혔다 (남은 셋은 0.14.2 hotfix, records `243`–`245`)

0.11.0 wheel로 마이그레이션하며 낸 보고들과 0.12.0 stepper 트레이스가 낸 하나. 번호는 아직 없다 — 같은 날 오너가 `095`–`097`을 썼고,
번호는 오너가 붙인다. 첫 번째는 671-run sweep에서 `--jobs 16`이 한 번에 하나씩 돌던 것으로,
성능 이슈로 오너가 바로 고치게 했다.

| 파일 | 제목 | 상태 | 닫은 것 |
|---|---|---|---|
| ~~`report-2026-09-10-run-jobs-does-not-parallelise-datamodel-runs`~~ | `vqapr run --jobs N`이 datamodel run을 병렬로 돌리지 않는다 — 프로세스 하나, 한 번에 하나 | **닫힘 — record `230`.** 두 종류 모두 풀로; worker의 raise는 그 run의 entry; envelope에 `jobs`; 배치 안에서 남이 쓰는 것을 읽는 run은 통째로 거절(`run.batch_dependent`, 오너 결정) | 코드 + skill |
| ~~`report-2026-09-10-agenda-has-no-year-unit-and-the-refusal-reads-as-a-closed-set`~~ | `agenda.every`에 `y` 단위가 없고, 거절문이 닫힌 집합처럼 읽힌다 | **닫힘 2026-09-10 — record `244` (0.14.2).** 거절문이 문법을 말한다(count는 자유, 단위는 d·w·M / m·h); `y`면 `12M`을 가리킨다; skill 문서 셋도 같은 말. 연 단위는 더하지 않았다 | 코드 + skill |
| ~~`report-2026-09-10-check-derives-a-three-year-agenda-twice`~~ | `check`가 run의 agenda를 두 번 유도한다 — 3년 run에서 check 3.6 s 중 3.5 s | **닫힘 2026-09-10 — record `238`.** workspace가 dataset의 instant를 명령당 한 번 읽어 preflight의 두 번째 유도가 스캔 없이 끝난다(파일의 `Status` 줄이 authority; 이 행은 2026-09-11에야 따라잡았다) | 코드 |
| ~~`098`~~ (`report-2026-09-10-a-datamodel-run-holds-memory-...`) | datamodel run의 peak 메모리가 lookback·기간이 아니라 종목 수에 비례한다 — 309종목 0.55 GB, 5종목 0.23 GB; 기간 7배엔 12% | **닫힘 2026-09-10 — records `235`·`236`.** 0.32 GB는 0.11.0 `Panel.from_rows`의 dict 행 877k(record 232가 이미 제거); 남은 절반은 등록 span 전체 스캔 + 필드당 두 벌. 235: panel은 run horizon, 숫자 필드 한 벌, bounds 밖 거절. 236: `--jobs` 배치가 dataset마다 cube를 한 번 굽고 worker가 mmap, 끝나면 삭제. 전 종목 worker peak 0.76 → 0.17 GB | 코드 + skill |
| ~~`report-2026-09-10-show-dataset-limit-zero-does-not-return-on-a-large-source`~~ | `show dataset --limit 0`이 430 MB(8.7M행) 소스에서 5분 넘게 돌아오지 않고 메모리를 소진한다 | **닫힘 2026-09-10 — record `245` (0.14.2).** `--limit 0`은 "전부"(record `077`)였고 모든 행을 dict로 올렸다. 이제 count는 count: 0은 0행, `show dataset`·`--table` 둘 다. 4.2M행에서 100 s·+1.78 GB → 0.86 s. 전부를 원하면 `rows_total`만큼 — 깨지는 변화, 0.14.2 노트에 | 코드 + skill |
| ~~`report-2026-09-10-unverified-fix-names-no-command-for-a-run-published-dataset`~~ | `dataset.unverified`가 run이 publish한 dataset에게 "register again"을 말하는데 그런 명령이 없다 (testbed, `0.13.0` wheel) | **닫힘 2026-09-10 — record `243` (0.14.2).** 거절이 `produced_by`를 읽어 run과 `vqapr run <run-id> --force`를 말한다; 선언된 dataset은 `vqapr register`를; 0.12.0 마이그레이션 노트에 run-published 한 줄 | 코드 + docs |
| ~~`099`~~ (`report-2026-09-10-check-500s-when-end-falls-between-a-fill-and-a-decision`) | `check`가 run의 `end`가 그 날의 체결과 결정 사이에 떨어질 때 500으로 죽는다 — decide-after-close·fill-next-close 전략의 유일하게 옳은 `end` | **닫힘 2026-09-10 — record `237`.** ordering 판단만 `derived_agenda`의 날짜 상위집합(`069`)을 그대로 읽어 `end` 뒤 occurrence를 `select_target`에 넘겼다; 이제 preflight가 얼리는 것과 같은 `inclusive_slice(start, end)`를 묻는다. envelope의 `blocked`/`failures` 모양은 그대로(별도 판정) | 코드 |

### enhanced-index testbed가 낸 일곱 (2026-09-09, `0.9.0.dev1` wheel) — 2026-09-10 전부 닫혔다

`report-issue-dev` skill이 쓴 첫 보고 묶음이다. `report-2026-09-09-<slug>.md`로 도착해 소유자가
2026-09-10에 분류하며 `089`–`095`를 붙였다. 하나(`095`)는 도착 시 이미 0.10.0의 record `203`이 닫아
바로 `archive/`로; 여섯은 records `215`–`220`이 하나씩 닫았다. 릴리스 노트는
`docs/releases/0.11.0.md`. 여섯 중 셋(`089`·`090`·`091`)이 한 워크플로우 — ~190개 alpha DataModel의
상수 sweep — 에서 났고, `091`은 결과가 **그럴듯해 보이는 채로 틀린** 종류다.

| # | 제목 | 상태 | 닫은 것 |
|---|---|---|---|
| ~~`089`~~ | 첫 callback에서 `self.memory`가 `None`이라 문서의 예제가 죽는다 | **닫힘 — record `215`.** opening memory는 모든 층에서 `{}`; `null` 선언도 `{}`. **run identity 전부 바뀜** (0.11 migration 1번) | 코드 + 문서 |
| ~~`090`~~ | 문서의 datamodel 재시도 절차가 바뀌지 않은 파일을 거절되게 두고, 거절이 "strategy"라 부른다 | **닫힘 — record `216`.** `record.exists` 409 · kind를 댐 · traceback 없음; "Retrying"은 `--force` | 코드 + 문서 |
| ~~`091`~~ | materialized dataset이 자기를 만든 fingerprint를 기록하지 않는다 | **닫힘 — record `217`.** `produced_by_record`; `check`의 `run.output_stale` 412 | 코드 |
| ~~`092`~~ | `optimize`가 shipped 박스의 bound를 거절한다 | **닫힘 — record `218`.** kit이 안쪽으로 quantize; 거절이 방향을 댐 | 코드 |
| ~~`093`~~ | `show dataset`이 projection 대신 원천 행을 보여준다 | **닫힘 — record `219`.** 기본이 projection, `items_are`, `--source`, `source_rows_total` | 코드 |
| ~~`094`~~ | 두 거절의 status가 결정표의 class 밖이다 | **닫힘 — record `220`.** 없는 경로는 404; 502는 "당신 코드"라고 문서 열 곳이 말함 | 코드 + 문서 |
| ~~`095`~~ | `check`가 roster 없는 run을 통과시킨다 | **도착 시 닫힘 — record `203` (0.10.0).** 보고 wheel에 없던 commit. 후속: `rm instruments` 없음 | archive |

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
| ~~`078`~~ | 지불 가능 수량 추정이 **category-driven venue가 쓰지 말라고 안내받은 채널**에서 비용을 읽고, 안 맞으면 venue를 탓한다 | **닫힘 2026-09-05 — record `155`.** 추정이 `charge`를 읽고, 보정은 청구된 값으로 다시 풀고, 못 맞추면 거부 대신 현금을 남긴다 | C4 |
| ~~`079`~~ | materialized dataset의 schema가 **첫 세션이 추론한 것**이고, 거부는 다른 것을 지목한다 | **닫힘 2026-09-05 — record `156`.** 거부가 pyarrow 문장과 확정된 스키마를 그대로 인용하고 원인을 단정하지 않는다(판정 C) | A1 |
| ~~`080`~~ | 크래시한 datamodel run이 **아무도 열거하지 않고 아무도 지우지 못하는** record 디렉터리를 남긴다 | **닫힘 2026-09-05 — record `157`.** `list datamodels`가 `unfinished`로 보이고 `rm datamodel`이 이름을 댄다; skill은 "record를 세라" | A5 |
| ~~`081`~~ | run 정의를 withdraw하면 그 record를 **열거하는 명령이 없어진다** | **닫힘 2026-09-05 — record `157`.** `list runs`가 고아를 `orphaned`로 보이고, `rm run-definition`이 남긴 것을 대고, `rm run --cascade`가 전부를 한 번에 지운다 | B1 |
| ~~`082`~~ | "이 dataset을 읽는 게 누구인가"에 답하는 것이 없고, dataset이 자기를 만든 run을 대지 못한다 | **닫힘 2026-09-05 — record `160`.** `list components --reads <dataset>`(한 프로세스에서 로드, 인덱스 없음)과 dataset의 `produced_by`(datamodel run이 등록 시 붙임) | B2 |
| ~~`083`~~ | `show model`은 component 세 종류를 읽는데 거부는 하나만 댄다 — 게다가 `unhandled` | **닫힘 2026-09-05 — record `156`.** 구조화된 거부가 세 kind를 대고, `list components --kind`가 생겼다 | B3 |
| ~~`084`~~ | run 정의는 재등록이 거부되는데, **거부도 skill도 그것을 가능케 하는 verb를 대지 않는다** | **닫힘 2026-09-05 — record `156`.** `fix`가 `rm run-definition`을 대고, skill이 예외를 말하고, 같은 문서 안의 producer run을 거부가 이름으로 댄다 | C1 (+A4) |
| ~~`085`~~ | fill 요약이 reason은 세고 instrument는 안 센다 — **한 번도 체결 안 된 종목이 안 보인다** | **닫힘 2026-09-05 — record `156`.** `never_filled`가 성공 payload에 종목별로 선다 | C5 |
| ~~`086`~~ | constraint에 허용오차가 없어 양자화 잔여가 위반으로 잡히고, `fix`는 bound를 넓히라고 한다 | **닫힘 2026-09-05 — record `158`.** 프레임워크가 한 자리에서 `max(bound×1%, 10bp)`로 판정하고 기록이 `held`/`within_tolerance`/`breached`를 나눠 센다; constraint 코드 변경 0 | C6 |

### 2026-09-05 소유자 판정 — 아홉 중 다섯의 방향이 정해졌다

이 세션에서 소유자가 직접 내렸다. 각 이슈 파일의 `**Status:**` 줄이 여전히 authority이고 여기는
색인이다. **다섯 다 아직 열려 있다** — 방향만 정해졌고 구현은 안 됐다.

| # | 판정 | 한 줄 |
|---|---|---|
| `078` ✔ | 두 번째 절반: **거부하지 않는다** (record `155`, 2026-09-05) | 지불 가능 수량이 안 맞으면 한 단위 덜 사고 잔액은 현금으로 남긴다. 실제 펀드는 현금을 꽤 들고 운용한다. 첫 번째 절반(청구하는 채널에서 비용을 읽기)은 그대로 버그이고 더 무겁다 |
| `079` ✔ | **C — 데이터와 타입은 사용자 책임** (record `156`) | 스키마를 선언하게 하지 않고(A 기각), precision을 지목하지도 않는다(B 기각). 구분 못 하는 자리에서는 pyarrow 문장을 그대로 낸다. skill이 "연속량은 `float`"을 말한다 |
| `080` ✔ | **`081`의 선행 조건이 됐다** (record `157`) | 열거가 불완전한 채로 cascade를 얹으면 "보이는 것만 지우고 성공했다"가 된다 |
| `081` ✔ | **cascade를 만든다** (record `157`) | 삭제는 쉬워야 한다. `rm run --cascade`. 부분 실패는 되돌리지 않고 남은 것을 이름으로 보고한다. 작은 절반 둘(`list runs`의 고아 표시, `rm run-definition`의 payload)도 함께 |
| `085` ✔ ·`086` ✔ | **후한 허용오차 + 기록을 셋으로** (`085`는 record `156`, `086`은 `158`) | 기본 `max(bound × 1%, 10bp)`, override 가능. 판정은 `constraints/evaluation.py` 한 자리 — 기존 constraint·scaffold·저자 코드 **변경 0**. 기록은 `held`/`within_tolerance`/`breached`와 각각의 worst excess. `085`도 같은 규칙(카운터를 나눈다, `never_filled`를 성공 payload에) |

판정을 정한 수치: `086`이 실측한 오탐 최악 **0.01%p(1bp)** 대 같은 run의 진짜 위반 **4.89%p(489bp)**
— **489배**. 기본값 10bp는 잔여의 10배이고 진짜 위반의 1/49다. **절대 금액 기본값은 기각** — vqapr에
통화 개념이 없어(돈은 단위 없는 `Decimal`) `10000`이 북마다 다른 뜻이 된다. **lot에서 유도하는 안도
기각** — 산술적으로는 그쪽이 옳지만 `ConstraintCall`이 최소 권한 원칙으로 venue를 못 보게 되어 있고,
정확할 필요가 없는 임계값 하나 때문에 그 설계를 뒤집지 않는다.

파일로 만들지 않은 것: A2(`store_root`가 JSON에서는 문자열인데 `strategy_refs`는 `Path`를 요구한다
— skill 문구 한 줄, 보고자 본인이 결함에서 내렸다); A3(0.3.0 대비 실측 개선과 **숫자가 그대로
재현된다**는 확인 — `annual-fundamentals` 1,193초→6.2초, factor book 6개가 한 run `--jobs 6`으로
141초, SMB/HML/CMA와 RMRF 상관까지 0.3.0 수치와 일치); B4·C2·C3(잘 돼 있다는 기록 — `rm`의 참조
거부, `check.lookback.uncovered`가 답을 그대로 들고 있는 것, `terms_by_kind`+roster가 문서대로
동작하는 것). A4는 `084`의 뒷절로 들어갔다.

`086`을 쓸 수 있게 하려고 `authoring.py`와 `constraints/findings.py`의 `docs/issues/archive/086` 인용
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
| `027` `082` | **record `160`, 2026-09-05 (캠페인 Step 5, M5e).** `register`의 `spoken`; `list components --reads`; dataset의 `produced_by` |
| `086` | **record `158`, 2026-09-05.** 허용오차 기본 `max(bound×1%, 10bp)`(override는 `Constraint.tolerance`), 판정은 `StampedConstraintFinding` 한 자리, 기록은 `held`/`within_tolerance`/`breached`+각 worst excess, `ok`는 `breached`만 본다, monitoring 행에 `verdict`·`tolerance` — constraint·scaffold 코드 변경 0 |
| `080` `081` | **record `157`, 2026-09-05, 한 브랜치.** 열거 완비 뒤 cascade — datamodel 쪽이 strategy 쪽과 같은 세 상태(`completed`/`running`/`unfinished`)를 갖고 `rm datamodel`이 record 없는 디렉터리를 댄다(`080`); `list runs`의 `orphaned` 행, `rm run-definition`의 `records_remaining`, `rm run --cascade`(record → 정의 → materialized 출력 → component, 다른 run이 이름 대는 것은 `kept`로 보고)(`081`) |
| `079` `083` `084` `085` | **record `156`, 2026-09-05, 한 브랜치.** 거부와 요약이 사실만 말한다 — datamodel 스키마 불일치는 pyarrow 문장+확정 스키마를 인용하고 원인을 단정하지 않는다(`079`, 판정 C); `show model`이 못 그리는 kind를 구조화된 거부로 대고 `list components --kind`(`083`); run conflict의 `fix`가 `rm run-definition`을 대고 같은 문서의 producer run을 거부가 이름으로 댄다(`084`); `fill_summary`에 `never_filled`(`085`) |
| `078` | record `155` — 지불 가능 수량이 **청구하는 채널**에서 rate를 읽는다(`terms_by_kind`를 쓴 venue가 큰 주문을 낼 수 있다, `013`의 재발 차단); 보정은 lot 하나씩이 아니라 청구된 값으로 다시 푼다; 못 맞추면 거부가 아니라 **현금을 남긴다**(2026-09-05 소유자 판정) |
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
