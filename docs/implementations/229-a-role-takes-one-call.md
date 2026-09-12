# 229 — A role takes one Call

| | |
|---|---|
| **작성 시각** | 2026-09-10 KST (+09:00) |
| **캠페인** | 한 루프 캠페인 L5 (`docs/refactoring/2026-09-10-the-one-loop-campaign.md`) |
| **참고** | 네 종류 캠페인 기록 `203` · `tests/boundaries/test_a_role_has_one_call.py` (`redesign/four-kinds-and-the-journal`) |
| **브랜치** | `redesign/one-loop` |
| **앞선 기록** | `228` (One member runner, one facts block) |

---

## 왜 이 변경이 있는가

네 역할 중 셋은 Call 하나를 받았다.

```python
DataModel.compute(call: DataCall)
StrategyModel.decide(call: StrategyCall)
Exchange.execute(call: ExecutionCall)
Compliance.observe(call: ComplianceCall, account: EconomicAccountView)     # 하나만 옆문이 있었다
```

`Call`은 DTO가 아니라 **capability object**다. 역할이 볼 수 있는 것은 Call에 있는 것뿐이고, 그래서
PIT는 지켜야 할 규칙이 아니라 접근 불가능이다(아키텍처 §2.2·§10.1). 인자를 옆에 하나 더 받는 순간
그 약속이 시그니처 밖으로 샌다. 배선표(`domain/wiring.py`)는 Compliance가 받는 View로
`COMMITTED_ACCOUNT`를 적어 두었으니, 표와 계약이 어긋난 유일한 자리였다.

소유자 결정(2026-09-10): 사용자 코드를 깨는 것은 상관없다. 0.10.0이 이미 `Compliance` 계약을 세웠고
0.11.0은 breaking 항목을 안고 있다.

## 무엇이 어떻게 바뀌었는가

- `authoring/call.py` — `ComplianceCall.account` (abstract property). docstring이 "계좌는 `observe`의
  인자"라던 것을 뒤집었다.
- `authoring/context.py` — `ComplianceContext(window, account, instruments, reads)`.
- `authoring/component.py` — `Compliance.observe(self, call: ComplianceCall) -> ComplianceFinding`.
- `compliance/evaluation.py` — view를 context에 싣는다.
- `compliance/builtin/no_short.py`·`single_name_cap.py`, `extension/scaffold.py`의 템플릿,
  `agent/skills/make-compliance/`(SKILL.md·`references/observe.md`), showcase `show_003` —
  `account.` → `call.account.`.
- `extension/conformance.py`는 손대지 않았다: arity는 계약에서 읽으므로 `observe(self, call, account)`를
  쓴 옛 규칙은 등록 시 `component.signature_invalid`로 거부된다(`tests/cli/test_register.py`,
  `tests/extension/test_conformance.py`가 그것을 고정한다; 메시지가 "3 positional" → "2 positional").
- `docs/releases/0.11.0.md` §7 — breaking 항목과 마이그레이션 한 줄.
- **`tests/boundaries/test_a_role_has_one_call.py`** — 참고 브랜치에서 이식. 네 역할이 각각 추상
  콜백 하나를 갖고, 그 콜백은 `self`와 Call 하나만 받으며, 반환을 선언한다. `ComplianceCall`이
  배선표의 `COMMITTED_ACCOUNT`를 실제로 든다는 것도 고정한다.

테스트 열넷의 `def observe(self, call, account)`는 스크립트로 바꿨다 — 시그니처와 그 메서드 몸통
안의 `account`만(들여쓰기로 경계). 기록 `203`이 경고한 "클래스 경계를 모르는 치환"을 피한 것이고,
그래도 산문 두 곳(`An account with no NAV` → `An call.account`)이 걸려 손으로 되돌렸다.

## 검증

```text
uv run ruff check src/                 All checks passed
uv run pyright                          0 errors
uv run pytest tests/ -q                 1659 passed + agent 4 (skill 파일 LF·_shipped.json 재기록 뒤 114/114); 최종은 마감 test_all
showcase digest                         81/81
```
