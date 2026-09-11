# 270 — 신호와 포트폴리오는 주제로 가른 두 패키지다

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M4 — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §7.5 · §13, 오너 결정 D7 (2026-09-11) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `268`(intent · budget은 domain으로), `269` |

---

## 왜 이 변경이 있는가

저자가 부르는 순수 함수가 세 곳에 흩어져 있었다: `transforms/`(순위 · 중립화 · Fama-French), `analysis/signal.py`(IC ·
적중률 · decay), `portfolio/`(가중 · 최적화 · 상자 · 배분 · 상쇄 측정). 오너는 "순수 함수라면 묶어야 한다"고 했고, 결정은
**주제로 가르는 것**이었다(D7): 기술적 성질("순수 함수")이나 호출 방향("저자가 부른다", toolkit)은 폴더의 기준이 아니다.
파이썬 퀀트 생태계 자체가 신호 평가(alphalens)와 포트폴리오 구성(PyPortfolioOpt)을 따로 둔다.

## 무엇이 어떻게 바뀌었는가

| 새 자리 | 무엇이 들어왔나 |
|---|---|
| `signals/transform.py` | `transforms/cross_section.py`(`rank`) + `fama_french.py` + `neutralize.py` |
| `signals/evaluation.py` | `analysis/signal.py` (IC · rank IC · 적중률 · decay · correlation) |
| `portfolio/weights.py` | `portfolio/weighting.py` (이름만) |
| `portfolio/netting.py` | `portfolio/diagnostics.py` (이름만 — 하는 일이 "멤버 비중의 상쇄를 재기"다) |

`portfolio/intents.py` · `budgets.py`는 이미 record `268`에서 `domain/intent.py`로 갔다(결정의 값이지 함수가 아니다).
`transforms/` 패키지는 사라졌고, `analysis/`에는 `performance.py` · `execution.py`가 보고서 단계(M8)까지 남는다.

- 이름은 `signals`(복수)다 — 표준 라이브러리 `signal`을 가리지 않게(D2).
- 합친 세 transform 파일은 비공개 helper 이름이 겹치지 않았다(`_checked` · `_values` · `_SCALE` · `_fraction`).
- 층 표: `transforms` → `signals` (층 10). `signals`는 vqapr의 어떤 모듈도 import하지 않는다.
- `tests/boundaries/test_capability_absence.py`: leaf 목록을 새 모듈 둘로. 금지 목록의 `vqapr.account`는 record `268`부터
  없는 패키지라 늘 통과하던 죽은 줄이었다 — 지우고 이유를 적었다(계좌 권한이 `analysis.performance`가 읽는 mark 값과 같은
  모듈 `domain/account.py`에 있어 모듈 단위로는 가를 수 없다).
- `test_neutralize.py`의 "중립화는 제약의 모양을 갖지 않는다"는 이제 transform 모듈 전체(`rank` · Fama-French 둘 ·
  `neutralize`)에 대해 같은 것을 확인한다.
- 테스트 미러: `tests/transforms/*` · `tests/analysis/test_signal.py` → `tests/signals/`, `tests/portfolio/`의 두 파일 이름.
- 옛 경로를 적은 docstring 넷(`authoring/result.py` 셋, `report/document.py`)과 characterization 테스트 docstring 하나를 새
  경로로.

## 트레이드오프

`rank` · `neutralize` · Fama-French가 한 파일(약 330줄)이 됐다. 셋은 "값을 값으로"라는 한 주제이고, 파일이 800줄 기준에서
멀다. 하나가 커지면 그때 나눈다.

## 검증

| 검사 | 결과 |
|---|---|
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1792 통과 · 5 skip (212 s) — 1794에서 둘이 준 것은 `test_capability_absence`의 leaf 매개변수가 다섯 모듈에서 셋으로 합쳐졌기 때문(검사 대상 코드는 같다) |
| `scripts/showcase_record_digest.py --check <campaign-digest.json>` | 81개 모두 일치 (캠페인 기준선) |
| `uv run ruff check src/` | 통과 |
| `uv run pyright` | 0 errors, 0 warnings |
| `tests/boundaries/test_capability_absence.py` | 두 leaf 모두 금지 목록의 어느 것도 끌어오지 않는다 (test_all에 포함) |
