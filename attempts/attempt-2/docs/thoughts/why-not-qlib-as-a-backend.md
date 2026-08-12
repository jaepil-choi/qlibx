# qlib을 backend로 채택하지 않은 이유

- 상태: 결정 기록 (decision record). 2026-08-04.
- 관련 문서: [[qlibx-architecture]], [[engine-borrow-benchmark-map]], [[why-not-nautilus-as-a-dependency]]
- 대상: `references/qlib` `main@79633dd` (= `pyqlib` 0.9.7과 인용 모듈 9/10 동일)

## 0. 결론

**qlib을 runtime backend로 사용하지 않는다.** 체결 산술과 원장 산술은 코드로 차용하고(MIT),
`Signal` 인터페이스는 계약으로 차용하되, engine과 데이터·증거 층은 qlibx가 직접 구현한다.

이 결정은 프로젝트 초기 전제를 뒤집은 것이다. PRD는 원래 "Qlib을 학습과 backtest 실행 기반으로
사용하는 재사용 가능한 alpha research framework"로 시작했고 `pyqlib==0.9.7`을 compatibility
baseline으로 고정하고 있었다. 그 전제가 왜 성립하지 않는지를 남긴다.

qlib에 대한 부정적 평가가 아니다. §1에 적은 대로 자기 목적에서는 잘 만들어졌고, 우리는 그 중
상당 부분을 계속 쓴다. 판단의 실질은 **qlib이 푸는 문제와 PRD가 요구하는 문제가 다르다**는 것이다.

```
qlib   금융 예측을 위한 ML 실험 파이프라인 + 그 끝에 붙은 backtest
       "이 모델이 이 데이터에서 얼마나 좋은가"

qlibx  재사용 가능한 연구 자산의 그래프 + 실행 증거
       "이 signal을 여러 alpha가 어떻게 쓰고, 결과가 무엇에 의존하고,
        실제 체결이 의도와 어떻게 달랐는가"
```

## 1. 계속 차용하는 것

### 1.1 체결·원장 산술 (코드 차용, MIT)

[[qlibx-architecture]] §14에 파일·줄번호 단위로 있다. 요약하면 `exchange.py`의 clipping 순서
전체(L859-950), tradability 판정, lot 산술, `position.py`의 매수/매도/settle, `account.py`의
누적기와 bar-end mark, `report.py`의 주문 단위 진단 집계다.

특히 `_calc_trade_info_by_order`의 clipping 순서는 주식 일봉 체결의 현실을 순서까지 담고 있어
대체재가 없다. qlibx는 이를 instrument축 batch 연산으로 옮겨 쓴다.

### 1.2 `Signal` 인터페이스 (계약 차용)

```python
# qlib/backtest/signal.py
class Signal(ABC):                    # L16
    def get_signal(self, start_time, end_time) -> pd.Series | DataFrame

class SignalWCache(Signal):           # L36  미리 계산된 값을 감쌈
class ModelSignal(SignalWCache):      # L68  model + dataset을 감쌈
```

**전략이 signal의 출처를 모른다.** 모델이 만들었는지, 파일에서 읽었는지, 사람이 넣었는지 알 수
없다. 이것이 PRD §2.2 "signal 생산과 alpha 의사결정을 분리한다"의 구현 형태다.

qlibx는 이 이음매를 그대로 쓰되 뒤에 저장소를 붙인다.

```
qlib   Signal = 메모리 객체. 실험이 끝나면 pred.pkl 로만 남음
qlibx  Signal = 정체성 있는 artifact. 여러 alpha가 재사용. 계보 있음
```

**ML workflow에서 실제로 차용하는 것은 이 인터페이스 하나다.** 나머지는 §1.3 참조.

### 1.3 참고하되 차용하지 않는 것

qlib의 ML workflow에는 잘 설계된 장치가 더 있다.

| 장치 | 내용 | qlibx |
|---|---|---|
| 4층 분리 | Loader → Handler → Dataset → Model | 참고만. sample에서 보여준다 |
| learn/infer 이원화 | `DK_L` / `DK_I` (`handler.py` L392-394) | view API로 흡수 |
| processor fit 구간 | `fit_start_time/end_time` (`processor.py` L197-205) | 차용하지 않음 |
| purge | `trunc_days=horizon+1` (`rolling/base.py` L198) | clock이 대체 |

