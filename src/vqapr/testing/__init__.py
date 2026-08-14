"""testing — 내장과 확장을 구분할 분기점이 없다.

**왜 패키지 안에 있나**
    `UC-EXTENSION-002`는 사용자가 local StrategyModel을 작성·검증하기를 요구하고
    `UC-FACADE-001`은 그것을 **package source를 열지 않고** 하라고 요구한다. `decide()`를 한
    번이라도 돌리려면 `StrategyModelContext`와 calendar와 창이 필요하다.

    출하된 kit이 없으면 사용자는 내부를 import하는 수밖에 없고, **그것이 PRD §1.4가 "public
    product surface의 결함"이라고 부른 상황이다.**

    nautilus가 `test_kit/`을 패키지에 출하하는 것과 같은 이유다. qlib에는 이 층이 없어서
    사용자가 자기 전략을 검증하려면 `tests/`를 읽어야 한다.

**우리 테스트가 같은 것을 쓴다.**
    픽스처가 dogfooding되고, `tests/testing/`이 이 kit 자체를 검증한다.
"""
