"""Model state 포트 — committed / working.

구현할 것
    ModelStateStore   port. memory 스냅샷과 payload를 저장하고 ModelStateRef를 발행한다
    commit / load     Model invocation 성공 시 스냅샷, 시작 시 복원
    working checkpoint  context.checkpoint()가 요청하는 staging 저장

왜 flow인가
    `save_payload()`를 부르는 것이 invocation 경계이고 그것이 flow다. 저장은 경제 규칙이 아니라
    배관이라 "flow는 경제 규칙을 소유하지 않는다"와 부딪히지 않는다(architecture §5.1.1).

왜 evidence가 아닌가
    state는 영수증이 아니라 **authority**다. evidence에 두면 그 구분이 흐려지고, 기록을 지우면
    state가 사라지는 것처럼 보인다.

Model은 이것을 import하지 않는다
    `save_payload(target)`이 받는 것은 열려 있는 대상일 뿐이다. Model이 store를 알면 state를
    자기가 commit할 수 있게 되어 working/committed 경계가 무너진다.

working checkpoint의 복원 조건
    Model implementation, configuration, dataset binding/cutoff, training window, seed policy,
    operation/subperiod identity가 **모두 같을 때만** 복원한다. 하나라도 다르면 같은 계산의
    재시도로 취급하지 않는다.

    working checkpoint는 inference나 downstream input으로 resolve되지 않는다. 새 계산이 완료되기
    전에는 이전 committed state가 유지된다.

`UC-STATE-001` `UC-STATE-002` `UC-MODEL-003`
"""