**이들의 가치는 구현이 아니라 어휘다.** `fit_start_time`은 슬라이스 한 줄이고, `trunc_segments`는
10줄 남짓이다. qlib이 한 일은 "정규화를 어디서 적합할지 명시해야 한다"는 결정에 **이름을 붙인
것**이며, 소스의 느낌표 세 개가 그 장치의 본질이다.

```python
# NOTE: correctly set the `fit_start_time` and `fit_end_time` is very important !!!
# `fit_end_time` **must not** include any information from the test data!!!
```

qlibx는 이 어휘를 알되 강제하지 않는다. 근거는 §2.5다.

**purge에 대해서는 qlibx가 다른 층위에서 푼다.** qlib은 task 생성 시점에 train 구간을
`horizon+1`만큼 잘라낸다. 이 방식은 (a) horizon을 사람이 별도 선언해야 하고 — 소스 자체가
`# TODO: get horizon automatically from the expression!!!!`로 남겨두었다 — (b) opt-in이며
(`trunc_days` 기본값 `None`) (c) 파이프라인 밖에서는 유지되지 않는다. qlibx는 label 등록 시
`available_at = event_time + horizon`으로 선언하므로 자르는 코드 없이 성립한다
([[qlibx-architecture]] §17 G3).

다만 이것이 해결하는 것은 **look-ahead**이지 **leakage**가 아니다. 정규화 통계 적합 구간, train과
validation 사이의 label 겹침은 모두 가용 구간 **안쪽**에서 발생하므로 clock이 관여하지 않는다.
qlibx는 이를 방법론 문제로 보고 project에 맡긴다(§2.5).

### 1.4 PIT 스키마

qlib의 재무제표 PIT 저장소는 qlibx가 필요로 하는 모델에 가장 가깝다.

```
qlib/data/data.py         L338  PITProvider
qlib/utils/__init__.py    L109  read_period_data(index_path, data_path, period, cur_date_int, ...)
```

`{instrument}/{field}.data`에 `(date, period, value, _next)` 레코드가 date 오름차순으로 쌓이고,
`_next`가 같은 period의 다음 수정본 위치를 가리킨다. 리더는 `date <= cur_date`인 마지막 레코드를
반환한다. 데이터베이스 서버가 아니라 **파일 포맷과 seek 기반 리더 함수**다.

```
qlib PIT    date         / period     / value / _next
qlibx       available_at / event_time / value / revision
```

**같은 모델이다.** nautilus의 `ts_init`/`ts_event`/`is_revision`과도 같으며, qlib 쪽이 수정 체인을
파일 내 링크로 잇는다는 점에서 더 완결적이다. 차이는 적용 범위뿐이고, 그것이 §2.2의 내용이다.

## 2. 채택하지 않은 이유

### 2.1 decision clock이 데이터 인덱스에 묶여 있다 — 결정적 사유

```python
# qlib/backtest/utils.py L23  TradeCalendarManager
self.freq = freq            # 주기 하나
self.trade_step = 0         # 카운터 하나
self.trade_len = ...
```

**결정 시점 = 실행 시점 = 데이터 인덱스**다. 셋이 같고, 분리할 파라미터가 없다.

PRD §9.6은 네 개의 독립 clock을 요구한다.

```
observation  새 데이터/상태를 관측하는 시점
decision     alpha/portfolio policy가 새 intent를 만드는 시점
execution    order/fill을 처리하는 bar 또는 interval
monitoring   저장된 account snapshot을 분석하는 시점
```

> §9.6 각 supported profile은 clock의 source, cadence, timezone, calendar와 **상호 관계**를
> frozen config에 선언한다. (...) Monitoring clock은 decision clock과 **독립적일 수 있으며**,
> required monitoring profile은 decision이 없는 시점에도 marked actual account snapshot을 제공해야
> 한다.

"월 1회 리밸런싱 + 매일 제약 감시"는 qlib 구조로 표현되지 않는다. `NestedExecutor`는 계층
(일봉 안의 분봉)이며 형제 관계가 아니다. 그리고 §9.8의 trigger/hold 구분 — 새 decision을 만들지
여부를 판정하고 hold를 empty decision으로 표현하는 것 — 은 개념 자체가 없어, 매 step 목표를
재제출하게 되고 이는 §5.6이 금지한 price-drift rebalance를 만든다.

