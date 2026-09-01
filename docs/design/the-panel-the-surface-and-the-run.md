# The panel, the surface, and the run — 아키텍처에 없는 세 개의 명사

| | |
|---|---|
| **작성 시각** | 2026-09-01 KST (+09:00) |
| **상태** | **제안. `src/`는 이 문서로 인해 움직이지 않았다.** 세 항목은 소유자 결정이 났다 — §7-1 (lookback 이름), §7-3 (`grain` 미선언은 거절), §7-4 (계정 비공유), 그리고 §6의 착수 순서 |
| **근거** | `docs/vqapr-architecture.md` §17 — 소유자 mental model 열 개와 트리의 대조 |
| **판정 기준** | `docs/vqapr-prd.md` → `docs/vqapr-architecture.md` → `docs/design/agent-first-surface.md` |
| **선례** | `docs/design/agent-first-surface.md`. 그 문서처럼, 승인되면 architecture가 이것을 흡수한다 |

---

## 0. 왜 이 문서가 있는가

§17이 소유자 mental model 열 개를 트리와 대조했고 **넷이 "없음", 둘이 "어긋남"**이었다.

그 여섯은 서로 다른 여섯 개의 결손이 아니다. **아키텍처에 세 개의 명사가 없어서 생긴 여섯 개의
증상**이다. 이슈로 하나씩 닫으면 여섯 번 고치고 여섯 번 다시 열린다 — `049`가 `035`·`044`·`045`를
따로 랭킹하면 각각 "적당한 최적화"로 읽힌다고 지적한 것과 같은 종류의 mis-triage다.

이 문서는 그 세 명사를 설계한다. **구현 계획이 아니라 behavior 계약이다.**

**범위 밖.** 코드. 읽기 경로 캠페인(레인 C/D)은 이 문서와 독립으로 계속 간다 — 접점은 §6에 적는다.

---

## 1. 진단 — 열 개의 증상, 세 개의 명사

| §17 | 증상 | 없는 명사 |
|---|---|---|
| 1.1 · 1.2 | grain을 선언할 수 없고, date x ticker 유일성을 물을 수 없다 | **Panel** |
| 1.3 | 창은 evaluation마다 파일에서 다시 잘린다 | **Panel** |
| 1.4 | 프로세스마다 자기 duckdb를 연다. 공유할 대상이 없다 | **Panel** |
| 9 · 10 | lookback의 축이 종목별과 표 기준으로 갈린다 | **Panel** |
| 2 · 8 | 저자 표면이 둘, 같은 이름 다른 클래스가 셋 | **Surface** |
| 3 · 3.1 · 3.2 | run 하나가 설정이자 실행이자 기록이다 | **Run** |
| 4 · 5 · 5.1 · 6 | 전략 축이 없어 이력도 삭제도 검색도 안 된다 | **Run** |

**세 명사는 독립이 아니다.** Run이 universe와 period를 고정하기 때문에 Panel 집합이 결정되고, Panel이
공유 가능하기 때문에 한 Run 안의 여러 전략을 병렬로 도는 것이 비로소 **이득**이 된다. Surface가
하나여야 두 종류의 Model이 그 Panel을 같은 문장으로 읽는다.

---

## 2. 명사 1 — `Panel`

### 2.1 오늘 없는 것

데이터 평면은 두 층이다: **선언**(`DatasetRegistration`)과 **창**(`observation_rows`). 사이에 **표가
없다.** 그래서 창은 매번 파일 위에서 다시 계산되고, `049`가 잰 것이 그 대가다 — 같은 모델, 같은 출력,
**806.61s 대 1.31s**, `compute`는 양쪽 다 0.36s. **연산이 1.9%이고 데이터를 옮기는 것이 98%다.**

한 층을 끼운다.

```
Source (parquet)  ->  Dataset (선언: grain + 표현식 field)
                  ->  Panel   (물질화된 2d 표. 불변, 공유 가능, run보다 오래 산다)
                  ->  Window  (Panel의 슬라이스: lookback x instruments. 복사가 아니다)
```

