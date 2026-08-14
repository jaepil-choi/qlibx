"""agent — agent 표면. **호출되지 않는다.**

**제약 하나가 이 층의 존재 이유를 지킨다.**

    `agent/`는 package의 deterministic 경로에서 호출되지 않고, 반대 방향도 없다.

PRD §2.6이 *"package의 deterministic behavior가 agent skill을 호출하거나 대화 상태를 소유하지
않는다"*고 못 박았다. 여기가 어딘가에서 import되는 순간 그 보장이 깨진다.

이 층은 **파일을 만들어내는 생산자**이고 진입은 CLI로만 일어난다.

왜 데이터 폴더가 아니라 층인가
    변경 이유가 독립적이다. Codex나 Claude Code의 skill 프로토콜이 바뀔 때 바뀌고, portfolio
    수학이 바뀔 때는 바뀌지 않는다.

역할 분담
    deterministic package   requirement 선언 -> validation -> structured failure / result
    bundled agent skill     candidate 구성 -> 설명 -> user interview -> project 변경 -> 재호출

    package error는 **가능한 resolution이나 user에게 물을 질문을 결정하지 않는다.**
"""
