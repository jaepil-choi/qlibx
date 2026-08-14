"""`vqapr new <kind> <dir>` — 확장점 템플릿을 깐다.

구현할 것
    kind는 넷: datamodel · strategy_model · exchange · constraint
    `extension/scaffold.py`를 부른다
    preview 후 적용하며 기존 파일을 확인 없이 덮지 않는다

설치되는 것
    구현 파일 + yaml + **자기 conformance 테스트** + README.
    그 테스트는 **처음에 실패한다.** 통과 조건이 실행 가능한 형태로 전달된다.
"""
