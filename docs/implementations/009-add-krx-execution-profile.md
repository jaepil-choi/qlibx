# 009 — KRX execution profile과 venue-owned 수량·비용 규칙

## 왜

Architecture §6.3은 두 fixture profile을 이미 규정하고 있었지만 `exchange/venues/krx.py`,
`exchange/listings.py`, `exchange/costs.py`가 전부 비어 있었다. 그래서 실행 가능한 profile이 Academic
하나뿐이었고, 더 중요하게는 **§6.1이 요구한 `plan_orders(..., rules: ExchangeRulesView)` 인자가 없었다.**

이 이탈은 실데이터에서 즉시 드러났다. 실제 종가로 weight 목표를 수량으로 바꾸면

```text
w=0.25, NAV=1e9, P=893,000  →  desired = -279.9552071668533034714445689
AcademicExchange            →  quantity violates listing rule
```

가 되어 **어떤 실제 가격으로도 weight 전략을 체결할 수 없었다.** show_001이 통과했던 것은
`0.5 × 100 / 100 = 0.5`, step `0.1`이라는 인위적 숫자 덕이었다.

## 무엇

### 수량 규칙은 venue가 소유하고 order 층이 적용한다

§6.1의 "venue마다 달라지는 것은 전부 `ListingRule`과 Exchange 구현 안에 있고, 여기 남는 것은 델타 산술
하나다"를 그대로 구현했다.

- `exchange/listings.py`: `ListingRule`(venue.py에서 이동) + `ExchangeRulesView`. `quantize()`가 0 방향
  내림을 수행하고 `minimum_quantity` 미달이면 정확히 0을 반환한다. divisible listing은 그대로 통과한다.
- `orders/planning.py`: `rules` 인자를 받아 delta를 quantize하고, 반올림된 매수가 현금과 매도 대금으로
  감당되지 않으면 결정적 순서로 clipping한다. **올림은 없고 없는 주문을 만들지 않는다.**
- `Exchange.execute`는 **재반올림하지 않는다.** 정수가 아니면 planning 결함이므로 거부한다.

nautilus도 같은 구조다. `Instrument.make_qty(value, round_down=True)`가 venue 정의에 속하고 호출자가
적용하며 matching engine은 검증만 한다.

### 비용은 commission과 tax로 분리한다

`exchange/costs.py`의 `CostRule`은 side별 요율을 선언하고 `select_cost_rule`이 **정확히 하나 매칭을
강제**한다(0개도 2개도 실패). `FillCost(commission, tax)`는 합계가 아니라 성분을 보존한다. slippage가
추가되면 필드 하나와 `total`만 바뀐다.

`Fill.cost`가 이 값을 나르고 `Fill.cash_delta`가 `-(dealt × price) - cost.total`을 계산한다.
`Account.prepare_fill`은 `next_cash += fill.cash_delta`로 비용을 차감한다. 비용이 Account를 우회하는
경로는 없다.

### KRX profile

`KrxExchange`가 선언하고 구현하는 것:

| 항목 | 값 |
|---|---|
| 수량 단위 | 1주, 0 방향 내림 |
| 위탁수수료 | 3bp, 매수·매도 양방향 |
| 증권거래세 | 20bp, 매도만 |
| 거래정지 | 체결 불가 → typed `NONTRADABLE` zero-dealt, 비용 0 |
| 공매도 | `held + delta < 0`이면 rebalance 전체 거부 |
| 체결 | 선택된 정확 시각 종가에 전량 |

**관리종목은 Exchange가 판단하지 않는다.** 보유 여부는 경제적 판단이므로 Strategy의 것이다. 그래서
`is_supervised`를 execution input이 아니라 **관측 데이터셋**에 실어 Strategy가 `DataRequirement`로 읽고
스스로 거른다. 거래정지는 반대로 venue의 사실이므로 execution input의 `is_tradable`이다.

### 미구현이며 주장하지 않는 것

호가단위, 상하한가, 동시호가 미시구조, 호가잔량, 유동성/참여율 기반 부분체결, 차입·대차, 증거금, 장중
행동. 비용은 선언된 수수료·세금 외에 **없는 것이지 0으로 측정된 것이 아니다.**

### 요율은 고정이되 effective-dating은 실제로 동작한다

