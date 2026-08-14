# `datamodel` template

DataModel — 값을 만든다. `compute(ctx) -> Rows`.

채워야 할 것: `trigger()` · `requirements()` · `compute()`.

통과 조건: 창 밖을 읽지 않는다 · `available_at`을 주장하지 않는다 · Model state를 쓰면 순차 생성 표시가 출력에 남는다.

## 이 디렉터리에 있어야 하는 파일

- 구현 파일 — 채워야 할 계약. TODO가 표시되어 있다
- 선언 파일 (`.yaml`) — `ComponentRef`가 될 선언
- conformance 테스트 — `vqapr.testing.conformance`를 호출한다. **처음에는 실패한다**
- 이 README — 각 TODO가 무엇을 요구하는지

## 흐름

```bash
vqapr new datamodel ./my_component
cd my_component && pytest        # conformance가 통과할 때까지
vqapr check .                    # 같은 검사, 기계 판독 결과
vqapr register . --project ../research
```
