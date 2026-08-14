"""submit — 사용자가 만든 것을 등록한다.

구현할 것
    register(ref, *, project) -> RegistrationResult
        1. loading.load(ref)            import, bounded error
        2. conformance.run(ref, obj)    **`testing/conformance/`와 같은 코드**
        3. fingerprint.of(ref)          이후 drift 판정의 기준점
        4. project config에 기록

**검증은 conformance 하나뿐이다.**
    별도의 계약 검사 모듈을 두지 않는다. 검사가 두 곳에 있으면 반드시 어긋나고, 어긋나면
    *"pytest는 통과하는데 register가 거부한다"*가 나온다.

    `pytest` · `vqapr check` · `vqapr register`가 전부 같은 함수를 부른다. 그래서 내장과 확장을
    차별할 **분기점이 존재하지 않는다.**

성공하기 전까지 등록하지 않는다
    validation을 통과한 뒤에만 reusable extension이 된다(`UC-EXTENSION-001`).
"""
