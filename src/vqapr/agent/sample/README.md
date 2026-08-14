# `agent/sample/` — optional sample journey

fresh user가 전체 mental model을 확인할 수 있도록 **명시적으로 materialize할 수 있는** 작은
샘플을 제공한다(PRD §11.4).

## 담아야 하는 것

- 작은 sample data
- sample project-local logic (DataModel 하나, StrategyModel 하나)
- config
- expected result

## 흐름

```text
sample data registration
|-> direct StrategyModel: signal + signed weights + research backtest
|-> DataModel output -> StrategyModel: signed weights + research backtest
|-> optional Ensemble StrategyModel
|-> optional physical / enhanced-index construction -> selected execution profile
-> portable artifacts, report, catalog lookup
```

## 경계

- **reference journey이지 hidden built-in alpha나 mandatory starter layout이 아니다.**
- user가 요청하지 않은 project에 **자동 생성하지 않는다.**
- 생성된 file은 product-owned example과 user-owned research code를 **구분해야 한다.**