### 2.2 grain은 유도하지 않고 선언한다

```yaml
datasets:
  equity-daily:
    grain: instrument_instant
    source_id: krx-equity
    path: data/equity_daily.parquet
    available_at: available_at
    instrument_field: ticker
    fields:
      adj_close: adj_close_price
```

| `grain` | 뜻 | 등록이 검사하는 것 | panel |
|---|---|---|---|
| `instrument_instant` | (available_at, instrument)당 field별 값 하나 | **그 쌍의 유일성** — §17.1.2가 요구한 검사 | 가능 |
| `instant` | available_at당 값 하나, instrument 축 없음 (`docs/issues/038`) | available_at의 유일성 | 가능 (1열) |
| `rows` | vendor grain. long / EAV | 선언된 `key_fields`의 유일성 — 오늘과 같다 | **불가** |

- **선언이지 유도가 아니다.** 레인 C의 `aggregated`는 long source에서 `instrument_instant`에 *도달하는
  수단*(집계 표현식)이지 grain 자체가 아니다. 유도된 사실은 저자에게 의도를 말할 자리를 주지 않는다 —
  long으로 등록해 놓고 왜 600배 느린지 모르는 것이 `049`의 이야기 전부다.
- `key_fields`는 남는다. `rows` grain에서는 그것이 유일성의 축이고, panel grain에서는 **provenance**다
  (이 표의 원래 grain이 무엇이었는지).
- **`grain`을 안 쓴 등록은 거절한다.** 세 값을 이름으로 대면서, 그리고 `RowsLookback`의 뜻이
  바뀌었다는 것을 같이 말하면서. **한 릴리스의 관대한 decode는 두지 않는다** — §7-1이 이름을
  재사용하기로 한 순간 그 경로가 안전하지 않게 되었다. 근거는 §2.4의 마지막 소절과 §7-3.

**SKILL.md의 권유가 바뀐다** (§17.1.1). date x ticker로 매핑되는 표는 `instrument_instant`로 등록한다.
vendor grain을 보존해야 하면 **둘 다** 등록한다 — 정직한 `rows` 하나와, 그 위에서 DataModel이 만든
`instrument_instant` 하나. *"붕괴 결정은 리뷰 가능한 component에 남아야 하고 ETL에 묻히면 안 된다"*는
`049`의 논거는 그대로 살아 있다. 바뀌는 것은 **그 두 번째 등록이 예외가 아니라 권장 경로**가 되는 것뿐이다.

### 2.3 Panel은 정체성과 수명을 가진 객체다

```
Panel identity = sha256(source_digest, dataset_id, field_id, instruments, span)
```

- 불변, read-only, 2차원(instant x instrument), **columnar**.
- **run이 아니라 cache가 소유한다.** 두 층:
  - **in-process** `PanelCache` — 같은 프로세스의 두 전략이 같은 객체를 본다.
  - **on-disk spill** — `.vqapr/panels/<identity>.arrow`. N개 프로세스가 read-only로 mmap한다.
    힙은 프로세스를 못 넘지만 **mmap된 Arrow 버퍼는 넘는다.** §17.1.4를 실제로 참으로 만드는 것은
    이쪽이고, in-process cache만으로는 `vqapr run` 다섯 개가 여전히 다섯 벌을 만든다.
- spill은 **결정적 바이트**다. identity가 digest이므로 두 프로세스가 동시에 같은 것을 만들어도 같은
  파일이고, 그 경합은 `_internal/atomic.py`의 durable write가 이미 아는 문제다.
- **`docs/issues/035`가 여기서 같이 닫힌다.** panel이 이미 columnar이므로 *"행 dict 대신 열 배열"*은 새
  작업이 아니라 panel을 그대로 노출하는 것이다. **1.3 · 1.4 · 035는 세 개의 변경이 아니라 하나다.**

