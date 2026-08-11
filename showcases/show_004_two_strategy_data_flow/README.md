# 두 전략으로 읽는 qlibx data flow

Status: current

Last verified: 2026-08-11T09:18:40+09:00

Verified against: qlibx 0.1.0, implementations 061–065

이 showcase는 “dataset이 이미 등록되었다”는 지점부터 같은 PIT 가격이 두 실행 경로에서 어떻게 다른
state와 evidence로 이어지는지 비교한다. 맨 앞의 real-DW projection과 minimal registration은 다른 환경에서도
재현하기 위한 setup이며, 학습할 본 흐름은 registry snapshot부터 시작한다.

1. `PeerMomentumLongShortStrategy`: 선언한 peer group의 다른 종목 20-session 수익률 평균을 signal로
   사용하고, 횡단면 평균 제거와 unit-gross 정규화로 long-short alpha weight를 만든다. 이 weight는
   `hypothetical_signed` portfolio를 거쳐 AcademicExchange에서만 signed fractional position으로 실행된다.
2. `FiveSessionTopTenStrategy`: 직전 5-session 종가 수익률을 순위화하고 상위 10종목을 10%씩 보유한다.
   5 session마다 판단하고 다음 session 종가에 KrxExchange가 정수 수량·비용을 계산해 Account에 commit한다.

중요한 instrument 경계도 일부러 나란히 보인다. Academic 경로는 `AcademicRunSpec.listings`가 가상 venue의
listing 계약이다. KRX 경로는 `QlibxProject.add_instrument()`로 주식을 하나씩 추가하고 `daily_spec()`이 그
실행 환경을 frozen spec에 복사한다. Dataset registration과 instrument declaration은 같은 일이 아니다.

저장소 루트에서 다음 명령으로 재현한다.

```powershell
uv run python showcases/show_004_two_strategy_data_flow/run.py
```

생성 결과는 이 showcase의 `outputs/` 아래에만 저장된다. `summary.json`은 전체 검증 요약,
`academic_rebalances.csv`는 signed weight→Academic Fill 구간, `krx_decisions.csv`는 top-10 판단과 PIT read,
`krx_fills.csv`는 실제 simulator Fill·cost, `flow_trace_ko.txt`는 단계별 mental model을 담는다.

## 실제로 관측된 첫 흐름

공통 dataset snapshot에는 20종목 × 61 session = 1,220 rows가 있다. 첫 Academic decision은
2024-01-30 15:30 KST다. `RowsLookback(21)`로 420 rows를 읽었고 `max_available_at`은 decision과 같은
시각이었다. Strategy는 long 10/short 10, gross 1.0, net 약 0의 weight를 발행했다. 그 weight는 별도
portfolio artifact가 된 뒤 2024-01-31 종가에 20개 signed fractional Fill로 가상 체결됐다.

첫 KRX decision은 2024-01-09 15:30 KST다. `RowsLookback(6)`으로 120 rows를 읽고 5-session 수익률
상위 10개를 각각 0.1 target으로 발행했다. 다음 session인 2024-01-10 종가에 instrument lot, 현금과
명시적 cost rule을 적용해 정수 수량을 체결한 뒤 Account와 mark를 commit했다. 전체 11회 decision은
독립 pandas oracle의 top-10과 모두 일치했다.

최종 검증에서 Academic은 8회 rebalance, 160 hypothetical Fill, 음수 position 관측, 독립 weight oracle
오차 0, Strategy→Exchange weight 오차 0이었다. KRX는 `add_instrument` 20회가 frozen spec의 20개
instrument로 보존됐고 11회 execution에서 157개 Fill record를 만들었다. 이 중 실제 dealt quantity가
양수인 record는 143개이고, 14개는 lot rounding 등으로 `dealt_quantity=0`인 diagnostic record다. 이
구분 때문에 `fills` 배열 길이를 실제 거래 횟수로 그대로 해석하면 안 된다.

이것은 workflow correctness showcase다. 2024년의 고정 20종목 universe와 수동 peer group은
survivorship/selection/classification bias를 포함한다. Academic short는 borrow, locate, margin, collateral,
dividend, market impact 또는 실거래 가능성을 모델링하지 않는다. KRX 비용률도 showcase에서 명시한 단순화된
가정이지 특정 날짜의 실제 전체 거래비용을 주장하지 않는다.
