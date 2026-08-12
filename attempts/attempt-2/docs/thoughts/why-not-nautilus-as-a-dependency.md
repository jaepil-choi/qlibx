# nautilus_trader를 dependency로 채택하지 않은 이유

- 상태: 결정 기록 (decision record). 2026-08-03.
- 관련 문서: [[qlibx-architecture]], [[engine-borrow-benchmark-map]]
- 대상: `references/nautilus_trader` `develop@4d14b8c`

## 0. 결론

**nautilus_trader를 execution backend dependency로 채택하지 않는다.** 설계 아이디어는 선별 차용하되
코드는 import하지 않고, qlibx가 engine을 직접 구현한다.

이 문서는 그 판단의 근거를 남긴다. nautilus에 대한 부정적 평가가 아니다 — 아래 §1에 적은 대로
자기 영역에서는 우리가 검토한 어떤 대안보다 낫다. 판단의 실질은 **qlibx의 기본 작업 단위와
nautilus의 기본 작업 단위가 다르다**는 것 하나다.

## 1. 채택을 진지하게 검토한 이유

일봉만 있어도 기술적으로 동작한다. 소스로 확인한 사실이다.

```
model/enums.py       L451   BarAggregation.DAY
backtest/config.py   L171   bar_execution: bool = True   (기본값)
backtest/engine.pyx  L4803  _process_trade_ticks_from_bar(bar)
```

봉 하나를 O→H→L→C 네 개의 합성 tick으로 분해해 열린 주문을 경매한다.
`bar_adaptive_high_low_ordering`(engine.pyx L598-603)은 고가와 저가 중 어느 쪽이 먼저 왔는지
휴리스틱으로 추정한다 — qlib에는 이런 개념 자체가 없다.

그리고 qlibx가 만들려던 것 중 상당 부분이 이미 있고, 실전에서 검증되었다.

| qlibx 계획 | nautilus |
|---|---|
| kernel (clock/event/timer) | `common/component.pyx` |
| `available_at` PIT | `ts_init` 정렬 stream |
| 읽기 전용 view | `CacheFacade` / `PortfolioFacade` |
| exchange 체결 | 봉 경매 + FillModel 9종 + 교체 가능 FeeModel |
| **round-trip 회계 (§17 G2)** | `model/position.pxd` `avg_px_open`, `realized_pnl` |
| **long-short 실행 회계 (§17 G4)** | `accounting/accounts/margin.pyx` `MarginAccount` |
| pre-execution 검증 | `risk/engine.pyx` |
| 주문 상태 | 부분체결/거부/만료/취소 전 생애주기 |
| reconciliation | `execution/reports.py` 3종 report |
| 실전 경로 | 실제 broker adapter |

§17의 G2와 G4가 대부분 해소된다. 특히 G4(long-short 담보·마진)는 직접 설계할 경우 크고
위험한 작업인데, 검증된 구현을 쓸 수 있다는 뜻이었다.

라이선스는 채택 반대 사유가 **아니다.** LGPL-3.0은 import 형태의 의존을 제약하지 않는다. 코드를
복사할 때만 적용된다. 의존은 세 선택지 중 라이선스 제약이 가장 적은 형태였다.

## 2. 채택하지 않은 이유

### 2.1 기본 작업 단위가 다르다 — 결정적 사유

nautilus의 기본 단위는 **instrument 하나의 event**다. 실시간 거래에서 tick은 실제로 하나씩
도착하므로 이것이 옳은 모델이다.

qlibx의 기본 단위는 **decision time의 횡단면**이다. 일봉 3000종목은 같은 순간에 함께 확정된다.
이를 3000개의 개별 event로 쪼개면 정보를 잃고 비용만 늘어난다.

```
nautilus   (날짜 × 종목) 마다 event    →  5000일 × 3000종목 = 1500만 event
qlibx 필요  날짜마다 batch 1회          →  5000 step, 각 step 안에서 3000개 배열 연산
```

이 차이는 최적화로 좁힐 수 있는 종류가 아니다. 아키텍처의 기본 단위에서 나온다.

그리고 이것은 성능만의 문제가 아니다. 횡단면 alpha가 자연스럽게 표현되려면 "이 시점 3000종목의
signal 벡터"가 한 덩어리여야 하는데, nautilus에서 그것은 3000회 조회 후 조립이다.

**중요한 구분:** 이 사유는 "event-driven을 포기한다"는 뜻이 아니다. qlibx는 event / callback /
handler 기반 inversion of control을 유지한다. 바뀌는 것은 **한 event가 나르는 데이터의 크기**뿐이다.
`exchange.match(order)` 대신 `exchange.match_batch(orders)`이며, clock·callback·closed-loop feedback은
그대로다. 시간 축은 여전히 순차이므로 partial fill, blocked liquidation, path-dependent stop-loss가
모두 성립한다.

### 2.2 PRD의 절반이 nautilus 밖이다

검색 결과 다음이 존재하지 않는다.

```
cross_sectional / portfolio_weight / target_weight / universe   →  없음
IC / RankIC / quantile spread / factor return                    →  없음
signal 저장·재사용 · signed alpha weight · ensemble               →  없음
artifact envelope · dependency lineage · research catalog         →  없음
```

`rebalance`로 검색되는 유일한 항목은 `data/engine.pyx` L1650의 **option chain 구독 갱신**으로,
portfolio rebalancing과 무관하다. `analysis/`는 portfolio 성과 통계만 제공한다.

