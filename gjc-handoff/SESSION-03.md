> **이건 세션 3(`01a03479` 후반)의 기록이다. 새 세션은 `README.md`(START HERE)부터 읽는다.**
> 원본은 `../kwam-enhanced-index/gjc-handoff/SESSION-03.md`.

# SESSION-03 — vqapr agent-first surface

이 세션은 **원래 ultragoal이 낡았다는 결론**으로 끝났다. 새 세션은 원래 계획을
이어받지 말고, 아래 설계 결정에서 시작한다.

## 먼저 읽을 것

`docs/design/agent-first-surface.md` (commit `ad620dd`). 이 세션의 진짜
산출물이고, 원칙 7개와 그 근거가 들어 있다.

## 왜 원래 계획을 이어받으면 안 되는가

원래 ultragoal은 "legacy `vqapr.public`을 dogfooding으로 걷어내고 breaking
`0.2.0a1`을 낸다"였다. 소유자가 이 세션 중반에 방향을 바꿨다:

> 기준은 **AI agent가 잘 쓸 수 있느냐**여야 한다. backend를 만들고 frontend를
> 붙이는 게 아니라, user 관점에서 UI를 먼저 설계하고 그것을 backend에 어떻게
> 연결할지 고민하는 것이다.

그 결과 이 세션이 만든 것 상당수가 **위치가 틀렸다**는 판정을 받았다:

| 만든 것 | 판정 |
|---|---|
| `_internal/*_bridge.py` 7개 | 남발은 좋은 패턴이 아니다. 3개는 소멸 대상 |
| `factors_authoring.py`의 손으로 쓴 cadence 6군데 | periodic trigger는 공용 모듈 + config여야 한다 |
| `Simulation` 필드 7개 | 등록/실행 분리하면 ~4개 |

검증이 틀린 게 아니라 **만든 자리가 틀렸다.** 그래서 G008(삭제·릴리스)과 G010의
dogfooding 절반은 **G011 이후 다시 써야 할 계획**이다. 소유자가 이에 동의했다.

## 확정된 설계 결정 (소유자 ruling)

1. **YAML은 선언·등록, Python은 저작·실행.** `DataModel`/`StrategyModel`/(나중에)
   `Exchange`는 pluggable module이므로 Python. dataset 등록, 작성한 전략의 설치는
   YAML + CLI. 전략을 쓰는 건 Python, 방금 쓴 전략을 등록하는 건 CLI.
2. **bridge 남발은 smell.** 타입 A를 B로 바꾸려고 존재한다면 둘 중 하나가 잘못된
   자리에 있다.
3. **Exchange friction은 불가피.** 나중에 pluggable로 풀고, 그전까지 `Academic`과
   `KRX`는 최대한 adjustable해야 한다. `fractional_allowed`는 "빠진 필드 하나"가
   아니라 adjustability gap이었다.

## 소유자가 제시한 YAML 스키마 (아직 문서에 미반영)

`my_strategy_001.py` + `my_strategy_001.yaml`이 짝을 이룬다는 것을 경로와 함께
알려주고, 다음을 담는다:

- `DataRequirements`
- **periodic entry trigger** — 모든 전략이 쓰므로 모듈로 만들고 config로 설정
- **weight scheme** — dollar neutral(long 1, short -1) / flexible budget(long ≤1,
  short ≥-1) / long only
- **recorder table schema** — 어떤 schema의 table로 기록을 남길지

### 이 스키마가 드러낸 gap 2개 (측정 완료)

- `PortfolioDirection`에 `LONG_ONLY`, `SIGNED` **2개뿐**. dollar neutral과 flexible
  budget이 둘 다 `SIGNED`로 뭉뚱그려져 **이름이 없다.** `Budget`의
  `target_lower`/`target_upper`로 수치는 표현되지만 전략이 "나는 dollar neutral"을
  선언할 어휘가 없다.
- `DiagnosticTable`은 `table_id` + `semantic_fields` **2개뿐**. 필드에 **타입이
  없어서** YAML로 table schema를 정할 수 없다.

## 왜 `Simulation`이 커졌는가 (측정 결과)

`Project._engine_definition`은 **104줄 중 15줄이 등록 호출**이고, run마다 등록을
5번 한다. 즉 `Simulation`은 **한 번 정해지는 것**과 **run마다 달라지는 것**을 같이
들고 있다.

`cli/register.py`의 `SECTIONS`는 이미 `datasets`, `execution_inputs`, `agendas`,
`components`, `strategy_configs`, `valuation_configs`, `monitoring_policies`를
이해한다 — **`Simulation`이 재선언하는 것과 정확히 같은 7개.** 선언 경로는 이미
있고 `Simulation`이 복제하고 있다. 새 기계가 아니라 중복 제거다.

## 버려지지 않는 것

- **testbed parity 증명** — 5개 factor 전부, weight **636,324개** 소수점까지 일치,
  Kimchi correlation 5개 6자리까지 일치 (.971509 / .972553 / .941883 / .917683 /
  .984659). 표면이 바뀌어도 이 숫자는 기준으로 남는다.
- **결함 9개의 목록** — 전부 표면을 *써보다* 막혀서 나왔고, 읽어서 찾은 건 하나도
  없다. 설계 요구사항의 근거다.
- `catalog.py` / `publication.py` / `objects.py` — engine 쪽이고 ruling과 무관.
- `loading.py`의 authoring 모델 적응 — scaffold와 agent/sample을 두 번 막던 커플링.
- `vqapr-testbed-2/parity_probe.py` — 재현 가능한 검증 도구.

## 구조 측정 (삭제 가능성 판단 근거)

- `public.py`는 **419줄, 자체 정의 11개**, 28개 모듈에서 re-export
- **engine 파일 중 이걸 import하는 것은 0개** — `flow/`, `models/`, `portfolio/`,
  `valuation/`, `exchange/`, `data/` 전부 깨끗
- 의존은 한 방향: public → engine
- 진짜 legacy 소비자 6개: `agent/sample/{exchange,journey}.py`,
  `cli/{register,run}.py`, `extension/scaffold.py`, `project.py`

따라서 점진적 제거가 가능하다. dogfooding 하나 끝낼 때마다 legacy 하나씩. 다만
**설계가 정해진 뒤에** 해야 두 번 안 한다.

## 상태

- qlibx `d23ca03` → `ad620dd`, **12 commits**, working tree clean, **1,036 passing**,
  ruff clean
- kwam-enhanced-index **9 commits**
- **push 안 함, tag 없음**
- showcase 3/8 마이그레이션 (001, 002, 004)

## 알려진 문제

goal 기계가 G010을 놓지 않는다. `pause` 4회, `drop` 1회 모두 거부됐다
("an active story still has resolvable work"). 소유자가 새 세션 시작을 제안했고
그게 출구다. 이 세션의 ledger는
`.gjc/_session-01a03479-6572-71ee-a423-897459b75deb/ultragoal/ledger.jsonl`에 남아
있으며 증거는 전부 거기 있다.

## 다음 세션의 첫 작업

설계 문서에 소유자의 YAML 스키마를 정식 반영하고, 위 gap 2개(weight scheme 어휘,
table schema 타입)를 요구사항으로 박는다. 그 다음 `Simulation`의 등록/실행 분리.
코드 마이그레이션은 그 이후다.

미확인 질문 하나: **strategy config가 YAML 등록에 들어가나, run 시점에 오나.**
잠정 답은 run 시점 — `FactorPortfolio` 하나를 5개 factor로 돌리는 게 testbed의 실제
사용 패턴이고, YAML에 config를 넣으면 같은 클래스를 5번 등록해야 한다.