**비용.** 1,600 종목 x 2,500 instant x 8바이트 = field당 **32MB**. field 10개면 320MB. `049`의
`pivot_experiment`가 잰 한 창 읽기는 **10.19s -> 0.048s**다.

### 2.4 Lookback은 grain을 따라 두 갈래가 된다

§17.9의 갈림은 semantics 논쟁이 아니라 **타입이 하나뿐이라 생긴 것**이다. 두 질문 다 정당하고, 서로
다른 grain에 속한다.

**소유자 결정 2026-09-01.** 이름은 아래와 같다.

```
PanelLookback     — panel grain 전용. wide 표의 행을 센다. 모든 이름에 같은 창
  |- CalendarLookback(years, months, days, tz)   시간 경계             (오늘 그대로 — §17.10)
  |- RowsLookback(n)                              마지막 N개 행         (§17.9의 진술)

SeriesLookback    — rows grain 전용. 이름별 시계열
  |- InstantsLookback(n)                          그 이름이 보고한 마지막 N개 instant
```

**이 이름들은 각 grain의 고유 단위를 따른다.** pivot된 표의 단위는 **행**이다 — 한 행이 한 instant이고
모든 이름이 그 행을 공유하므로 `RowsLookback(313)`은 정의상 313개 instant다. long 표에는 공유되는
행이 없다: 이름마다 자기가 보고한 **instant**들이 있고 그 집합이 서로 다르므로, 거기서 세는 단위는
`InstantsLookback`이다. 나중에 읽는 사람이 이 이름을 "뒤집힌 것 같다"고 고치지 않도록 근거를 여기
적어 둔다.

- **타입이 steering을 한다.** `grain: rows` dataset은 `PanelLookback`을 받지 않고, panel dataset은
  `SeriesLookback`을 받지 않는다. 등록이, 그리고 preflight가 거절한다.
- 그래서 **architecture §4.2의 논거도 `033`의 소유자 확인도 무효화되지 않는다.** 항목마다 공시 주기가
  다른 재무를 이름별로 세는 것은 여전히 옳고 여전히 가능하다. 바뀌는 것은 **cross-section 모델이 그것을
  실수로 집을 수 없다**는 것뿐이고, 그게 `033`의 실제 불만이었다 — 033은 semantics 버그가 아니라
  steering 버그로 닫혔고, 이것이 그 steering을 문서가 아니라 **타입**으로 옮긴다.
- `033`이 잰 사고(313행 요청에 1,865 세션, 상장폐지된 이름이 자기 2016년을 끌고 옴)는 **타입으로
  불가능해진다.** panel 위의 `RowsLookback(313)`은 313개 행이고, 이름별로 세고 싶으면 `rows` grain에서
  `InstantsLookback`을 쓴다.

#### `RowsLookback`이 뜻을 바꾼다 — 그리고 그것이 조용하면 안 된다

이 결정의 유일한 실제 위험은 여기다. **오늘 `RowsLookback(313)`이라고 쓰인 모든 등록이 내일 다른
뜻이 된다.** 균형 잡힌 패널에서는 두 뜻의 결과가 같아서 (033의 stage one이 정확히 그 착시였다)
어긋남이 테스트로도 안 잡힌다. 캠페인 §6의 첫 번째 위험 — *green tree, 옮겨진 지표* — 이 그 모양이다.

**막는 방법은 이름이 아니라 `grain`이다.**

1. `grain`을 안 쓴 등록은 **거절**한다 (§7-3이 이 결정 때문에 관대한 쪽에서 뒤집혔다). 그래서 모든
   기존 등록은 **저자가 한 번은 손으로 편집한다.**
2. 그 편집 순간에 나오는 거절 메시지가 **두 가지를 같이 말한다**: 세 grain 중 무엇인지, 그리고
   *"`grain: instrument_instant`를 고르면 이 dataset 위의 `RowsLookback`은 이름별이 아니라 표의 행을
   센다"*.