즉 PRD §8(signal), §9(alpha), §10(ensemble/construction), §12(artifact/catalog) 전체에 대응물이 없다.
채택하더라도 qlibx가 만들 분량은 크게 줄지 않으며, **줄어드는 부분이 정확히 qlibx의 차별점이 아닌
부분**이다.

### 2.3 v1 → v2 전환이 진행 중이다

`MIGRATION_V2.md` 원문:

> v2 is the Rust core and PyO3 Python package. It becomes the primary Python path when `develop`
> switches to that package.
>
> After cutover, v1 moves to `develop_v1` for approximately three months of critical security
> backports. **It does not receive new feature or parity work.**

vendoring한 스냅샷은 v1(Cython) 계열이다. 지금 v1 API에 결합하면 cutover 후 짧은 기간 안에 다시
써야 한다. 하드 의존을 시작하기에 가장 나쁜 시점이다.

이 사유는 **시간이 지나면 소멸한다.** §4의 재검토 조건에 해당한다.

### 2.4 대규모 종목 수가 검증되지 않았다

```
examples/backtest/   전부 1~3 instrument (FX 쌍, crypto, 개별주 1개)
BENCHMARKING.md      instrument 수 / throughput 데이터 없음
docs                 "limited only by machine resources" — 주장이며 측정치가 아님
```

3000종목 규모의 공개 사례나 벤치마크가 없다. §2.1의 구조적 사유와 합쳐지면, 채택 결정을 위해
우리가 직접 측정해야 하는 상태였다.

### 2.5 기업행위 처리가 없다

engine에 split / dividend / adjusted price 처리가 없다. 검색되는 항목은 Interactive Brokers
adapter의 data feed wrapper 필드뿐이다(`adapters/interactive_brokers/client/wrapper.py`).

20년 주식 리서치에서 이는 필수다. 수정주가를 사전 생성해 우회할 수 있으나 액면분할 시점의 보유
수량이 어긋나므로 어느 경우든 qlibx가 별도로 해결해야 한다.

## 3. 그럼에도 차용하는 것

코드가 아니라 **설계**를 차용한다. 상세 매핑은 [[engine-borrow-benchmark-map]]와
[[qlibx-architecture]] §14에 있다.

| 차용 | 출처 |
|---|---|
| 이중 timestamp (`ts_event` / `ts_init`) → `available_at` 모델 | `core/data.pyx` L30, L42 |
| `ts_init` 오름차순 stream = PIT 강제 | `backtest/engine.pyx` L903 |
| restatement 표시 | `model/data.pyx` L1496 `is_revision` |
| 읽기 전용 facade | `cache/base.pxd`, `portfolio/base.pxd` |
| clock / timer / TimeEvent | `common/component.pyx` L130, L623, L1013 |
| data ↔ timer 실행 순서 | `backtest/engine.pyx` L1692, L1731-1735 |
| pass or deny-with-reason 검증 | `risk/engine.pyx` L584-666, L1073-1132 |
| reconciliation report 3분할 | `execution/reports.py` L95 / L619 / L859 |
| portfolio statistic plugin | `analysis/statistic.py` L25 |
| round-trip 회계 필드 구성 | `model/position.pxd` |
| 마진 계좌 / 마진 모델 | `accounting/accounts/margin.pyx`, `margin_models.pyx` |
| 명시적 생성자 주입 (kernel 조립) | `system/kernel.py` L101 |

특히 §2.1의 `available_at` 정렬 stream은 [[qlibx-architecture]] §7의 근간이 되었다. 초안은 이를
"어디에도 대응물이 없다"고 잘못 기술했고, 이 검토 과정에서 정정되었다(§18 개정 이력).

## 4. 재검토 조건

다음 중 하나라도 성립하면 이 결정을 다시 검토한다.

1. **v2가 안정화되고 API가 고정된다.** §2.3이 소멸한다.
2. **분단위 이하 체결이 필요해진다.** 이때는 §2.1의 횡단면 이점이 사라지고 주문 생애주기와
   intraday 순서 처리의 가치가 커진다. 현재는 필요하지 않다는 것이 확인되었다.
3. **실전 운용으로 전환한다.** broker adapter, reconciliation, 주문 생애주기는 직접 구현할 대상이
   아니다. 이 경우 research/backtest 경로는 qlibx가 유지하고 실전 경로만 nautilus에 위임하는
   분리를 검토한다.
4. **3000종목 규모의 벤치마크가 공개되고 우리 요구를 만족한다.** §2.4가 소멸한다.

재검토 시 §2.2는 소멸하지 않는다는 점에 유의한다. 리서치 층은 어느 경우에도 qlibx가 소유한다.

## 5. 기각한 대안

**대안 A — nautilus를 backend로, qlibx는 리서치만.**
가장 매력적인 배분이었으나 §2.1이 막는다. "현실적이면서 빠른 시뮬레이션"이라는 요구는 리서치
층에도 nautilus 층에도 속하지 않는 중간 조각이며, 그 조각(일봉 횡단면 batch 체결)이 nautilus에
없다.

**대안 B — 이중 backend (자체 + nautilus adapter)를 port 뒤에 둔다.**
port 추상화 비용 자체는 작다. 그러나 두 backend의 semantics parity를 지속적으로 검증해야 하고,
§2.3 때문에 nautilus 쪽은 곧 다시 써야 한다. 재검토 조건 1 또는 3이 성립할 때 다시 고려한다.

**대안 C — nautilus를 검증 oracle로만 사용.**
§2.4가 미해결이므로 oracle 자체의 신뢰 구간을 우리가 먼저 측정해야 한다. 조건 4에서 재고한다.