이 사유가 결정에서 가장 큰 비중을 차지한다. 시간축은 아키텍처의 최상위 구조이며, 그것이 데이터
스키마에 종속되어 있으면 위의 모든 층이 그 제약을 물려받는다.

**학습 시점도 같은 문제에 걸린다.** qlib에서 train/valid/test는 config의 날짜 문자열이고, rolling은
그 문자열을 프로그램으로 생성하는 것이다. 시간축 위의 event가 아니다. qlibx는 `FIT`을 다른 event와
같은 queue에 두어 학습·결정·실행·감시가 하나의 시간축에서 정합적으로 진행되게 한다
([[qlibx-architecture]] §3).

### 2.2 저장의 최소 단위에 `available_at`이 없다

일반 feature의 저장 형식이다.

```python
# qlib/data/storage/file_storage.py
class FileFeatureStorage(FileStorageMixin, FeatureStorage):      # L285
    self.file_name = f"{instrument.lower()}/{field.lower()}.{freq.lower()}.bin"   # L289
    ...
    np.hstack([index, data_array]).astype("<f").tofile(fp)       # L310
```

**첫 원소가 시작 인덱스, 나머지가 float32 값이다.** i번째 값의 날짜는 `calendar[start + i]`로
결정된다. "언제 알 수 있었나"를 기록할 자리가 물리적으로 없으며, 암묵적 가정은 "t일 위치의 값은
t일에 알 수 있었다"이다.

종가에는 성립하지만 다음에는 성립하지 않는다.

```
벤더가 2일 지연 배포하는 signal    t일 칸에 있으나 t+2에 관측 가능
수정된 재무 데이터                발표는 5월, 회계기간은 3월
지수 편입 발표                    발표일과 효력일이 다름
장 마감 후 공시                   같은 날이나 장중에는 관측 불가
```

qlib도 이 문제를 인식했고, 그래서 §1.4의 PIT 서브시스템을 **재무제표에 한정해** 별도 파일 포맷과
전용 연산자(`P()`)로 만들었다. 결과적으로 한 시스템 안에 데이터 모델이 둘이다.

```
일반 데이터   달력 인덱스 배열.        available_at 없음
PIT 데이터    date/period/value/_next.  available_at 있음.  별도 시스템, opt-in
```

PRD §4.4는 이를 전 데이터의 기본 속성으로 요구한다.

> **모든** data consumer는 선언된 `available_at <= evaluation_time`인 observation만 사용한다.

그리고 §7.2는 logical dataset의 필수 metadata로 "Event time, observation time와 `available_at`"을
요구한다.

**이는 스택의 최하부이므로 상위에서 감쌀 수 없다.** 없는 정보는 wrapper가 만들어내지 못한다.
[[qlibx-architecture]] §7의 clock-bound view 전체가 이 속성 위에 서 있다.

### 2.3 실험 단위이지 결과물 단위가 아니다

qlib의 실행 단위는 한 번의 experiment다.

```python
# qlib/workflow/record_temp.py
self.save(**{"pred.pkl": pred})        # L195
self.save(**{"label.pkl": raw_label})  # L206
def list(self): return ["pred.pkl", "label.pkl"]   # L209
```

저장 백엔드는 MLflow다(`workflow/recorder.py`). 중간 산출물은 **그 실험에 딸린 첨부파일**이며
pickle이다.

PRD의 요구는 다르다.

> §4.5 Standard artifact는 Qlib process와 **producer implementation 없이** schema와 lineage를 읽을
> 수 있어야 한다.
>
> §5.6 금지 behavior — **Pickle-only result를 portable public artifact라고 주장**

pickle은 producer의 클래스 정의가 있어야 열린다. 그리고 §12.2의 envelope(schema version, content
fingerprint, 시간 범위, axis/unit/currency, coverage, terminal status, lineage, path-dependency
flag)에 대응하는 구조가 없다. MLflow parameter가 대체물 역할을 하지만 typed dependency graph가
아니다(§12.4).

방향성도 다르다.

```
qlib    데이터 → 모델 → 예측 → backtest → 리포트
        한 방향 파이프라인. 종료 시 실험 기록 하나.

qlibx   signal ──┬→ alpha A ──┐
                 ├→ alpha B ──┼→ ensemble → physical target
                 └→ alpha C ──┘
        artifact가 서로를 소비하는 graph. 중간에서 시작·재개 가능.
```