3. `grain: rows`를 고르면 그 dataset 위의 `RowsLookback`은 **타입 오류**가 되어
   `InstantsLookback`을 이름으로 대며 거절한다. 오늘의 뜻을 유지하려는 저자는 자동으로 거기 도착한다.

**어떤 경로로도 같은 코드가 조용히 다른 뜻이 되지 않는다.** 이것이 이 이름 선택을 안전하게 만드는
유일한 장치이므로, `grain` 거절과 이 이름 변경은 **같은 릴리스에 같이 들어가야 하고 따로 나갈 수 없다.**

### 2.5 Model이 받는 창

```python
# panel grain — 2d 슬라이스
w = call.read("equity-daily", "adj_close")
w.instants       # tuple[datetime, ...]   — 모든 이름에 공통
w.instruments    # tuple[str, ...]
w.values         # 열 단위 2d
w.latest()       # 이름당 마지막 값

# rows grain — 오늘의 행 스트림, 그대로
for row in call.rows("statement-facts", "value"):
    ...
```

- panel 뷰는 **복사가 아니라 슬라이스**다. lookback은 instant 축의 두 인덱스이고 instrument는 열
  선택이다. 읽기 경로가 아무것도 검증하지 않는다는 레인 A의 계약이 여기서 자연스럽게 유지된다 —
  검증할 셀을 만들지 않기 때문이다.
- `rows` grain은 오늘의 dict 스트림을 그대로 둔다. 지울 이유가 없다: vendor grain을 정직하게 읽는
  유일한 모양이다.

### 2.6 닫는 것과 닫지 않는 것

- **닫는다:** §17.1.1, 1.2, 1.3, 1.4, 9, 10. `docs/issues/035`, `045`(어느 행이냐가 grain 선언으로
  흡수된다), `046`.
- **닫지 않는다:** `rows` grain의 읽기 비용. 그것은 grain의 성질이다. 이 설계가 하는 일은 저자가
  **그 비용을 골랐다는 것을 알게** 만드는 것이다.

---

## 3. 명사 2 — 하나의 저자 표면

### 3.1 `vqapr.authoring`이 표면이다

- `vqapr.public`은 **동사**를 갖는다: 등록, 실행, 분석. 그리고 authoring의 이름을 **동일 객체로**
  재수출한다 — `public.DataModel is authoring.DataModel`이 참이 되고, §17.8이 확인한 세 쌍의
  같은-이름-다른-클래스가 사라진다.
- 이것은 `agent-first-surface.md` Principle 5의 연장이다. 그 문서가 *"YAML이 선언하고 Python이
  저작한다"*를 정했고, 여기서 정하는 것은 **그 Python이 한 모듈이라는 것**이다.

### 3.2 공통 base가 저자 쪽에 생긴다

```python
class Model(ABC):                 # authoring.Model
    def inputs(self) -> Mapping[str, DatasetInput]: ...
    def diagnostics(self) -> tuple[DiagnosticTable, ...]: ...
    # state / memory

class DataModel(Model):           # account 없음, venue 통과 없음
    def output(self) -> Output: ...
    def compute(self, call: DataCall) -> Sequence[DerivedRow]: ...

class StrategyModel(Model):       # account 있음, venue 통과함
    def account_history(self) -> tuple[AccountHistoryInput, ...]: ...
    def decide(self, call: StrategyCall) -> StrategyResult: ...
```

- §17.2의 진술이 **클래스 차이 그 자체**가 된다: *account가 달려서 exchange venue execution을 거치면
  StrategyModel, 아니면 DataModel.* 나머지는 전부 `Model`이다.
- `DataCall`과 `StrategyCall`이 공통 `Call`을 공유하고 `read`/`rows`가 **같은 동사**다. `036`의
  대조표가 행 단위로 사라진다 — import, 선언 메서드, 요구 타입, 행 접근, timestamp 가시성 전부.
