"""The skill describes the provenance the package actually has.

`docs/issues/023`, docs half only. The skill claimed:

    Registrations are immutable identities, not editable configuration rows. Re-registering changed
    content under the same id is refused because an old run may depend on the original declaration.

**That refusal was removed on purpose.** `docs/issues/009` argued the component fingerprint should
report rather than refuse, because editing a registered component is the ordinary development loop,
and `tests/flow/test_edit_loop.py` is the acceptance test it asked for. So the skill was describing
a gate the package had deliberately stopped having, and sending readers to invent a new component id
for every edit.

**What is NOT being built here.** 023 also proposes a `matches` / `differs` / `absent` statement in
`show run`, reporting whether the source at the registered path still hashes to the digest that run
recorded. That is the held product half (023p). It is undecided, so the narrowed text must state the
current state **without implying such a read-back exists** -- and it must never become a gate, which
009's "What not to do" forbids outright.
"""

from __future__ import annotations

from pathlib import Path

from vqapr.cli.main import main


def _installed(tmp_path: Path) -> str:
    (tmp_path / ".git").mkdir()
    main(["--project-root", str(tmp_path), "skill", "install"])
    return (tmp_path / ".agents/skills/vqapr/SKILL.md").read_text(encoding="utf-8")


def test_the_skill_no_longer_claims_re_registration_is_refused(tmp_path: Path) -> None:
    """The false sentence, gone."""
    collapsed = " ".join(_installed(tmp_path).split())

    assert "Re-registering changed content under the same id is refused" not in collapsed, (
        "the skill still promises the gate docs/issues/009 removed"
    )


def test_the_skill_names_the_edit_loop_that_actually_exists(tmp_path: Path) -> None:
    """Two commands, same id: what 009's acceptance test proves and the skill hid."""
    collapsed = " ".join(_installed(tmp_path).split())

    assert "--force` to replace it in place" in collapsed
    assert "The id stays" in collapsed or "id stays" in collapsed


def test_the_skill_calls_the_digest_a_receipt_and_not_a_check(tmp_path: Path) -> None:
    """`source_digest` records what ran; nothing re-checks it.

    Saying so is the honest description of today's behaviour, and it is what keeps a reader from
    assuming the digest is verified on their behalf.
    """
    collapsed = " ".join(_installed(tmp_path).split())

    assert "receipt rather than a gate" in collapsed
    assert "nothing re-checks it afterwards" in collapsed


def test_the_skill_does_not_imply_a_read_back_that_does_not_exist(tmp_path: Path) -> None:
    """023p is HELD, so the docs half must not describe it as though it shipped.

    A reader told the digest can be compared back against the file would look for a command that
    does not exist. If 023p is ever decided, this test is the place that has to change with it.
    """
    collapsed = " ".join(_installed(tmp_path).split())

    for absent in ("matches / differs / absent", "still matches the digest", "verify the digest"):
        assert absent not in collapsed, (
            f"the skill implies a digest read-back ({absent!r}) that is not built; 023p is held"
        )


def test_the_skill_still_refuses_two_declarations_under_one_id(tmp_path: Path) -> None:
    """009 explicitly kept this: one id must not silently mean two different declarations.

    Narrowing the immutability claim must not narrow it into nothing.
    """
    collapsed = " ".join(_installed(tmp_path).split())

    assert "one id means one declaration" in collapsed
    assert "give it its own id" in collapsed
