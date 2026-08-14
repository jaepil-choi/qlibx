# `strategy_model` template

StrategyModel — 자본을 어떻게 나눌지 판단한다. `decide(ctx) -> PortfolioIntent`.

채워야 할 것: `trigger()` · `requirements()` · `warmup()` · `decide()`.

통과 조건: `PortfolioIntent`만 반환한다 · warm-up 선언이 지켜진다 · hold가 완전한 target으로 온다 · 다른 run을 실행하지 않는다.

## 이 디렉터리에 있어야 하는 파일

- 구현 파일 — 채워야 할 계약. TODO가 표시되어 있다
- 선언 파일 (`.yaml`) — `ComponentRef`가 될 선언
- conformance 테스트 — `vqapr.testing.conformance`를 호출한다. **처음에는 실패한다**
- 이 README — 각 TODO가 무엇을 요구하는지

## 흐름

```bash
vqapr new strategy_model ./my_component
cd my_component && pytest        # conformance가 통과할 때까지
vqapr check .                    # 같은 검사, 기계 판독 결과
vqapr register . --project ../research
```
