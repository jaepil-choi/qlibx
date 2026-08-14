"""어디에 설치하는가 — normative product contract.

구현할 것
    target별 skill directory와 required entrypoint (PRD §11.2)
        Codex             `.agents/skills/vqapr/`        + `SKILL.md`
        Claude Code       `.claude/skills/vqapr-skill/`  + `SKILL.md`
        explicit custom   `<user-selected-output>/vqapr/` + `SKILL.md`

**이 path들은 normative다.** 일반적인 directory convention이나 architecture candidate가 아니라
선택된 target이 skill을 발견하기 위해 사용하는 제품 계약이다.

custom target root는 user가 명시적으로 선택해야 하며 **package가 임의의 output location을
추측하지 않는다.**

각 skill directory 안의 `references/` `scripts/` `examples/` 같은 보조 resource는 해당 target
protocol과 generated manifest가 허용하는 범위에서 둘 수 있다.
"""
