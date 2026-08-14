"""이식 가능한 typed artifact.

구현할 것
    artifact 봉투 (schema id, version, semantic role, producer, lineage)
    직렬화 / 역직렬화
    **경계에서의 validation** — schema, required field, type, version, cross-field invariant

핵심 요구
    downstream consumer는 producer가 vqapr built-in인지, local Python module인지, 외부
    process인지 몰라도 schema·semantics·compatibility·lineage를 검사할 수 있어야 한다.

    따라서 serialized data를 읽을 때 raw dict로 넘기지 않고 **semantic role에 맞는 typed
    object를 생성**한다. invalid serialized state가 partially constructed object로 runtime에
    들어가서는 안 된다(PRD §2.5).

pickle-only 결과를 portable public artifact라고 주장하지 않는다
    PRD §12.5 금지 항목.

`UC-ARTIFACT-001` `UC-ARTIFACT-002`
"""