관련해 `TaskManager`는 MongoDB를 **필수**로 요구한다(`workflow/task/manage.py` L7-8). PRD §5.5가
명시적으로 배제한 의존이다.

### 2.4 전역 가변 상태

```python
# qlib/config.py L547
C = QlibConfig(_default_config)
```

module-level singleton이며 `qlib.init()`이 이를 변경한다. provider, calendar, cache가 여기에
매달린다.

PRD가 두 곳에서 이를 문제 삼는다.

> §7.9 서로 다른 calendar, region, provider 또는 data materialization을 사용하는 concurrent run은
> process isolation, immutable initialization 또는 검증된 lifecycle로 상호 mutation을 막아야 한다.
>
> §12.8 여러 session과 agent가 같은 repository와 branch에서 연구할 수 있다.

agent 여럿이 서로 다른 universe로 동시에 연구하면 오염된다. process 분리 외의 방법이 없고, 그것은
§12.8이 요구하는 default 동작이 아니다.

### 2.5 framework가 아니라 model zoo를 겸한다

```
qlib/contrib/model/    35개 파일, 12,093줄
```

```
GBDT · XGBoost · CatBoost · Linear · DoubleEnsemble
LSTM · GRU · ALSTM · TCN · SFM · TabNet
GATS · HIST · IGMTF · KRNN · TRA · TCTS · ADARNN · ADD · Sandwich
Transformer · Localformer  (+ 각 _ts 시계열 변형)
```

`setup.py`에 torch가 없으므로 soft dependency이나, 12,000줄이 배포물에 포함된다.

PRD의 소유 경계는 명확하다.

> §5.3 User project가 소유하는 것 — **Signal model과 alpha policy code**
>
> §2.7 사용자 고유의 signal model과 alpha logic은 **project가 소유한다.** (...) qlibx가
> reference/sample component를 제공할 수는 있지만 **project-owned proprietary alpha를 package
> built-in에 가두지 않는다.**
>
> §6.1 Sample은 **reference journey**이지 hidden built-in alpha나 mandatory starter layout이 아니다.

**qlibx는 모델을 제공하지 않는다.** ML이든 DL이든 규칙 기반이든 project가 소유한다. sample 1벌을
둘 수 있으나 참고용이며 요청하지 않은 project에 자동 생성하지 않는다.

같은 원리가 연구 방법론 전반에 적용된다. **전처리, train/validation split, 정규화 적합 구간,
cross-validation 설계는 project 소유이며 qlibx가 검증하지 않는다.** embargo를 두지 않는 설계가
틀렸다고 판정할 근거가 없고, 판정하려면 전처리 파이프라인의 구조를 규정하게 되어 모델을
제공하지 않겠다는 원칙과 충돌한다. PRD §2.6("경제적 의미를 추측하지 않는다")과도 어긋난다.

qlibx가 요구하는 것은 **schema뿐이다.** §8.2가 stored signal에 "Producer/model/fitted-state
identity"를 필수 필드로 요구하므로 envelope에 그 자리가 있어야 하지만, 값은 producer가 채우는
**불투명한 식별자**이며 qlibx는 이를 운반하고 조회할 뿐 해석하지 않는다. §12.10의 원칙과 같다 —
"consumer가 custom semantics를 이해하지 못해도 identity, checksum, provenance, dependency edge는
보존할 수 있어야 한다."

```
schema 요구   "envelope에 이 필드가 있어야 한다"        →  qlibx
의미 검증     "그 값이 방법론적으로 옳은가"              →  project
```

### 2.6 PRD 조항별 미충족

