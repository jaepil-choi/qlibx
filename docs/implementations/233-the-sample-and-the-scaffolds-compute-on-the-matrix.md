# 233 — The sample and the scaffolds compute on the matrix

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | one-door 캠페인 P2 (`.agent/plans/active/one-door-campaign.md`) |
| **이슈** | `docs/issues/096` — 닫는다 |
| **설계 근거** | 기록 `232` (`PanelWindow.matrix()`) · 오너 지적 2026-09-10 "5일 close lookback 받은 2d panel을 가지고 axis=0 으로 mean 해주고 부호만 - 로 해주면 되잖아" |
| **브랜치** | `redesign/one-door` |
| **앞선 기록** | `232` (A field is one block, and a window is a matrix) |

---

## 왜 이 변경이 있는가

기록 `232`가 창을 행렬로 주게 됐으니, 그 창을 종목 for loop으로 읽던 세 곳 — sample 전략
(`agent/sample/reversal_5d.py`), `vqapr new strategy`가 내는 scaffold, `vqapr new datamodel`이 내는
scaffold의 panel 두 flavour — 가 그것을 쓴다. 이 셋은 사용자가 처음 복사하는 코드다: 여기가 루프를
돌면 모든 사용자 전략이 루프를 돈다.

## 무엇이 어떻게 바뀌었는가

```text
agent/sample/reversal_5d.py     closes = window.matrix()
                                complete = isfinite(closes).all(axis=0) & (rows == LOOKBACK)
                                returns = closes[-1] / closes[0] - 1.0     ← 한 줄, 모든 종목
                                weakest = sorted((returns[j], name))[:3]   ← 동점은 id로 (재생 동일)
                                Decimal은 Rebalance 경계에서만

extension/scaffold.py           _STRATEGY_TEMPLATE      matrix() · complete · scores = closes[-1]/closes[0]-1 · Rebalance.of(float)
                                _PANEL_BODY_BLOCK       matrix() · first/newest per name · eligible · signal · derived (rows · calendar)
                                _ROWS_BODY_BLOCK        rows grain: 공유 시각 축이 없으니 종목별 Decimal 축약 그대로
                                flavour: history_block → body_block · imports · eligibility
                                빈 창 가드: 전략은 Hold, datamodel은 [] (argmax on empty axis는 예외)

skills/*/references/reading-inputs.md   matrix()가 무엇인지 한 문단 (전략 · datamodel)
_shipped.json                   두 파일 재기록
```

- `Rebalance.of(long=chosen)`은 float conviction을 받는다(`Decimal | int | float | str`). 정확한
  산술은 프레임워크가 비중을 만들 때 한다.
- sample의 정렬 키 `(return, name)`은 옛 코드와 같다. Decimal 나눗셈과 float 나눗셈이 순서를 바꿀 수
  있는 것은 동점뿐이고, 동점은 name이 가른다.
- datamodel scaffold의 출력은 창의 행렬 위 float 나눗셈이라 `105/100 - 1`이 `0.050000000000000044`다; 그 값을 `0.05`로 고정하던 테스트 둘은 `pytest.approx`로 비교한다(출력 필드는 DOUBLE이고 그 마지막 비트는 이진 float의 것이다).
- 옛 텍스트를 고정하던 테스트 둘(`test_neither_template_collects_a_raw_cell`,
  `test_the_scaffold_offers_both_lookbacks`)은 새 guard 철자를 고정한다: panel 템플릿에는 `Decimal(`이
  없고 `for name in window.instruments`도 없다; rows grain 템플릿에는 `Decimal(str(value))`가 남는다.

**하지 않은 것.** showcase의 전략들(`show_002` · `003` · `004`)이 `window.values[name]`으로 읽는 것 —
그것은 사용자 코드의 자리이고 digest 기준선이 그 출력을 고정한다. `values`·`series` 삭제 — 이름
하나의 시계열은 여전히 그 길이다.

## 성능 (`exp_231`, 3,000 × 6)

sample decide: 종목 루프 + Decimal 12.3 ms → `matrix()` 위 1.5 ms (best of 3, 같은 답).

## 검증

| 검사 | 결과 |
|---|---|
| `tests/extension tests/agent` + scaffold CLI 테스트 (slow 포함) | 234 passed — 40줄 한도(`test_the_emitted_strategy_fits_in_forty_lines`)에 맞추느라 전략 템플릿을 39줄로 다듬었다 |
| sample journey (slow) · scaffold unedited (slow) | passed |
| fast suite | 1672 passed, 29 deselected |
| digest | 83/83 |
| `scripts/record_shipped_skills.py --check` | every shipped skill file is recorded |
| pyright (src) | 0 |
