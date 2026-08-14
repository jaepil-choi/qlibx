"""`vqapr register <dir> --project <path>` — 등록.

구현할 것
    `extension/registration.py`를 부른다
    load -> conformance -> fingerprint -> project config 기록

**fingerprint를 찍는 이 순간이 계약의 시작점이다.**
    이후 source가 바뀌면 compute 전에 drift로 거부된다(`UC-EXTENSION-002`).

성공하기 전까지 등록하지 않는다
    conformance 실패 시 project config는 바뀌지 않는다. partial registration을 만들지 않는다.
"""
