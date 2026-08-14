"""배분 — 부호는 입력에서, 크기의 출처만 다르다.

**이 파일은 순수 leaf다. 아래를 import하지 않는다.**

    vqapr.data  vqapr.account  vqapr.exchange  vqapr.runtime  vqapr.flow  vqapr.models

이것이 없으면 built-in은 편의 함수가 아니라 **보이지 않는 곳에서 경제적 판단을 내리는 두 번째
StrategyModel**이 된다. 시가총액이 필요하면 **인자로 받는다** — 여기서 직접 읽으면 그 data가
StrategyModel의 declared requirement를 거치지 않아 lineage에 남지 않는다(`UC-BUILTIN-001`).

구현할 것
    signal_weight(signal, *, cash_range)              크기가 |signal|에 비례
    equal_weight(signal, *, cash_range)               균등
    proportional_weight(signal, sizes, *, cash_range) 크기 panel에 비례

지켜야 할 것
    - 예산은 **현금 범위**로 선언한다. cash_range=(0, 0)이면 전부 배분, 넓게 두면 남길 수 있다.
    - budget을 스스로 결정하지 않는다. 선언된 것보다 적게 배분된 결과를 자동으로 채우지 않는다.
    - `sizes`에 선택된 종목이 없으면 **계산 전에 실패**한다. 빼고 재정규화하지 않는다.
    - `signal`의 결측은 다루지 않는다. 호출자가 `transforms/missing.py`로 먼저 해소한다.
    - 선택된 종목이 없으면 실패하지 않고 **빈 weights**를 낸다 — hold를 표현할 수 있어야 한다.
    - 같은 입력에 같은 출력. run identity도 decision time도 account version도 모른다.
    - **PortfolioIntent를 반환하지 않는다.** intent 조립과 lineage 기록은 StrategyModel의
      책임이다(`intents.py`).

signal과 weights는 shape가 같고 의미가 다르다
    타입이 경계를 지켜주지 못하므로, **이 함수를 통과했다는 사실 자체가 전환이 의도되었다는
    증거**가 된다(PRD §5.3).
"""
