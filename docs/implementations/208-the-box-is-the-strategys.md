# 208 — The box is the strategy's

| | |
|---|---|
| **작성 시각** | 2026-09-09 KST (+09:00) |
| **캠페인** | 두 시계 캠페인 M8 (`docs/refactoring/2026-09-09-the-two-clocks-campaign.md` 3a) — M9(`209`)와 한 커밋 |
| **설계 근거** | `docs/design/two-clocks-and-the-wiring-table.md` §7.1 (Constraint는 확장점이 아니다) · §8 (PRD §7·§12.3·§12.4 뒤집힘) |
| **브랜치** | `redesign/two-clocks` |
| **앞선 기록** | `207` (One instant, one order) |

---

## 왜 이 변경이 있는가

`Constraint`는 멤버가 둘이었다. `project`는 결정 전에 전략에게 box를 만들어 주고, `monitor`는
commit된 장부를 판정했다. 하나는 전략 시계 위에서 무상태로, 하나는 시장 시계 위에서 세면서 —
**한 객체의 두 멤버가 서로 다른 시계 위에 살았다**(M6 발견). 설계 §7.1은 그 앞 반쪽을 이렇게
읽는다: *"best effort는 재량이고 재량은 전략의 것이므로 프레임워크가 보장할 것이 없다."* 프레임워크가
보장할 것이 없는 것은 확장점이 아니다.

부수적으로 정직해지는 것이 있었다. `single_name_cap`이 벤치마크 비중을 읽는 것은 constraint의
`inputs()` 안에 숨어 있어서, **전략의 데이터 의존성이 전략에 보이지 않았다.** showcase 006·008의
ensemble 전략은 벤치마크를 구독하지 않으면서 벤치마크 상대 cap 안에서 최적화하고 있었다.

---

## 무엇이 어떻게 바뀌었는가

### kit — `vqapr.portfolio.bounds`

```python
lower, upper = intersect(no_short(names), single_name_cap(names, benchmark, cap))
optimize(desired=..., lower=lower, upper=upper, ...)
```

셋 다 순수 함수다. 이름과 숫자가 들어가고 `(lower, upper)` — 이름마다 한 쌍의 `Decimal` —가
나온다. 그것이 `optimize`가 받는 모양 그대로라 저자가 만들어야 할 타입이 없다(`ConstraintBounds`는
사라졌다). `no_short`는 `[0, 1]`, `single_name_cap`은 `[-max(cap, bench_i), +max(cap, bench_i)]`
(사이즈 cap이라 floor가 ceiling을 거울로 비춘다), `intersect`는 이름별 max/min이고 이름이 빠진
box는 거절한다 — 빠진 bound는 feasible set을 조용히 넓힌다. **long-only는 둘의 교집합에서만
나온다**(`tests/portfolio/test_bounds.py`).

### 전략이 구독한다

`single_name_cap`에 벤치마크를 주는 것은 전략이다. showcase 005는 이미 구독하고 있었고, 006·008은
`benchmark_dataset_id`·`cap`·`benchmark_tolerance`를 config로 받아 `requirements()`에 벤치마크를
더했다. 셋 다 옛 constraint가 `project` 안에서 하던 `validate_allocation(LONG_ONLY, tolerance)`를
box를 만들기 전에 스스로 한다 — `UC-CONSTRAINT-002`의 보장(*"binding이 없으면 결과를 만들기 전에
실패"*)은 콜백 실패의 원자성(PRD §3.6)으로 유지된다.

### 사라진 것

- `authoring.Constraint` · `ConstraintBounds` · `ConstraintCall` · `ConstraintFinding`(→ `ComplianceFinding`,
  `209`) · `StrategyCall.constraint_bounds` · `StrategyModelContext.constraint_bounds`.
- `constraints/` 패키지 전부. `project_constraints`·`merged_constraint_bounds`·`ProjectedConstraintFinding`.
- `flow/strategy/callback.py`의 projection 경로 — 콜백은 이제 전략 하나만 부르고, 전략 외의 component
  memory를 commit하지 않는다. `CallbackEvidence.constraints` 필드.
- `StrategyEntry.constraints`. 그 자리에 오는 것은 `constraints:`를 이름으로 거절하는 validator다
  (*"declare `compliance: [...]` on the RUN"*).
- `ComponentKind.CONSTRAINT`, `vqapr new constraint`, `register_constraint`, skill `make-constraint`.

### AC-9 — showcase 005·006·008이 같은 결과를 낸다

digest는 identity(`compliance` 선언이 접힌다)와 `vqapr.monitoring`의 열 이름(`constraint` → `rule`)
때문에 재기록됐지만, **`run_id`·`rule` 열을 뺀 테이블은 M7 worktree와 바이트까지 같다** — 005·006·008
전부(원인표는 `209`). 006·008은 전략이 새로 벤치마크를 구독했는데도 같은 결과다: 옛 constraint가
같은 데이터를 같은 시각에 읽고 있었기 때문이다.

---

## 무엇을 잃었나

- **§7.1의 *"constraint별 before/after와 잔여 보존"*이 프레임워크 보장에서 전략의 기록으로
  내려갔다.** 콜백 evidence는 더 이상 projection을 나르지 않는다. 논문이 "이 제약이 시그널에서 무엇을
  깎았나"를 보이려면 전략이 `self.recorder`로 남긴다 — 다른 무엇을 남기듯이.
- `tests/extension/test_conformance.py::test_every_problem_is_reported_at_once`를 지웠다. 두 멤버가
  동시에 틀린 Constraint로 "한 번에 다 보고한다"를 증명하던 테스트인데, 남은 kind 중 contract 메서드가
  둘인 것은 StrategyModel뿐이고 그쪽은 loader가 `decide` arity를 먼저 거절해서 두 코드가 한 진단에
  담길 길이 없다. collector의 성질 자체는 남아 있고 다른 테스트가 한 문제씩 본다.
- `ComponentKind`는 여전히 넷이다(`COMPLIANCE`가 `CONSTRAINT`의 자리). 아키텍처 §10.2의 "넷 + Accrual
  자리"에서 Accrual은 M7의 handler일 뿐 kind가 아니다.

---

## 검증

`209`의 표를 본다 — 한 커밋이다.

---

## 남긴 흔적 — 다음 사람이 같은 구덩이를 피하도록

- **kit 함수는 `Mapping`을 받고 `dict`를 돌려준다.** `CrossSection`을 강요하지 않았다 — 저자 코드는
  `dict`를 만들고 `optimize`는 `Mapping`을 받는다. 프레임워크 타입이 저자 손에 들어갈 이유가 없다.
- **`StrategyEntry`가 pydantic dataclass라 `constraints=` kwarg는 `model_validator(mode="before")`에
  Mapping으로 안 온다.** 친절한 거절은 `RunDefinition._from_the_stored_spelling`이 strategy 블록을
  읽는 자리에서 한다.
- **showcase 006·008의 전략 config는 `tolerance` 지역변수를 쓴다** — constraint를 등록하던 함수 안에
  이미 있었다. 그 변수가 정의된 뒤에 `register_strategy_model`이 오는지 봐야 한다(둘 다 그랬다).
- **`test_public`의 `__all__` 튜플은 모듈에서 재생성했다.** 손으로 정렬하면 ruff의 isort 순서와 어긋난다.

---

## 다음 기록이 이어받을 것

- `209`가 같은 커밋의 다른 반쪽 — `Compliance`.
- M10: `ExecutionCall`에 종목 사전, venue 설정 스키마.
