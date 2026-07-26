# Qlib long-short 실행을 위한 matched capitalization 결정

## 1. 결정 상태

- 결정일: 2026-07-23
- 상태: **Accepted — target architecture, implementation pending**
- 적용 경계: `qlib-integration-codex/` 및 `qlib-extended`

Qlib source를 수정하거나 synthetic inverse ticker를 만들지 않는다. Signed active intent는
원 종목 기준으로 유지하고, Qlib에는 non-negative composite position만 보낸다. Short를 표현할
baseline inventory는 ticker가 point-in-time으로 tradable해진 시점에 matching cash debit과 함께
활성화한다.

Qlib `Account`와 `Position`은 order, fill, cash, quantity, mark-to-market과 NAV의 source of
truth로 계속 사용한다. 별도 signed ledger가 Qlib과 독립적으로 체결 상태를 소유해서는 안 된다.
Signed 상태는 Qlib composite position과 baseline sidecar의 차이로 계산하는 read-only audit
projection이다.

```text
signed active intent
-> matched-capitalization adapter
-> non-negative composite target/order
-> Qlib Exchange / Account / Position
-> signed observation and audit projection
```

## 2. 채택한 상태 모델

ticker `i`, bar `t`에 대해 다음 수량을 둔다.

```text
A[i,t] = active signed quantity
B[i,t] = synthetic baseline inventory quantity, B >= 0
C[i,t] = Qlib composite quantity, C >= 0

C[i,t] = B[i,t] + A[i,t]
A[i,t] = C[i,t] - B[i,t]
```

각 상태의 책임은 다음과 같다.

- `active signed intent`: strategy/optimizer가 원 종목 기준으로 만든 목표다.
- `baseline sidecar`: matched capitalization으로 활성화한 ticker별 inventory와 대응 cash를
  기록한다.
- `Qlib composite position`: Qlib이 실제 order/fill을 반영한 authoritative execution state다.
- `signed audit projection`: composite와 baseline의 차이로 계산하며 체결 상태를 직접 변경하지
  않는다.

Baseline sidecar는 Qlib을 대신하는 portfolio ledger가 아니다. Baseline activation과 이후
corporate action을 재현하는 최소 상태만 소유한다.

## 3. Dynamic universe와 no-lookahead 계약

전체 backtest 기간의 ticker 집합을 matrix column axis로 미리 사용할 수 있다. 이는 저장과 정렬을
위한 schema일 뿐이며, 미래 ticker의 경제적 존재나 inventory를 의미하지 않는다.

각 bar에는 최소한 다음 point-in-time mask가 있어야 한다.

```text
observed_mask[t,i]
tradable_mask[t,i]
strategy_universe_mask[t,i]
shortable_mask[t,i]
inventory_ready_mask[t,i]
```

미래 ticker가 full axis에 있더라도 `observed_mask=False`인 동안에는 다음을 모두 만족해야 한다.

- signal, rank, normalization과 optimizer 대상에서 제외한다.
- active target과 actual active quantity는 0이다.
- baseline inventory와 composite quantity는 0이다.
- 가격 결측 여부나 향후 등장 사실을 feature로 사용하지 않는다.

Ticker lifecycle은 다음과 같다.

```text
unseen
-> observed
-> tradable
-> inventory activated
-> short eligible
```

`observed`, `tradable`, `shortable` 전이는 해당 bar까지 확인 가능한 데이터만 사용한다. 향후 K200
편입, 향후 alpha target, 전체 기간 최대 short weight로 activation 여부나 buffer 크기를 정하지
않는다.

## 4. Matched capitalization

신규 ticker가 처음 inventory activation 조건을 충족하면 execution-time price `P`와 현재 정보로
정한 buffer `delta_B`를 사용해 다음 두 상태를 같은 atomic event로 갱신한다.

```text
baseline.quantity  += delta_B
baseline.cash      -= delta_B * P

composite.quantity += delta_B
composite.cash     -= delta_B * P
```

수량 증가와 cash 감소가 같은 가격으로 대응하므로 activation 자체는 composite NAV와 active
projection을 바꾸지 않는다.

```text
delta composite NAV = delta_B * P - delta_B * P = 0
delta active quantity = delta_C - delta_B = 0
```

그 다음 active order를 원래 경제적 방향으로 Qlib에 보낸다. 신규 ticker의 active target이
`-q`이면 baseline activation 뒤 Qlib `SELL q`를 실행한다.

```text
activation 후 composite quantity = B
active SELL q 체결 후 composite quantity = B - q
audit active quantity = (B - q) - B = -q
```

따라서 active short는 BUY mirror가 아니라 실제 원 종목 SELL 방향으로 Qlib tradability, price,
volume, lot과 cost 검사를 통과한다.

### 4.1 Buffer sizing과 top-up

`B`는 미래 target으로 계산하지 않는다. 현재 active NAV, 현재 config의 per-name short cap,
현재 가격과 명시적 safety multiplier만 사용한다.

```text
required_inventory_notional[t,i]
    = current_active_nav[t]
    * current_per_name_short_cap[t,i]
    * safety_multiplier
```

필요 수량이 현재 baseline보다 크면 부족분만 같은 matched-capitalization event로 top-up한다.
Top-up과 active SELL의 순서는 반드시 다음과 같다.