KRX profile이 들고 나오는 기본 요율은 고정이다. 그러나 `CostRule`은 `effective_from`/`effective_to`
반열림 구간을 선언할 수 있고 `ExchangeRulesView.at(instant)`가 그 시각의 band로 좁힌다. 미사용 인자를 둔
것이 아니라 **동작하는 기능**이며 테스트가 이를 확인한다.

- 고정 요율만 선언한 venue는 `at()`이 자기 자신을 그대로 돌려주므로 비용이 없다.
- dated band를 선언하면 시각별로 다른 세율이 적용된다(예: 23bp → 20bp 전환).
- dated band를 instant 없이 조회하면 매칭 0으로 **실패한다.** 시점을 모르면 요율을 고를 수 없다는 것이
  묵시적 기본값보다 낫다.

실제 세율 이력 데이터를 등록해 쓰려면 `CostRule` 튜플을 그 이력으로 만들어 주면 되고, 계약 변경은 없다.

### 확장점 경계

`load_exchange`가 `SHIPPED_EXECUTION_PROFILES = (AcademicExchange, KrxExchange)` 중 하나의 subclass만
허용하고, 해당 profile의 `execute`를 교체하지 않았는지 검사하며, `ExchangeRulesView` 노출을 요구한다.
listing과 cost는 사용자가 선언할 수 있지만 체결 의미를 조용히 바꿀 수는 없다.

## 검증

**모든 검증은 실제 KRX 시장 데이터로 수행했다.** `tests/fixtures/real`은 `data/DW` 벤더 창고에서
`scripts/extract_dw_fixture.py`로 뽑은 커밋된 excerpt다(4종목 × 실제 거래일 22일). 창고가 있는 환경에서는
같은 슬라이스를 재추출해 커밋된 행과 일치하는지 검사하므로 fixture가 조용히 드리프트할 수 없다.

```text
uv run pytest -q
226 passed

uv run ruff check src tests scripts showcases
All checks passed!

uv run ruff format --check src tests scripts showcases
178 files already formatted
```

`tests/exchange/test_krx.py` 7건이 실제 종가로 다음을 확인한다.

- 3bp/20bp 요율이 선언값과 일치하고 side당 CostRule 중복은 거부된다
- 실가격 weight 배분이 정수 주문을 만들고 수수료 포함 현금 안에 들어간다
- 매도가 수수료와 거래세를 함께 물고 `cash_delta`와 Account 현금이 정확히 일치한다
- 공매도 주문은 거부된다
- 정지 종목은 zero-dealt이며 비용 0이고 requested 수량은 남는다
- 내림 잔여가 intended보다 작고 1주 미만이며 잔여 현금이 정확히 맞는다

`showcases/show_004_krx_execution_profile`은 하나의 frozen strategy를 두 profile로 실행한다. 2026-04-01 ~
2026-05-29, KOSPI200 6종목, 34회 리밸런스, 초기 현금 10억.

| | Academic | KRX |
|---|---|---|
| final NAV | 1,895,960,196.32 | 1,865,987,436.94 |
| dealt fills | 80 | 77 |
| traded notional | 20,871,637,793.57 | 20,699,378,200.00 |
| commission | 0 | 6,209,813.46 |
| sale tax | 0 | 19,763,149.60 |
| whole shares only | no | yes |

실효 비용은 거래대금 대비 **12.55bp**다(양방향 3bp + 매도분 20bp). NAV 격차 29,972,759는 부과된 비용보다
큰데, 정수 내림이 매 리밸런스마다 의도 비중을 조금씩 미달시키기 때문이다. 두 run 모두 자기 fill journal
만으로 현금·포지션을 독립 재계산해 커밋된 Account와 일치함을 assert하며, 불일치 시 showcase가 중단된다.

## 한계와 후속

- KRX 기본 요율은 고정값이다. 실제 한국 세율 이력을 반영하려면 그 이력을 `CostRule` band로 선언해야
  하며, 이 package는 그 이력 데이터를 들고 있지 않다.
- fully-invested weight book(`cash_target = 0`)은 Decimal 유한 정밀도에서 NAV를 미세하게 초과할 수 있어
  mutation 전에 거부된다. 이는 올바른 fail-closed 동작이며 show_004는 2% 현금 버퍼를 둔다.
- `plan_orders`의 clipping은 §6.2가 말한 빠른 경로/느린 경로를 하나의 결정적 경로로 구현했다. 결과는
  같지만 대규모 유니버스에서 빠른 경로 분기를 별도로 두는 최적화는 하지 않았다.