- `_internal/pit_bridge.py`와 `_internal/strategy_bridge.py`는 **자기 docstring이 적어 둔 조건대로**
  삭제된다: *"That is the next convergence, and when it lands this file has nothing left to do."*

### 3.3 scaffold는 한 가지 문법만 가르친다

세 scaffold(strategy · datamodel · constraint)가 같은 import, 같은 선언 메서드, 같은 read 동사를
emit한다. `agent-first-surface.md`가 *"Open consequence"*로 남겨 둔 것 — 패키지가 없애려는 ceremony를
scaffold가 가르친다 — 이 여기서 닫힌다.

---

## 4. 명사 3 — Run은 설정이고, strategy record는 output이다

오늘 "run"이라는 한 단어가 세 가지 일을 한다: **실험 설정**, **시험 대상 전략**, **한 번의 실행
기록**. §17의 3 · 3.1 · 3.2 · 4 · 5 · 5.1 · 6이 전부 그 겹침의 증상이다.

### 4.1 Run은 등록되는 재사용 객체다

```yaml
runs:
  krx-2015-2024:
    instruments_from: krx-roster
    start: 2015-01-01T00:00:00+09:00
    end:   2024-12-31T00:00:00+09:00
    valuation: daily-close
    exchange: krx-costed
    execution_input: krx-close-fill
    initial_account: {cash: 1000000000, mode: long_only}
    strategies:
      ou-k0:   {agenda: krx-rebalance, constraints: [no-short]}
      ou-pca5: {agenda: krx-rebalance, constraints: [no-short]}
      ou-ff5:  {agenda: krx-rebalance, constraints: [no-short]}
```

- `vqapr register` 가 run을 workspace에 넣는다. **재사용의 단위가 파일이 아니라 등록된 이름**이 된다.
  오늘은 `cli/run.py`가 호출마다 spec을 읽어 `RunDefinition`을 새로 만든다 (§17.3).
- `vqapr run krx-2015-2024 [--strategy ou-ff5] [--jobs 3]`
- **`docs/issues/040`이 이 설계의 전제조건이다.** 세 전략이 같은 agenda를 가리켜야 하고, 오늘은 agenda가
  전략 하나만 구동한다. 040의 ruling(agenda는 공유 가능하다)이 먼저 들어와야 한다.
- `FrozenRun`이 둘로 갈린다:
  - **run 층** — universe, period, venue, execution input, initial account, agenda. 전략들이 공유한다.
  - **전략 층** — component, config, constraints, requirements. 전략마다 하나.

  preflight는 run 층을 한 번, 전략 층을 전략마다 언다. 오늘의 preflight가 이미 그 두 집합을 따로
  들고 있다 (`strategy_requirements`와 `constraint_requirements`가 이미 분리되어 있다).
- **panel 집합이 여기서 결정된다.** preflight가 이미 모든 requirement를 모으고 source를 얼린다
  (`flow/preflight.py:516` 이하). `vqapr prepare <run>` = preflight + panel 물질화. 그 다음 N개 전략이
  mmap된 바이트 위에서 돈다. **§17.3과 §17.1.4는 같은 기능이다.**

**각 전략은 자기 Account를 가진다** (소유자 결정, §7-4). 계정을 공유하면 그것은 세 전략이 아니라 한
전략이고 병렬로 돌 수도 없다. Run이 공유하는 것은 *초기* 계정 **선언**이지 계정 자체가 아니다.

### 4.2 기록은 둘이다

```
.vqapr/runs/<run-id>/
  run.json                      설정 — instruments, period, venue, execution input,
                                account 선언, agenda, 그리고 이 run이 시도한 전략 목록
  strategies/
    ou-ff5@3f2a91c8/            <strategy-id>@<fingerprint 앞 8자리>
      strategy.json             component ref (id, path, fingerprint, config digest),
                                계약 보고, source_digest, 실제로 커버한 기간, roster
      signal.jsonl              저자가 선언한 진단 표
      weight.jsonl              vqapr.weight   — 목표 비중
      account.jsonl             vqapr.account  — 측정. NAV의 원천
      fill.jsonl                vqapr.fill     — 미체결도 사유와 함께
    ou-ff5@9c04b1e7/            같은 전략, 다른 tweak
    ou-k0@11d3ae5b/
```

