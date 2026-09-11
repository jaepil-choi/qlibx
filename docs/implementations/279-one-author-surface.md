# 279 — 저자의 표면은 하나다: `vqapr.authoring`은 없고 `vqapr.public`뿐이다

| | |
|---|---|
| **작성 시각** | 2026-09-12 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M11b — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §12 · §17 "공개 어휘", 오너 결정 D8 · D11 (2026-09-11) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `278`(루프의 어휘) |
| **깨지는 변화** | 예. 0.16.0 |

---

## 왜 이 변경이 있는가

0.15.0에는 저자가 import할 이름이 둘 있었다. `vqapr.public`과 `vqapr.authoring`이다. records `126`–`132`가 두 이름이 같은
객체를 가리키게 맞췄다. 그래도 둘은 둘이었다. scaffold는 `from vqapr import authoring as va`를 가르쳤고, exchange와
instruments 템플릿은 `from vqapr.public import ...`를 가르쳤다. 오너의 결정(D8)은 "public으로 통일"이다.

그리고 run을 출발시키는 문 셋의 이름이 하는 일과 달랐다(D11).

- `verify_run`: 판정 전부에 답하고, 얼릴 수 있으면 얼린다. `RunVerdict`를 돌려준다. `vqapr check` · `run` ·
  `--jobs` worker가 모두 지나는 문이다.
- `run/preflight/freeze.py`의 `preflight_run`: 이름 → 값. 얼리기만 한다.
- 공개 `preflight_run`: 문을 지나 얼린 run을 건넨다. 거절이면 raise한다.

## 무엇이 어떻게 바뀌었는가

| 0.15.0 | 0.16.0 |
|---|---|
| `from vqapr import authoring as va` · `va.StrategyModel` | `from vqapr import public as vq` · `vq.StrategyModel` |
| `from vqapr.authoring import X` | `from vqapr.public import X` |
| `vqapr.authoring` (패키지) | 없음. import하면 `ModuleNotFoundError` |
| `run/preflight/verdict.py::verify_run` | `preflight` (판정 + 얼리기 → `RunVerdict`) |
| `run/preflight/freeze.py::preflight_run` | `freeze` (얼리기만) |
| `vqapr.public.preflight_run` | `vqapr.public.freeze` (문을 지나 얼린 run을 건넨다) |

- `vqapr.public`은 `authoring`만 내보내던 일곱 이름을 이제 함께 내보낸다: `AccountHistory` · `AccountHistoryInput` ·
  `DataCall` · `StrategyCall` · `EconomicAccountView` · `Observation` · `requirements_for`.
- `import vqapr` 뒤의 게으른 속성은 `vqapr.public` 하나다(`vqapr.__all__ == ("public",)`).
- scaffold 템플릿 셋, 스킬의 예시 코드, 출하 sample 전략, showcase 컴포넌트가 모두 `vq`를 쓴다. showcase 컴포넌트의
  바이트가 바뀌었으므로 지문과 run identity도 바뀌었다. digest 기준선은 릴리스 때 다시 기록한다.
- 층 표에서 과도기 행 `"authoring": 21`이 빠졌다.
- 컴포넌트를 싣지 못할 때의 거절문이 "`vqapr.public.StrategyModel`(DataModel · Compliance)을 상속하라"고 말한다.
  전에는 `vqapr.authoring.X`를 말했다.
- facade tripwire의 바닥이 6에서 7이 됐다. 출하 sample 전략(`agent/sample/reversal_5d.py`)이 이제 사용자의 전략처럼
  `vqapr.public`을 import하기 때문이다. 옆의 sample 거래소와 같은 이유로 바닥에 들어간다.
- `test_agent_first_authoring`은 `authoring`이 내보내던 이름 스물셋을 `AUTHOR_NAMES` 한 곳에 적는다. 그 이름이 모두
  `public`에 있는지, 그 값 타입이 프레임워크 상태(`version` · `memory` …)를 annotation으로 들여오지 않는지를 확인한다.
- 테스트 `test_one_authoring_surface`는 "두 이름이 한 객체"를 확인하던 곳이다. 이제는 "둘째 표면이 없다"를 확인한다.
  facade tripwire의 템플릿 고정은 새 import 줄을 본다.

## 검증

| 검사 | 결과 |
|---|---|
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1797 통과 · 5 skip (219 s). 1800에서 셋이 준 것은 "네 이름이 한 객체"를 이름마다 확인하던 매개변수 넷이 "둘째 표면은 없다" 한 테스트가 됐기 때문이다 |
| showcase digest | 지문을 떼고 내용으로 비교하면 표 46개가 모두 같다. 다른 것은 JSON 기록뿐이다(`278`과 같다). 기준선은 릴리스 때 다시 기록한다 |
| `uv run ruff check src/` | 통과 |
| `uv run pyright` | 0 errors, 0 warnings |
