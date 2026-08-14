# Handoff — vqapr, 데이터 등록 표면

Branch: `exp/3rd-attempt`
마지막 커밋: `3ae08ce` (슬라이스 3 완료)

이 문서는 **이어받는 agent가 대화 기록 없이** 계속할 수 있도록 쓴 것이다. 권위는 여전히
`docs/vqapr-prd.md`(제품)와 `docs/vqapr-architecture.md`(설계)에 있다. 이 문서와 그 둘이
어긋나면 그 둘이 맞다.

---

## 1. 일하는 방식 — 이것이 가장 중요하다

**사용자는 당신이 작성한 코드를 직접 읽지 않는다.** 코드를 보여주며 설명하지 말고 **증거를
만들어 보여줘야 한다.** 이것은 취향이 아니라 이 프로젝트의 작업 규약이다.

### 모든 슬라이스는 세 겹의 증거로 끝난다

| | 무엇 | 어디 |
|---|---|---|
| ① | **실데이터 시나리오** — 성공과 실패를 나란히 돌려 출력한다 | `scripts/evidence_*.py` |
| ② | **픽스처 테스트** — 실데이터 없이 도는 것이 대부분이어야 한다 | `tests/` |
| ③ | **주장을 관측 가능하게** — 코드를 읽어야만 확인되는 주장을 남기지 않는다 | 반환값·타입 |

③이 잘 드러나는 예가 있다. *"1단계가 실패하면 2단계 전체 스캔을 건너뛴다"*는 주장을
`ValidationTiming.key_was_skipped`로 **반환값에 실었다.** 그래서 테스트가 단언할 수 있고 증거
스크립트가 출력할 수 있다. 그렇게 하지 않았다면 그 주장은 코드를 읽는 사람만 확인할 수 있다.

### 실패 시나리오가 성공만큼 중요하다

첫 사용자가 agent이므로 **실패는 읽는 것이 아니라 파싱하는 것**이다. 증거 스크립트는 실패가
`as_dict()`로 어떻게 나오는지도 보여줘야 한다.

### 데이터를 과하게 파헤치지 마라

이 세션에서 한 번 잘못했다. 등록하려고 데이터를 보다가 품질 감사로 빠졌는데, **전략도 정하지
않은 시점에 체결 데이터 품질을 따지는 것은 순서가 뒤집힌 것**이다. PRD §4.3의 progressive
requirement discovery가 명시적으로 거부하는 방식이다 — 등록은 등록에 필요한 것만 보고,
나머지는 그것을 요구하는 operation이 실패시킬 때 고친다.

---

## 2. 지금까지 선 것

```text
domain/errors.py       VqaprError · Failure · Diagnosis · collector · FailureFamily
domain/identifiers.py  DatasetId · SourceId · InstrumentId
data/sources.py        SourceSpec (path · hive_partitioned)
data/scan.py           describe() · key_check() · ColumnType
data/datasets.py       DatasetRegistration · check_schema() · check_key() · validate()
```

검증됨: 46 tests (실데이터 없이 42), ruff check/format 통과.

### 개발용 실데이터

```bash
uv run --with pytz python scripts/prepare_dev_data.py     # 약 3초
```

`data/DW/fng_stock_daily_prices.csv` (721MB) → `data/vqapr-dev/price_daily/year=*/` (220MB,
8,709,828행, 5,670종목, 2,833세션, 2015-01-02~2026-07-20). `/data/`는 gitignore라 커밋되지
않는다. **이 변환은 package가 아니라 user 쪽 일을 흉내 낸 것이다**(PRD §4.0).

### 증거 재실행

```bash
uv run python scripts/evidence_scan.py       # 슬라이스 1·2, 8개 시나리오
uv run python scripts/evidence_register.py   # 슬라이스 3, 7개 시나리오
uv run pytest -q                             # 46 passed
uv run pytest -q -m "not real_data"          # 42 passed — 실데이터 없이
```

---

## 3. 다음 작업 — 슬라이스 4 `workspace.py`

**목표**: 검증된 선언이 명령 사이에 살아남는다. `register` → 프로세스 종료 → 다시 열어 조회하면
같은 선언이 나온다.

설계는 architecture §10.5에 있다. 요점만:

- 한 project가 축적한 **선언 집합**을 보관한다 — 지금은 등록된 dataset, 나중에 frozen
  `SessionCalendar` · `ComponentRef` · Exchange config
- **전역이 아니다.** 명시적으로 전달한다. `qlib.init()` 같은 process-global provider는
  PRD §12.5가 금지한 것이며, 있으면 동시 run이 서로의 설정을 본다
- **검증하지 않는다.** 무엇이 유효한 선언인지는 각 타입이 안다. 여기는 보관과 조회만

### 정해야 할 것 둘

**① 어디에 저장하나.** 제안은 project root의 `.vqapr/workspace.yaml`이다 — 도구가 소유하는
숨은 디렉터리라 사용자 파일과 섞이지 않고, `pyyaml`이 이미 의존성에 있다. 확정 전에 사용자에게
확인할 것.

**② 재등록 규칙.** 같은 `dataset_id`로 다시 register하면 어떻게 되나. **아직 정해지지 않았고
슬라이스 4가 마주치는 첫 문제다.** agent는 재시도를 많이 하므로 자주 발생한다. 후보:

- 같은 선언이면 idempotent하게 통과
- 다른 선언이면 실패시키고 명시적 `--replace`를 요구
- 무조건 덮어쓰기 (권장하지 않음 — 무엇이 바뀌었는지 흔적이 없다)

