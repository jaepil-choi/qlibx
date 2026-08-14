"""frozen mini SessionCalendar.

구현할 것
    10세션 규모의 작은 KST calendar. open/close 시각 포함.
    휴장을 포함한 변형 — 월말이 휴장인 달(`LastSessionOfMonth` 검증용)

왜 작아야 하나
    창 경계와 trigger 발화 시점을 **손으로 셀 수 있어야** 테스트가 무엇을 주장하는지 읽힌다.
"""