| PRD | 요구 | qlib | 근거 |
|---|---|---|---|
| §4.4 | 모든 관측에 `available_at` | ✗ | 일반 데이터는 달력 인덱스 배열. PIT는 별도 서브시스템 |
| §7.2 | logical dataset 등록 (schema/unit/currency/coverage) | ✗ | `.bin`에 metadata 없음 |
| §4.5 | producer 없이 읽히는 artifact | ✗ | `pred.pkl` |
| §12.2 | artifact envelope + fingerprint | ✗ | MLflow parameter가 대체물 |
| §12.4 | typed dependency graph | ✗ | 실험 ID 참조 |
| §12.5 | file-backed catalog, MongoDB 불요 | ✗ | MLflow |
| §5.5 | MongoDB 배제 | ✗ | `TaskManager`는 MongoDB 필수 |
| §9.6 | 4개 독립 clock | ✗ | `freq` 하나, `trade_step` 하나 |
| §9.8 | trigger / hold 구분 | ✗ | 개념 없음 |
| §9.2 | signed alpha weight를 1급 결과로 | ✗ | strategy 내부 중간값 |
| §10.1 | signed weight ensemble + netting/crossing | ✗ | `AverageEnsemble`은 **예측 평균** (`model/ens/ensemble.py` L91) |
| §11.3 | 전 주문 conversion 진단 보존 | ✗ | `logger.debug`로 폐기 |
| §4.6 | silent fallback 금지 | ✗ | 현금 부족 시 전량 매도 폴백 등 |
| §7.9 §12.8 | provider 격리 / 병렬 agent | ✗ | 전역 singleton `C` |
| §5.3 §2.7 | model은 project 소유 | ✗ | contrib/model 35개 |

ensemble 항목을 부연하면, qlib `AverageEnsemble`은 prediction DataFrame들을 평균·표준화한다.
PRD §10.1이 요구하는 것은 signed weight를 결합하며 종목별 netting과 crossing 금액, member
contribution과 overlap을 기록하는 것으로, 다른 층위의 연산이다.

## 3. 위치가 문제다

미충족 항목을 wrapper로 메울 수 있는지가 실질적 판단 기준이었다. 네 가지는 불가능하다.

```
①  available_at        저장 포맷의 최소 단위.        스택 최하부
②  decision clock      캘린더 구조.                  시간축 최상위
③  artifact 정체성     실험 단위 대 결과물 단위.      그 위 전부에 영향
④  전역 상태           초기화 방식.                  프로세스 경계
```

①은 없는 정보를 wrapper가 만들 수 없다. ②는 시간축이 데이터 스키마에 종속되어 있어 상위에서
분리할 수 없다. ③은 저장·조회 계약 전체를 바꾸는 것이므로 감싸는 것이 아니라 대체하는 것이다.
④는 process 분리 외의 방법이 없다.

원래 PRD가 "Qlib을 closed-loop runtime kernel로 쓴다"고 한 것은 **체결 lifecycle만** 본 판단이었다.
그 부분은 실제로 견고하고 지금도 산술을 차용한다. 성립하지 않는 것은 그 위아래 — 데이터 층과 증거
층 — 이며, 그것이 PRD의 대부분이다.

## 4. 재검토 조건

1. **qlib이 일반 feature에 availability timestamp를 도입한다.** §2.2가 소멸한다. 현재 PIT
   서브시스템의 스키마를 전 데이터로 확장하는 형태라면 그렇다.
2. **decision clock이 데이터 인덱스에서 분리된다.** §2.1이 소멸한다.
3. **portable artifact 계약이 도입된다.** MLflow/pickle 외의 경로가 생기면 §2.3이 완화된다.

세 조건이 모두 성립해도 §2.5는 남는다. 모델과 연구 방법론은 어느 경우에도 project가 소유한다.

`pyqlib`은 dependency에서 제거되었으나 `references/qlib`에 upstream 전체 트리가 보존되어 있어
차용과 재검토는 저장소만으로 가능하다.

## 5. 기각한 대안

**대안 A — qlib을 backend로 두고 그 위에 qlibx 계약을 씌운다.**
초기 PRD의 전제였다. §3의 네 항목이 wrapper로 메워지지 않으므로 성립하지 않는다.

**대안 B — qlib을 fork한다.**
PRD §5.6이 "Qlib fork를 기본 해결책으로 사용"을 금지 behavior로 명시한다. §2.1과 §2.2는 데이터
포맷과 캘린더 구조의 변경이므로 fork라 해도 사실상 재작성이며, upstream과의 동기화 비용만 남는다.

**대안 C — 데이터 층만 qlibx가 만들고 backtest만 qlib에 위임한다.**
검토 가치가 있었으나 §2.1이 막는다. clock이 데이터 인덱스에 묶여 있으므로 데이터 층을 교체하면
캘린더 의미가 함께 바뀌고, 그 시점에 위임하는 것은 `Exchange`와 `Position` 산술뿐이다. 그것은
지금 코드로 차용하고 있는 것과 같으며 runtime 의존을 유지할 이유가 없다.
