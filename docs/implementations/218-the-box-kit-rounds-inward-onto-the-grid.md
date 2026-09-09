# 218 — The box kit rounds inward onto the grid

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **닫는 이슈** | `docs/issues/092` — `optimize`가 shipped `single_name_cap`이 만든 bound를 거절한다 |
| **브랜치** | `develop` |
| **앞선 기록** | `217` · `208` (constraint는 kit이다) · `075` (canonical grid) |

---

## 왜 이 변경이 있는가

보고는 `Constraint.project`와 `call.constraint_bounds` 시절 것이지만 문제는 0.10.0의 kit으로 그대로
옮겨왔다. `vqapr.portfolio.bounds.single_name_cap`은 `max(cap, benchmark_i)`를 benchmark의 지수
그대로 돌려주고, benchmark는 DOUBLE field에서 `Decimal(str(float))`로 와 지수가 -16이며,
`optimize._on_grid`는 1E-12보다 가는 값을 거절한다("quantizing toward it could land outside the
caller's own box"). 패키지가 만든 박스를 패키지의 optimiser가 받지 않았다.

보고자의 우회책이 위험의 크기를 보여 준다: caller가 quantize하되 **방향**을 스스로 골라야 한다 —
upper는 내림, lower는 올림. 반대로 하면 mandate를 넓히고, 아무것도 그것을 보고하지 않는다(북은 자기가
받은 박스 안에 있으니까). 그 방향은 "bound"의 뜻을 소유한 패키지 안에 있어야 한다.

## 무엇이 어떻게 바뀌었는가

- `portfolio/bounds.py` — `_ceiling`(ROUND_FLOOR)·`_floor`(ROUND_CEILING)·`_on_grid(lower, upper)`.
  `single_name_cap`과 `intersect`가 반환 직전에 통과한다. `no_short`의 0과 1은 이미 grid 위다.
  손으로 만든 박스도 `intersect`를 거치면 grid에 앉는다. 좁히기만 하고 넓히지 않으므로 compliance
  의미는 보존된다. `QUANTUM`은 `optimize`에서 import한다 — `optimize`는 `bounds`를 import하지 않으니
  순환은 없다.
- `portfolio/optimize.py` — `_on_grid`의 거절 문구가 수리를 댄다: kit을 쓰라, 아니면 upper는
  ROUND_FLOOR·lower는 ROUND_CEILING으로 1E-12에 quantize하라.
- `make-compliance/references/the-box.md` — 한 문단.

`optimize` 자신이 quantize하는 대안(보고자의 1안)은 두지 않았다: 거절은 "가는 값은 받지 않는다"는
명시적 계약이고, 그것을 유지한 채 박스를 만드는 쪽에서 방향을 정하는 것이 규칙을 한 곳에 둔다.
kit을 안 쓰는 caller는 문구가 방향을 알려 준다.

## 검증

```
.venv/Scripts/python.exe -m pytest tests/portfolio tests/compliance tests/acceptance/test_enhanced_index.py -q
  110 passed (kit 변경 직후, 기존 suite) → 새 테스트 3개 추가 후 tests/portfolio/test_bounds.py 통과
.venv/Scripts/ruff.exe check src/   All checks passed
```

새 테스트(`tests/portfolio/test_bounds.py`):
- DOUBLE에서 온 0.2690387918366073이 ceiling 0.269038791836 / floor -0.269038791836으로 — 안쪽으로.
- kit이 만든 박스를 `optimize`가 받고, 같은 bound를 quantize 없이 넘기면 `vqapr.portfolio.bounds`를
  이름 댄 거절.
- 손으로 만든 가는 박스가 `intersect`를 거쳐 grid에 앉는다.

## 남은 것

callback 안에서 `OptimizeRefusal`이 raise되면 프레임이 패키지 것이라 `status_of`가 500으로 분류한다
— 보고자는 그것을 502로 봤다고 적었지만 어느 쪽이든 "입력 거절"이 결함으로 읽힌다. `094`의 후속
항목으로 남긴다: 패키지 helper의 typed refusal이 사용자 callback 안에서 나면 422가 맞다.