```text
1. validate point-in-time masks and price
2. activate or top up baseline
3. submit active order
4. observe Qlib fill
5. reconstruct realized signed position
```

Baseline funding reserve가 부족하면 Qlib cash constraint를 우회해 정상 처리된 것처럼 보이지 않고
명시적으로 실패한다. Reserve sizing과 replenishment policy는 implementation config에 드러나야
한다.

### 4.2 Same-bar 의미

Matched capitalization은 시장에서 baseline BUY를 체결한 것으로 보지 않는다. Short 표현을 위해
Qlib long-only inventory를 회계적으로 활성화하는 financing event다. 따라서 baseline activation은
시장 volume이나 transaction cost를 소비하지 않고, 뒤따르는 active SELL만 Qlib execution
constraint와 cost를 소비한다.

이는 해당 bar에 inventory를 사용할 수 있다는 modeling assumption이다. 실제 borrow availability
data를 도입하면 `shortable_mask`와 capacity를 그 데이터로 제한한다. 더 보수적인 연구가 필요하면
activation 다음 bar부터 `inventory_ready=True`로 만드는 lag policy를 별도 config로 비교한다.

## 5. Signed observation and audit layer

Audit layer는 다음 값을 date × ticker artifact로 남긴다.

- point-in-time masks와 observation timestamp
- intended active signed target
- baseline quantity/cash before and after activation
- capitalization quantity, price와 reason
- composite quantity/cash before order
- submitted active order와 Qlib requested/dealt amount
- composite closing quantity
- reconstructed realized active signed quantity
- baseline, composite와 active PnL/NAV attribution
- partial fill, capacity shortfall과 blocked reason

Partial fill에서는 target이 아니라 Qlib fill로 realized active quantity를 갱신한다.

```text
realized_A[t] = realized_A[t-1] + signed_active_fill[t]
```

매 bar 다음 invariant를 fail-fast로 검사한다.

```text
B >= 0
C >= 0
A == C - B
composite_nav == baseline_nav + active_nav

if observed_mask is false:
    A == 0
    B == 0
    C == 0
```

Qlib Position과 별도 signed execution ledger를 각각 source of truth로 두지 않는다. 기존 production
signed holdings ledger는 이 invariant와 PnL을 비교하는 differential-test oracle로만 사용한다.

## 6. Reporting 계약

Qlib standard portfolio return은 거대한 composite account NAV를 denominator로 사용하므로 active
return report로 사용하지 않는다. Reporting은 저장된 composite와 baseline artifact에서 active
money PnL과 선택한 active notional denominator를 명시적으로 계산한다.

Qlib raw report와 Account artifact는 execution reconciliation을 위해 보존하지만 전략 성과의
canonical report는 아니다.

## 7. 채택하지 않는 대안

다음 접근은 이 결정으로 폐기한다.

- synthetic inverse/mirror ticker를 BUY해 short를 근사하는 방식
- 상장 전 ticker에 양수 Qlib inventory 또는 0-price holding을 미리 넣는 방식
- long leg와 short leg를 독립 Qlib account로 실행한 뒤 사후 PnL만 합치는 방식
- `Exchange.deal_order(position=None)`와 별도 signed ledger를 authoritative state로 사용하는 방식
- Qlib source code를 fork하거나 `.venv` package를 직접 수정하는 방식

Mirror ticker는 underlying의 long/short 전환, rank, 방향별 limit/cost와 고정수량 short semantics를
왜곡한다. 상장 전 positive inventory는 첫 가격 발생 시 free NAV를 만들 수 있다. Two-account와
Exchange-only 방식은 Qlib Account/Position feedback을 잃거나 체결 상태의 source of truth를
이중화한다.

## 8. 구현 경계와 테스트 순서

구현은 `qlib-extended` adapter 안에 두고 production `src/kwam_enhanced_index`와 Qlib source를
수정하지 않는다.

최소 구현 단위는 다음과 같다.

1. `MatchedCapitalizationState`: baseline quantity/cash와 activation provenance
2. `MatchedCapitalizationAdapter`: signed intent를 causal composite action으로 변환
3. Qlib lifecycle hook: active order 전에 atomic activation/top-up 수행
4. `SignedExecutionObserver`: Qlib fill과 baseline에서 realized signed view 생성
5. artifact schema와 reconciliation validator

최소 contract test는 다음을 포함한다.

- full future ticker axis를 사용해도 first-observed 이전 상태가 모두 0
- 신규 ticker first-tradable bar activation의 NAV 변화가 0
- activation 뒤 active short가 underlying `SELL` 방향으로 실행
- short increase, cover와 long/short cross-zero 전환
- partial fill에서 target이 아니라 dealt amount로 signed quantity 갱신
- suspension, upper/lower limit과 volume clipping
- baseline capacity 부족과 funding reserve 부족 fail-fast
- corporate action 뒤 `A = C - B` 유지
- universe exit/re-entry와 retained baseline policy
- Qlib composite와 production signed ledger의 quantity/cash/PnL differential parity

구현 완료 전에는 matched capitalization을 지원한다고 표시하지 않는다. 현재 long-only twin과
Goal 0~15 contract는 regression baseline이며 이 문서는 다음 구현의 canonical decision이다.
