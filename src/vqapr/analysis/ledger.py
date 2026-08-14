"""intended / requested / dealt / committed / marked — 나란히.

구현할 것
    다섯 단계를 같은 축(시점 x 종목)에 놓은 대조표
    각 단계 사이의 차이와 그 사유(rounding, clipping, rejection, missing data)

왜 이것이 별도 파일인가
    PRD §9.4가 report의 최소 요구로 이 다섯 구분을 지목한다. 그리고 architecture §2.4의
    `intended != requested != dealt != committed`가 **사람이 볼 수 있는 형태로** 나타나는
    유일한 자리다.

intended target을 actual holding처럼 섞지 않는다
    `UC-MONITOR-001`이 명시적으로 금지한다.

profile과 realism limitation도 함께 보인다
    선택한 profile, state-transition validity, 미모델링 항목이 같은 표에 있어야 숫자를 어떻게
    읽어야 하는지 알 수 있다.

`UC-REPORT-001`
"""
