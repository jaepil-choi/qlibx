"""Account — 상태를 쓰는 유일한 객체.

구현할 것
    AccountMode   LONG_ONLY(적용 후 어떤 position도 < 0이면 실패) · SIGNED
    Account
        snapshot()                          -> AccountSnapshot
        commit(fills, *, expected_version)  -> AccountSnapshot
        mark(marks, *, expected_version)    -> AccountSnapshot
        history(query)                      -> AccountHistory

    변경 경로는 commit과 mark **둘뿐이다.**

왜 AccountMode가 여기 있고 별도 파일이 아닌가
    소비자가 사실상 Account 하나이고 **하는 일이 하나뿐**이다 — 음수 position 유효성. fractional,
    lot, rounding, 가격, 비용, 체결 시점은 전부 아니다(architecture §7.2). 타입 하나짜리 파일은
    소비자가 하나면 합친다.

    run 시작 시 동결되며 중간 변경 불가.

지켜야 할 것
    - expected_version으로 optimistic concurrency. 불일치면 mutation 없이 실패.
    - validation 실패 시 **하나도 바꾸지 않는다**(all-or-nothing).
    - commit 후 cash가 음수면 mutation 없이 실패. **모든 mode, 모든 profile에서 동일하다.**

왜 cash >= 0이 mode가 아니라 공통 불변식인가
    차입을 허용하면서 차입 비용·유지증거금·강제청산을 모델링하지 않으면 그 mode는 **공짜 돈
    버튼**이다. 레버리지를 올릴수록 수익이 선형으로 커지는데 대가가 없다.

    **gross를 키우는 것과 차입은 다르다.** NAV 100에서 long 2.0 / short 1.0은 공매도 대금이
    매수를 조달하므로 cash가 정확히 0이고 차입이 없다. cash가 음수가 되는 것만 차입이다.

이중 방어
    Exchange가 venue 규칙에 맞는 Fill만 만들고, Account는 그걸 믿지 않고 자기 mode와 회계
    불변식으로 다시 검증한다. **Exchange는 교체 가능한 주입물이고, authority가 주입물을
    신뢰하면 authority가 아니다.**

cash는 이자를 벌지 않는 numeraire다
    유휴자본에 수익을 주고 싶으면 derived unit price로 등록한 자산을 **포지션으로** 보유한다.
    조용한 기본값보다 선언된 포지션이 낫다 — 무엇을 얼마에 들었는지 lineage에 남는다.

`UC-CLOSED-LOOP-001` `UC-ACADEMIC-001` `UC-SCALE-001`
"""
