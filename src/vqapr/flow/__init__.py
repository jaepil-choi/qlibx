"""flow — 조립·배달·동결. **경제 규칙을 소유하지 않는다.** 닫힌 층.

책임
    run 동결과 preflight · schedule 조립 · 이벤트 dispatch · requirement resolution과 View 생성
    · Model 호출과 intent 발행 · plan_orders/Exchange 호출 · commit · Model state 스냅샷 ·
    evidence · finalize

**Academic Flow와 KRX Flow를 따로 만들지 않는다.**
    Exchange, AccountMode, calendar, policy를 주입한다. flow가 경제 규칙을 가지면 profile마다
    flow가 갈리고 "같은 lifecycle에 다른 정책"이 거짓이 된다(architecture §2.5, §8.1).

각 단계의 경제 규칙은 해당 package에 있다
    decision -> models/   execution -> orders/ + exchange/   commit -> account/
    valuation -> valuation/   monitoring -> constraints/

    그래서 이 package에 monitoring.py가 없다. dispatch만 `simulation.py`에 있다.
"""
