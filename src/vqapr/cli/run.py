"""`vqapr run ...` / `vqapr materialize ...` — 두 진입점.

구현할 것
    run          RunDefinition을 동결하고 preflight 후 SimulationFlow 실행
    materialize  DataModel을 기간에 대해 계산해 dataset으로 publish

왜 두 명령인가
    진입점이 둘이기 때문이다(architecture §4.4). 한 번 materialize한 결과를 여러 run이
    공유한다.

동결 후 project 변경은 그 run에 영향을 주지 않는다
    `UC-CONFIG-001`.

preflight 실패는 FAILED_WITHOUT_MUTATION으로 끝난다
    아무것도 commit되지 않는다.
"""
