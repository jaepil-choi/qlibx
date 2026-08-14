"""DataModel 진입점 — 그리고 available_at을 붙인다.

구현할 것
    materialize(model, start, end, ...)
        기간 안의 trigger를 순회하며
            첫 trigger 전에 initial committed Model state 복원
            PIT ModelWindow 구성 (`views.py`)
            DataModel.compute(context)
            Rows와 새 candidate Model state 검증
            다음 trigger로 진행
        완료된 dataset과 state snapshot들을 함께 publish

**available_at은 package가 붙인다.**

    available_at = max(trigger 시각, max(창 안 available_at))

    생산자가 주장하지 않는다 — 실제로 읽은 것에서 나오므로 위조할 수 없다. 자기 행 시각보다
    먼저 알 수는 없다: 재무만 읽는 6월말 계산이 3월 공시를 썼더라도 available_at은 6월말이다.
    그렇지 않으면 "6월말 분류"가 5월에 보인다(architecture §4.5).

    창을 크게 잡으면 스스로 쓸모없어진다 — 전체 기간을 한 번에 읽으면 모든 출력 행이 마지막
    날부터 유효해진다. 그래서 "전체 패널을 보지 마세요"라고 적을 필요가 없다.

왜 models/가 아니라 flow인가
    compute는 순수 계약이고 materialize는 state를 commit하고 dataset을 publish하는 **부작용**이다.
    그리고 run()이 이미 Model state를 commit하므로, 다른 층에 두면 state store 접근이 두 층에서
    일어난다(architecture §4.4, §10).

run()과 다른 진입점이다
    한 번 materialize한 결과를 여러 run이 공유한다.

warm-up이 없다
    데이터가 부족하면 그 시점 행을 만들지 않으면 된다.
"""
