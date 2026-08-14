"""transforms — 값을 값으로. 순수 leaf.

architecture §5.2의 3단 중 **1단**을 담당한다.

    transforms/   research values (정리된 신호)
    portfolio/    weights -> PortfolioIntent

leaf 규칙
    `domain` 외에는 import하지 않는다. 필요한 panel은 **전부 인자로 받는다.**
    여기서 창을 직접 읽으면 그 data가 StrategyModel의 declared requirement를 거치지 않아
    lineage에 남지 않는다(`UC-BUILTIN-001`).

    순수성은 도구가 아니라 **인자 목록**이 지킨다. 받지 않는 것을 쓰려면 import를 새로 써야
    하고, 그 import는 리뷰에서 눈에 띈다.

왜 이 package가 필요한가
    PRD §2.7이 signal transform을 built-in으로 약속했고, `UC-EXTENSION-001`은 "built-in 예시를
    참고해 agent가 project-local transform을 작성한다"고 한다. 참고할 built-in이 없으면 그
    use case가 성립하지 않는다.
"""
