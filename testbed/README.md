# qlibx conversation testbed

이 폴더는 qlibx 저장소의 구현을 직접 보지 않고, 설치된 패키지의 public surface만 사용해 사용자와
Codex가 대화형으로 기능을 검증하는 독립 consumer project다.

준비가 끝난 뒤에는 저장소 루트에서 다음과 같이 요청하면 된다.

```text
testbed에 모의 주가 데이터를 만들어줘.
testbed의 데이터를 qlibx에 등록해줘.
등록된 dataset을 조회하고 point-in-time 규칙을 검증해줘.
```

Testbed 작업은 생성된 `.agents/skills/qlibx/SKILL.md`에서 시작하며, `../src` 같은 qlibx 내부 구현은
읽거나 수정하지 않는다. 공개 기능이 부족하면 내부를 우회하지 않고 제품상 누락으로 기록한다.
