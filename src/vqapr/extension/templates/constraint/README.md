# `constraint` template

Constraint — 무엇을 지켜야 하는가.

채워야 할 것: `requirements()` · `project()` · `measure()`.

통과 조건: 요구한 data가 없으면 결과를 만들기 전에 실패한다 · 누락을 0으로 추정하지 않는다 · 같은 선언이 intended weights와 actual holdings 둘 다에 적용된다.

## 이 디렉터리에 있어야 하는 파일

- 구현 파일 — 채워야 할 계약. TODO가 표시되어 있다
- 선언 파일 (`.yaml`) — `ComponentRef`가 될 선언
- conformance 테스트 — `vqapr.testing.conformance`를 호출한다. **처음에는 실패한다**
- 이 README — 각 TODO가 무엇을 요구하는지

## 흐름

```bash
vqapr new constraint ./my_component
cd my_component && pytest        # conformance가 통과할 때까지
vqapr check .                    # 같은 검사, 기계 판독 결과
vqapr register . --project ../research
```
