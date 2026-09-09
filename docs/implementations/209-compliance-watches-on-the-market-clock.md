# 209 — Compliance watches on the market clock

| | |
|---|---|
| **작성 시각** | 2026-09-09 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M9 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md` 3b) — M8(`208`)과 한 커밋 |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §4 (배선표: Compliance = 시장 시계 · 창 + committed 계좌 · 게시판) · §7.2 |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `208` (The box is the strategy's) |

---

## 왜 M8과 한 커밋인가

ExecPlan은 M8 착수 시 결정하라고 했다. 따로 가면 M8 커밋에서 COMPLIANCE 자리가 비고(`monitor_at`이
돌릴 것이 없다), `vqapr.monitoring` 테이블과 record의 `contract` 블록이 한 커밋 동안 사라졌다
돌아오며, showcase 005·006·008과 monitoring을 보는 테스트 열 개를 두 번 고친다. 두 번째 digest
재기록도 생긴다. **중간 상태에 정직한 이름이 없으면 그 상태를 만들지 않는다.** 그래서 한 커밋, 기록은
둘.

---

## 무엇이 어떻게 바뀌었는가

### 확장점 `Compliance`

```python
class Compliance(Component):
    compliance_id: str                     # 등록된 id와 같아야 한다 (load에서 검사)
    tolerance: Decimal | None = None       # 프레임워크 기본선 max(bound·1%, 10bp)
    def observe(self, call: ComplianceCall, account: EconomicAccountView) -> ComplianceFinding
