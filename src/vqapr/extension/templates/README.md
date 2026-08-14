# extension templates

`vqapr new <kind> <dir>`이 여기서 파일을 복사한다. kind는 넷이다.

    datamodel · strategy_model · exchange · constraint

각 템플릿 디렉터리가 담아야 하는 것 — 네 파일

| 파일 | 역할 |
|---|---|
| 구현 파일 (`.py`) | 채워야 할 계약. TODO가 표시되어 있고 그 자리를 채우면 통과한다 |
| 선언 (`.yaml`) | `ComponentRef`가 될 선언. trigger, requirements 등 |
| conformance 테스트 (`test_*.py`) | `vqapr.testing.conformance`를 호출한다. **처음에는 실패한다** |
| `README.md` | 각 TODO가 무엇을 요구하는지와 통과 조건 |

## 원칙

- **템플릿은 내장과 같은 public 계약만 쓴다.** 내부 접근을 쓰면 사용자가 그것을 따라 할 수
  없고, 그 순간 템플릿은 예제가 아니라 거짓말이 된다.
- 테스트가 처음에 실패하는 것이 의도다. 통과 조건이 실행 가능한 형태로 전달된다.
- `pytest`와 `vqapr check`가 같은 conformance 코드를 부른다. 갈리면 "로컬에선 되는데 등록이
  안 된다"가 생긴다.
