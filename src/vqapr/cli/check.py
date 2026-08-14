"""`vqapr check <dir|ref>` — conformance 검사.

구현할 것
    `testing/conformance/runner.py`를 부른다
    **기계 판독 결과**를 낸다 — agent가 읽는 쪽

`pytest`와 같은 코드를 부른다
    사용자는 pytest로 반복하고 agent는 이 출력을 읽는다. 두 경로가 갈리면 "로컬에선 되는데
    등록이 안 된다"가 생긴다.
"""