- §17.6의 진술 그대로다. run 기록은 *"어느 기간에 어떤 설정으로"*, strategy 기록은 *"돌린 그대로의
  output"*.
- **디렉터리 이름이 §17.4를 닫는다.** `ou-ff5@*`를 세는 것이 *"이게 몇 번 tweak한 전략인가"*의 답이다.
  접힌 digest를 파고들 필요가 없고, exchange 변경과 섞이지도 않는다 — fingerprint가 **그 component
  하나**의 것이기 때문이다 (`extension/fingerprint.py`는 이미 파일 bytes + kind + object_name + config를
  접는다. config가 preimage에 있으므로 *"조건만 약간 바꿔서"*가 정확히 새 디렉터리를 만든다).
- strategy record는 **content-addressed**다. 같은 run + 같은 fingerprint를 다시 돌리면 같은 디렉터리이고,
  조건을 바꾸면 **옆에 새로 생긴다.** 데이터가 바뀌었으면(`source_digest` 불일치) 거절하고 두 digest를
  이름으로 댄다 — 오늘의 `--force`가 그 자리를 그대로 이어받는다.
- `run.json`이 **execution input id를 든다.** `docs/issues/034`가 여기서 닫힌다: run이 자기가 어떤 체결
  규약을 썼는지 말할 수 있게 된다. §17.7이 지적한 유일한 결손이다.
- `declared_digest` / `source_digest`는 남는다. **접힌 값이 아니라 component별로** 남고, 둘의 차이가
  *"등록 이후 편집되었다"*를 말하는 receipt라는 `009`의 결정은 그대로다.

### 4.3 CLI

```
vqapr list runs        [--id ...] [--since ...] [--strategy ...]
vqapr list strategies  --run krx-2015-2024 [--strategy ou-ff5] [--fingerprint 3f2a]
                       [--failed-contract] [--since ...]
vqapr show  run        <run-id>
vqapr show  strategy   <run-id>/<strategy-id>@<fp> [--table weight] [--limit N]
vqapr rm    strategy   <run-id>/<strategy-id>@<fp>
vqapr rm    run        <run-id> [--keep-latest]
```

- **filter는 새 I/O를 만들지 않는다.** `_runs`가 이미 `read_record`로 record 전체를 읽고 네 필드만 쓰고
  버린다 (`cli/list_.py:106`). §17.5.1이 못 하던 질문들은 필드가 없어서였지 스캔이 비싸서가 아니었다.
- **삭제 기계는 이미 있다.** `RunRecordWriter._clear`가 그 id의 lock을 이긴 뒤에만 지우고, heartbeat가
  살아 있는 run을 보호한다. **verb만 없다** — 소스가 직접 그렇게 적어 두었다 (§17.5).
- **인덱스 파일은 여전히 만들지 않는다.** `run-record-layout.md`의 논거(동시 writer가 서로의 항목을
  지울 공유 대상을 만들지 않는다)는 그대로 유효하고, 디렉터리 이름이 이제 질문의 절반을 답한다.

---

## 5. 무엇이 안 바뀌는가

명시적으로 적는다 — 이 목록이 없으면 "아키텍처 재설계"가 척추까지 열린 것으로 읽힌다.

- **척추.** `optimize`, `plan_orders`, `Account.prepare_fill`, `Fill.__post_init__`.
- **시간.** agenda / occurrence 모델, 네 개의 시계, frozen input, warm-up과 atomic callback acceptance.
- **PIT 규칙.** `available_at`은 컬럼이지 규칙이 아니다. 모든 lookback은 과거 방향이다. field는
  표현식이지 statement가 아니다 — **look-ahead가 문법으로 막힌다는 성질을 이 문서는 건드리지 않는다.**