architecture §4.6이 *"identity는 선언이지 파일 내용이 아니다"*라고 정했으므로, **선언이 같으면
같은 dataset이고 다르면 다른 것**이라는 기준은 이미 있다. 그 위에서 정하면 된다.

### 슬라이스 4의 증거로 보여야 하는 것

```text
성공   register → 새 프로세스 → 조회하면 같은 선언
성공   dataset 두 개를 등록하고 둘 다 조회된다
실패   같은 dataset_id 재등록 (위 ②에서 정한 대로)
실패   workspace가 없는 경로 / 손상된 yaml
확인   workspace 인스턴스를 전역에서 가져오는 경로가 없다
```

### 그 다음 (슬라이스 5)

`public.py`에 `register_dataset()` 하나. `UC-FACADE-001`의 최소 형태 — 내부 module을 import하지
않고 등록이 되는지. `cli/data.py`는 그 위의 얇은 껍질이라 나중에 붙여도 된다.

---

## 4. 되돌리면 안 되는 결정

각각 이유가 있고 대부분 비싸게 배운 것이다.

| 결정 | 왜 |
|---|---|
| **`VqaprError`가 `Failure` 여럿을 담는다** | agent가 자기 준비를 고치려면 문제를 한 번에 다 받아야 한다. 하나씩이면 왕복이 다섯 번 |
| **예시는 생성 시점에 잘린다** (`Failure.bounded`) | 원천이 8.7M행이라 잘못된 key 선언은 대부분의 행에 걸린다. `example_total`을 따로 남겨 표본인지 전부인지 구분 |
| **`mutation` 필드를 지금부터 갖는다** | 등록에선 항상 `False`라 쓸모없어 보이지만, commit 이후 실패하는 단계가 생겼을 때 뒤늦게 붙이면 그것 없이 짜인 호출부를 전부 고쳐야 한다 |
| **duckdb 타입 문자열을 위로 안 올린다** | `ColumnType`으로 정규화. backend를 바꿀 때 검증이 깨지지 않아야 한다(§4.6) |
| **`TIMESTAMP_TZ` vs `TIMESTAMP_NAIVE`를 가른다** | 이 enum의 존재 이유다. naive는 저장도 조회도 완벽히 되면서 **조용히 틀린다.** 등록이 그것을 잡을 수 있는 유일한 자리 |
| **검증이 두 단계** | 스키마는 값싸니 전부 모아서, key는 전체 스캔이라 스키마 통과 후에만. 없는 컬럼 때문에 8.7M행을 읽지 않는다 |
| **`instrument_id`가 경로 구분자를 허용** | NYSE는 `BRK/B`를 준다. 문자를 막으면 그 시장을 못 쓴다. 공백만 거부 |
| **`available_at`은 컬럼이지 규칙이 아니다** | user가 준비 단계에서 계산해 넣는다. 규칙을 config로 받아 평가하지 않고, 어떤 가정이었는지 기록하지도 않는다(PRD §4.0) |
| **`hive_partitioned`는 장식이 아니다** | 선언하지 않고 읽으면 파티션 키가 컬럼으로 살아나지 않고 가지치기도 없다 |

---

## 5. 알고 있으나 **지금 고치지 않기로 한 것**

개발용 데이터를 만들며 눈에 걸린 것들이다. **전부 등록을 막지 않는다.** 그것을 요구하는
operation이 나올 때 실패시키는 것이 PRD §4.3이다. 다시 발견하느라 시간 쓰지 말 것.

```text
거래정지구분에 NULL 57,956행      체결 테이블을 만들 때 결정해야 한다
J접두사 708종목 (ELW로 보임)       가격 계보가 달라 대부분 컬럼이 비어 있다
종가 <= 0 인 375행 (전부 J접두사)  execution이 그 종목에 닿을 때 문제가 된다
거래량 0 인 393,016행              `거래대금 > 0`을 tradability로 쓰면 정지와 뒤섞인다
                                   (실제 정지 221,331행과 양방향으로 어긋난다)
2016-08-01에 종가 시각 15:00→15:30  현재 전 구간 15:30. 907,818행이 30분 늦게 잡힌다.
                                   보수적 방향이라 look-ahead는 아니다
```

---

## 6. 열려 있는 설계 질문

architecture §15에 있는 것 외에, 구현하며 새로 열린 것.

- **`flow/stamping.py`의 materialize stage 이름.** DataModel materialization이 recorder 행에 찍을
  `stage` 값이 §3.2 어휘에 없다. 후보는 `MATERIALIZE` 추가 또는 `DATA_AVAILABLE` 사용.
  recorder를 쓰는 DataModel이 실제로 나올 때 정한다.
- **§10 트리가 기계 검증 가능한 형태가 아니다.** 대부분 한 줄에 파일 하나인데 `cli/`와
  `testing/`만 압축 표기(`main · new · check …`)라 파서가 못 읽는다. §16이 트리 준수를
  체크리스트로 요구하므로 통일해두면 좋다.

---

## 7. 작업 규약

`AGENTS.md`와 `.agent/project.yaml`을 먼저 읽을 것. 요점:

- 커밋은 **사용자가 명시적으로 요청할 때만**. push는 아직 한 번도 하지 않았다
- 커밋 메시지는 무엇을 왜 바꿨는지를 산문으로. 이 브랜치의 기존 커밋들이 그 형식이다
- production source가 바뀌면 implementation record가 필요하다 (`docs/implementations/`).
  문서·실험·showcase 전용 변경은 예외
- `uv`를 쓴다. 별도 venv를 만들지 말 것
