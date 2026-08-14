"""account — commit authority. **닫힌 층.**

vqapr에는 서로 바꾸어 쓸 수 없는 두 runtime authority가 있고 이것이 그중 하나다.
committed fill과 mark가 만든 cash · position · cost · NAV와 그 이력.

나머지는 authority가 아니다. intended portfolio, requested order, validation finding,
monitoring finding, evidence는 **의도와 영수증**이다(PRD §2.4).

**Account는 자기가 어떤 profile에 쓰이는지 모른다.** "academic Account"나 "KRX Account" 같은
것은 없다. profile 차이는 전부 Exchange에 있고 Account는 상태 전이의 유효성만 본다.

사용자가 저작할 수 없다. 열면 intended != committed가 사용자 코드에 달린다.
"""