- **Evidence 계약.** 선언되지 않은 진단 표는 거절한다. 거절 코드는 closed set이다.
- **읽기 경로는 아무것도 검증하지 않는다** (레인 A). Panel이 그것을 더 쉽게 만든다.

바뀌는 것은 셋뿐이다: **데이터가 어떻게 도착하는가**, **저자가 무엇을 상속하는가**, **실행 기록이 어떤
축을 갖는가.**

---

## 6. 의존과 순서

```
  049 lane C/D (field는 표현식, 한 스캔이 여러 field)
        |
        v
  명사 1: Panel  ------------------+
                                   |
  040 (agenda는 공유 가능) --------+--> 명사 3: Run
                                        (run이 universe/period를 고정 -> panel 집합 결정)

  명사 2: Surface  --- 독립. 언제든 갈 수 있다
```

**착수 순서는 소유자가 정했다 (2026-09-01): 명사 2가 먼저다.**

| 순서 | 무엇 | 왜 여기 |
|---|---|---|
| 1 | **명사 2 (Surface)** | **소유자 결정.** 다른 둘과 독립이고 `036`의 ruling이 이미 CONVERGE다. 가장 먼저, 가장 싸게 가치를 낸다 |
| 2 | **명사 1 (Panel)** | 캠페인 레인 D 병합 후. `035`의 미뤄 둔 결정이 이 안에서 답해진다 |
| 3 | **`040`** | 명사 3의 전제. 작고 독립적이다 |
| 4 | **명사 3 (Run)** | workspace 문서 마이그레이션이 걸리므로 마지막. 되돌리기가 가장 비싸다 |

각 단계는 **`develop`이 green인 상태로** 들어간다. 캠페인 §4의 게이트 규칙(하한을 숫자로 박지 말고
분기한 커밋에서 직접 재라, `-rs`를 항상 붙여라)이 그대로 적용된다.

---

## 7. 결정

### 7-1. RESOLVED 2026-09-01 — lookback 이름

**`RowsLookback`이 panel 축(pivot된 표의 행)이고, `InstantsLookback`이 이름별 마지막 N개 record다.**
근거와 이름의 논리는 §2.4에 있다.

이 결정은 **같은 이름이 뜻을 바꾸는** 쪽이고, 그것이 이 문서 전체에서 가장 조용히 틀릴 수 있는
변경이다 (캠페인 §6의 첫 번째 위험). 그래서 §2.4의 마지막 소절이 그 위험을 **`grain` 거절에 묶어**
막는다: 모든 기존 등록이 한 번은 손으로 편집되고, 그 편집이 뜻의 변경을 말한다.

**따라서 7-3은 이 결정에 종속되었고, 관대한 쪽에서 뒤집혔다.**

> **구현 현황 (2026-09-01, 레인 C 병합 시점에 확인한 사실).** `src/`는 아직 이 결정을 반영하지
> 않았고, **오늘의 `RowsLookback`은 이름별로 센다.** rank가 `PARTITION BY instrument`이고, 증명도
> instrument로 묶으며, 선언한 수에 미달하는 이름은 하한 없이 읽혀 자기 역사만큼 뒤로 닿는다
> (`data/scan.py`의 `_prove_rows_bound`·`observation_rows`). 즉 `033`이 실측한 축 그대로다.
>
> 레인 C(기록 `123`)가 grouped 등록을 들여오며 바꾼 것은 **한 instant 안에서 무엇이 한 행인가**
> — 원천 행이 아니라 표현식이 내는 값 — 이고, **창이 이름별이라는 성질은 바꾸지 않는다.** 이
> 결정을 만들지도 봉하지도 않는다는 뜻이다. 다음 사람이 "코드가 문서와 반대다"를 보고 코드를
> 먼저 고치지 않도록 적어 둔다 — `033`이 그 방향의 실수를 correctness 문제로 기록한 자리다.

