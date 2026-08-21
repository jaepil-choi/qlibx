# `exchange` template

Exchange — 어느 venue에서 어떤 규칙으로 체결되는가.

채워야 할 것: 체결 테이블 선언 · `TradeRule` (수량 단위·access·비용) · `FillConvention` · `execute()`.

통과 조건: `is_tradable=true`면 가격이 유한하고 양수다 · 세 zero-dealt 사유를 구분한다 · batch-atomic 전제조건을 지킨다 · 선언한 가격 컬럼을 대체하지 않는다.

## 이 디렉터리에 있어야 하는 파일

- 구현 파일 — 채워야 할 계약. TODO가 표시되어 있다
- 선언 파일 (`.yaml`) — `ComponentRef`가 될 선언
- conformance 테스트 — `vqapr.testing.conformance`를 호출한다. **처음에는 실패한다**
- 이 README — 각 TODO가 무엇을 요구하는지

## 흐름

```bash
vqapr new exchange ./my_component
cd my_component && pytest        # conformance가 통과할 때까지
vqapr check .                    # 같은 검사, 기계 판독 결과
vqapr register . --project ../research
```