```

멤버 하나. §7.2의 셋이 그대로 코드다 — **구독한다**(`inputs()`, `call.read`는 관측 시각 기준),
**기억한다**(`memory`가 `observe` 전에 복원되고 finding과 함께 commit), **committed 계좌를
관측한다**(`EconomicAccountView`, 마크 직후). 계좌를 바꾸지 않는다: `prepare_monitoring`은 pending도
계좌도 건드리지 않고 행과 memory만 더한다.

**전략의 값을 물려받지 않는다(소유자 결정).** 옛 `monitor`는 자기 `project`가 만든 box를 셋째
인자로 받아 그 안에서 재고 있었다. `observe`는 아무것도 못 받는다. shipped `single_name_cap`은 자기
`cap`과 자기 벤치마크 구독으로 `ceilings()`를 만들고, 전략은 kit으로 자기 box를 만든다. 둘이 같은
숫자를 받으면 같은 ceiling이 나온다는 것을 `tests/compliance/test_builtin.py`가 못박는다 — 그래야
리포트에서 둘이 갈릴 때 그것을 노이즈가 아니라 정보로 읽을 수 있다.

### 배선

| | 옛 | 지금 |
|---|---|---|
| 선언 | `strategy: {constraints: [...]}` | `compliance: [...]` — **run에**, `exchange:` 옆 |
| freeze | `FrozenStrategy.constraints`/`constraint_requirements` | `FrozenStrategy.compliance: ComplianceSet`/`compliance_requirements` (identity가 접는다) |
| 창 | `constraint_window_for_occurrence`(콜백) + `constraint_window_at`(마크) | `compliance_window_at`(instant) 하나 |
| 단계 | `SimulationStage.MONITORING` | `MARKET_COMPLIANCE = "simulation.market.compliance"` — M7의 `MARKET_ACCRUE`와 같은 체계 |
| 호출 | `ValuationHandler.monitor_at(cutoff, occurrence=)` | `ComplianceHandler.observe(instant)` — `flow/strategy/compliance.py` |
| 테이블 | `vqapr.monitoring`의 `constraint` 열 | `rule` 열. 나머지 열·stage `MONITORING`·`event_time` 그대로 |
| record | `strategy.json`의 `constraints` | `compliance`. `contract` 블록은 rule id로 키 |
| report | `Compliance.constraints: [ConstraintSummary]` | `Compliance.rules: [ComplianceSummary(rule=...)]` |
| 등록 | `register_constraint` · `vqapr new constraint` · kind `constraint` | `register_compliance` · `vqapr new compliance` · kind `compliance` |
| 실패 코드 | `component.constraint_id_mismatch` · `constraint.identity_mismatch` | `component.compliance_id_mismatch` · `compliance.identity_mismatch` (baseline 재생성) |

`_handle_market`의 넷째 줄이 `self._compliance.observe(instant)`다. `MonitoringEvidence`에서
`occurrence`가 빠졌다 — 관측자에게는 가리킬 결정이 없다(`207`이 예고한 것).

### 선언이 run에 있는 이유

datamodel run은 `compliance`를 선언하면 거절된다(*"no account for a rule to observe"*). 전략 아래가
아니라 venue 옆에 두는 것은 §7.2를 구조로 말하는 것이다: 규칙의 파라미터는 규칙의 것이지 전략의 것이
아니다.

### 스킬·scaffold

`make-constraint` → `make-compliance`(SKILL.md · `references/{the-box,observe,declaring-data,tolerance}.md`).
`make-strategy/references/public-helpers.md`에 kit 절. run-declaration·run-backtest·introduce·inspect·
analyze-result 다섯 스킬의 문구. `vqapr new compliance <id> --cap` 템플릿은 `observe` 하나를 낸다.
`_shipped.json`에 열여섯 해시.

### AC-10 — 판단이 없는 날에도 breach를 잡는다

`tests/flow/strategy/test_monitoring_findings_reach_the_record.py`: Hold만 하는 전략, 세션마다 15:30
프린트 하나 → 세션마다 규칙 둘이 관측하고 행을 남긴다(`UC-EXEC-003`). **관측만 하는 규칙이 bound
없이 등록된다**: `no_short`는 `inputs() == {}`, `observe`뿐, `vqapr new compliance`가 내는 것도 그렇다.
`tests/flow/strategy/test_a_compliance_rule_remembers.py`: 관측 넷이 `{"breaches": 4}`를 root에 남기고,
`observe`가 memory를 바꾸고 실패하면 root에는 mark만 남고 memory는 없다(`MARKET_COMPLIANCE`, after
commit).

---

## 무엇을 잃었나

- `ComplianceContext`는 `ConstraintContext`의 이름 바꾸기다 — 읽기 표면은 그대로.
- 옛 `test_monitoring_projects_at_the_fill_instant_and_reuses_its_projected_bounds`의 주장("판정은
  콜백의 bound가 아니라 fill 시각에 다시 투영한 bound로")은 투영이 없어져 무의미해졌다. 남은 주장은
  "규칙은 fill 시각에, 콜백에서는 한 번도, 관측한다"다.

---

## 검증

```
uv run python -m pytest tests/ -q -m ""       1643 passed (208s)
uv run ruff check src/                         All checks passed
uv run python -m pyright                       0 errors
scripts/showcase_record_digest.py --check      16/81 이동 → 재기록 → 83/83
```

원인표 — 무엇이 왜 움직였나:

| 무엇 | 몇 개 | 왜 |
|---|---|---|
| `strategy.json` (규칙 없는 run 전부: 005 alpha, 006 reversal·momentum, 007, 008 세 멤버 × replicate 둘) | 14 | record 키 `constraints: []` → `compliance: []`. 그 외 한 글자도 안 움직였다 |
| show_003의 datamodel record (`showcase-score`) | 2 (신규) | 기준선이 M0부터 show_003을 안 담고 있었다("81 entries / 6 showcases"). 이번에 들어온다 → 83 |
| 테이블 | 0 | `run_id`는 identity가 접히는 열이라 움직였지만, digest는 그 열을 이미 M5에서 재기록했고 이번 identity 변화는 키 이름뿐이라 값이 같다 |

**AC-9.** 규칙을 선언하는 run 셋(show005-index · show006-ensemble · show008-ensemble)은 record를
`outputs/`에 남기지 않아 digest 밖이다. 대신 M7 worktree(`f6dfa7e4`)에서 같은 showcase 셋을 돌려
비교했다: (1) `outputs/` 아래 parquet 53개가 `run_id` 열을 빼고(`constraint` 열은 `rule`로 읽어)
행까지 같다, (2) `manifest.json`·`trace.json`의 index/ensemble 블록 — rebalances · frozen 횟수 ·
final_active_norm · monitoring 횟수·drift · replay 검사 — 이 같다. 갈린 것은 공개된 allocation
parquet의 sha256뿐이고 그것은 `run_id` 열이다.

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **`due_boundary`의 owner는 `layer.compliance`(ComplianceSet)다.** 실패한 규칙 하나가 아니라 선언
  전체. 규칙 하나를 가리키려면 `evaluate_compliance`가 규칙마다 boundary를 열어야 하는데, 그러면 실패
  뒤 나머지 규칙의 관측이 사라진다. 지금은 "이 시각의 COMPLIANCE가 실패했다"가 단위다.
- **arity 픽스처는 이름만 바꾸면 무력화된다.** `monitor(self, account, marks)`는 옛 계약(4)에 대해
  하나 짧았지만 새 계약(3)에는 딱 맞는다. `observe(self, account)`로 바꿔야 "짧다"가 유지된다 —
  test_conformance · test_register · refusal_codes 셋 다.
- **heredoc 안의 `\\n`은 믿지 않는다** (M7 흔적의 재확인). 문자열에 백슬래시가 있으면 Write 도구로
  스크립트를 쓴다.
- **시스템 python으로 `vqapr.public`을 import하면 pydantic이 없다.** 테스트 기대값을 모듈에서
  재생성하는 스크립트는 `uv run python`으로 돈다.

---

## 다음 기록이 이어받을 것

- **Stage 3의 셋째 — M10.** `ExecutionCall`에 종목 사전(M3의 경로를 계약으로), venue 설정 스키마.
  Exchange가 `Component`인 것은 그대로.
- `MonitoringResult`·`MonitoringEvidence`·`LifecycleKind.MONITORED`·`MONITORING_STAGE`·테이블
  `vqapr.monitoring`은 이름을 안 바꿨다 — "monitoring"은 행위이고 Compliance는 역할이다. 바꾸려면
  record 열 이름과 report가 같이 움직인다.
