# `tests/sample/` — the sample journey the suite runs

PRD §11.4가 말하는 sample journey의 현재 구현. `src/vqapr/agent/sample/`에 출하되던 것을 record 170이
여기로 옮겼다: 어느 CLI 명령도, `vqapr.public`의 어느 이름도, skill의 어느 경로도 이 패키지에 닿지
않았으므로 wheel에 실린 테스트 코드였다(record 124가 지운 것과 같은 모양). 사용자 문(`vqapr new --sample`
같은)은 아직 없다 — 그것은 별도 결정이고, 그때까지 §11.4의 "명시적으로 materialize"는 이 suite가
`journey.install`/`journey.execute`로 하는 일이다.

`tests/conftest.py::sample_panel`이 panel을 세션당 한 번 만들고(record 169), 아홉 테스트가 그것을
자기 프로젝트에 설치한다. 아래는 이 journey가 담아야 하는 것에 대한 원래의 서술이다.

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