### 7-3. RESOLVED (7-1의 귀결) — `grain`을 안 쓴 등록은 거절한다

한 릴리스 동안 `rows`로 조용히 decode하는 write-forward는 **더 이상 안전하지 않다.** 그 경로를 열면
`grain`을 안 쓴 등록이 `rows`가 되고, 그 위의 `RowsLookback`은 새 타입 규칙에서 거절되어야 하는데
거절할지 통과시킬지가 릴리스 경계에 걸린다 — 그리고 균형 잡힌 패널에서는 통과시켜도 결과가 같아
보인다. **7-1이 이름을 재사용하기로 한 순간, 침묵할 수 있는 경로를 하나도 남기면 안 된다.**

그래서: `grain` 없는 등록은 거절하고, 거절 메시지가 세 값과 함께 `RowsLookback`의 새 뜻을 말한다.
비용은 모든 기존 dataset 선언을 한 줄씩 편집하는 것이고, 그것이 **뜻이 바뀌었다는 사실을 저자에게
전달하는 유일한 확실한 통로**다.

### 7-2. 열림 — panel spill을 지금 정할 것인가

in-process cache만 먼저 넣으면 §17.1.3은 닫히고 §17.1.4는 안 닫힌다. spill까지 가야 `--jobs`가 의미를
갖는다. **다만 spill의 값은 명사 3이 들어온 뒤에 커진다** — 한 run에 전략 셋이 있어야 공유할 상대가
생긴다. 후보: 명사 1에서 in-process까지, spill은 명사 3과 함께.

### 7-4. RESOLVED 2026-09-01 — 전략들은 계정을 공유하지 않는다

각 전략이 **자기 Account**를 가진다. Run이 공유하는 것은 *초기* 계정 **선언**이지 계정 자체가 아니다.

귀결이 둘 있고 둘 다 이 설계가 의존한다.

- **병렬이 성립한다.** 계정을 공유하면 전략들 사이에 순서 의존이 생겨 `--jobs`가 불가능해진다.
- **전략별 NAV가 뜻을 갖는다.** §17.6이 요구한 strategy record의 `account.jsonl`이 그 전략만의 경로다.

"여러 전략이 한 계좌를 나눠 쓴다"는 이 문서의 기능이 아니라 **ensemble / netting**이고,
`showcases/show_006_ensemble_netting`이 이미 다른 방식으로 다루는 영역이다. 그쪽이 필요해지면 그것은
*하나의* StrategyModel이 여러 sleeve를 합성하는 문제이지, run이 계정을 나눠 주는 문제가 아니다.

### 7-5. 열림 — `vqapr prepare`가 별도 verb인가

`run`이 필요할 때 알아서 물질화하면 verb가 하나 준다. 반대로 별도 verb면 *"이 run은 준비되었다"*가
관찰 가능한 상태가 되고, 긴 물질화가 첫 전략의 wall time에 숨지 않는다. 후보: 별도 verb, 단 `run`이
없으면 알아서 만든다.

---

## 8. 승인되면 무엇이 움직이는가

`docs/vqapr-architecture.md`의 §4(Data) · §5(Decision) · §9(Evidence) · §12(Run definition)가 이 세
명사를 흡수하고, §17은 대조표에서 **traceability 표**로 바뀐다 — 열 개의 진술이 각각 어느 절에서
behavior가 되었는지를 가리키는 표.

§15-6(`RowsLookback`이 세는 축)은 §7-1로 대체되어 닫힌다.

**다음 작업은 명사 2다.** 그것은 `docs/issues/036`의 CONVERGE ruling을 실행하는 것이고, 이 문서 §3이
그 목표 모양이다. 착수하려면 ExecPlan 하나와 implementation record 하나가 필요하다 —
`.agent/PLANS.md`와 `AGENTS.md`의 "Implementation records and commits" 절을 따른다.
