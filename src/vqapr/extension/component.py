"""무엇이 등록되는가.

구현할 것
    ComponentKind   datamodel · strategy · exchange · constraint
    ComponentRef    path + config + fingerprint. **frozen**

왜 registry가 아니라 frozen 값인가
    registry는 상태를 갖고, 그러면 "언제 등록됐나"가 run identity 밖으로 샌다. PRD §12.1은
    frozen input만으로 실행과 재현이 가능해야 한다고 요구하며, ref는 frozen input에 그대로
    실린다(`RunDefinition`).

    nautilus의 ImportableConfig가 같은 모양이다 — class path + config를 담은 frozen 값을
    assembly 시점에 푼다. qlib의 InstDictConf는 str|dict|object|Path를 다 받는데(피클 경로까지),
    **그 느슨함 때문에 qlib은 extension drift를 감지할 수 없다.**

왜 fingerprint가 값에 포함되나
    등록 시점의 source 상태가 ref에 박혀 있어야 이후 변경을 drift로 판정할 수 있다
    (`UC-EXTENSION-002`).
"""
