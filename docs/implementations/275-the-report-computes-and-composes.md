# 275 — 보고서는 계산하고 조립한다: `analysis/`는 `report/`로

| | |
|---|---|
| **작성 시각** | 2026-09-11 KST (+09:00) |
| **캠페인** | 개념 트리 (`redesign/concept-tree`), M8 — 계획 `.agent/plans/active/concept-tree-campaign.md` |
| **설계 근거** | `docs/vqapr-architecture.md` §12 · §13 · §17, 오너 결정 (2026-09-11: 새로 지은 이름 `report/compose.py` 승인) |
| **브랜치** | `redesign/concept-tree` |
| **앞선 기록** | `270`(signals — `analysis/signal.py`가 먼저 나갔다), `274`(run) |

---

## 왜 이 변경이 있는가

캠페인 첫머리에 오너가 물었다. "analysis랑 report는 또 어떻게 다르지?" 답은 "다르지 않다"였다.

- `analysis/performance.py`(NAV · 수익률 · 낙폭)와 `analysis/execution.py`(체결 요약)를 읽는 곳은 보고서
  (`report/measure.py`)와 표면(`public`, `cli/run.py`)뿐이었다.
- 둘 다 run이 저장한 값만 받는다. 보고서의 원칙("run이 저장하지 않은 것은 계산하지 않는다")과 같은 것이다.
- `analysis/`의 세 번째 파일(`signal.py`)은 record `270`에서 `signals/evaluation.py`로 갔다. 남은 둘은 보고서의
  계산이다.

그리고 `report/record.py`는 기록을 열어 보고서를 조립하는 모듈이었다. 그런데 이름이 기록 패키지 `record/`와
겹쳤다. `report/document.py`의 `Series`는 패널의 열 `data/panel.py::Series`와 이름이 같았다.

## 무엇이 어떻게 바뀌었는가

| 옛 자리 | 새 자리 |
|---|---|
| `analysis/performance.py` + `analysis/execution.py` | `report/metrics.py` |
| `report/record.py` | `report/compose.py` (`strategy_report` · `run_report` · …) |
| `report/document.py::Series` | `report/document.py::Curve` (NAV · 수익률 · 낙폭 · 회전율 · 초과수익의 곡선) |

- `analysis/` 패키지는 사라졌다. 층 표에서도 `"analysis": 10` 행이 빠졌다. `metrics`는 보고서 층에 있다. 이
  모듈이 import하는 것은 `domain.account`와 표준 라이브러리뿐이다.
- `test_capability_absence`의 leaf 목록에서 `vqapr.analysis.performance`를 `vqapr.report.metrics`로 바꿨다. 이제
  체결 요약도 같은 검사를 받는다.
- `Curve`는 보고서 문서 안의 값이다. 공개 표면(`vqapr.public`)이 내보내는 `Series`는 패널의 것이고 그대로다.
  스킬은 보고서 곡선을 `.instants` · `.values`로 읽고 클래스 이름을 쓰지 않는다. 보고서 JSON에도 클래스 이름은
  나오지 않는다. 그래서 이 이름 변경은 저자에게 보이지 않는다.
- 테스트: `tests/analysis/test_performance.py` → `tests/report/test_metrics.py`.

## 검증

| 검사 | 결과 |
|---|---|
| `uv run python -m pytest tests/ -q -m ""` (test_all) | 1795 통과 · 1 실패 · 5 skip (212 s). 실패는 metrics 모듈의 공개 이름을 세 개로 못박은 테스트였다. 이제 넷(`fill_summary` 포함)이고 이름도 바꿨다. 파일을 다시 돌려 11개 모두 통과. M7에서 고친 테스트도 이번 전체 실행에서 통과했다 |
| `scripts/showcase_record_digest.py --check <campaign-digest.json>` | 81개 모두 일치 (캠페인 기준선) |
| `uv run ruff check src/` | 통과 |
| `uv run pyright` | 0 errors, 0 warnings |
