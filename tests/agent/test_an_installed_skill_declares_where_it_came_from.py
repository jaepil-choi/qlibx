"""The five states an installed skill file can be in, and which of them may be overwritten.

PRD §11.3. The judgment is content-only -- no manifest, no filesystem -- so all five states are
reachable here without installing anything. That is the point of `judge` being pure: the
integration tests in `tests/cli/` cannot reach `outdated` at all, because doing so needs a release
history that the working tree does not have until a release writes one.

The distinction this file exists to protect is `outdated` against `modified`. Collapsing them was
the old behaviour: a single `current: false` told every reader to run `skill install`, and a reader
who followed it lost their own edits. One of those two states is safe to overwrite and the other
is not, and only the release history can tell them apart.
"""

from __future__ import annotations

import pytest

from vqapr.agent.skillset import (
    WRITABLE_WITHOUT_FORCE,
    FileState,
    judge,
    sha256,
    shipped_skills,
)

NOW = b"what this package ships today"
BEFORE = b"what an earlier release shipped"
MINE = b"what the user typed"

SHIPPED = {"SKILL.md": NOW, "references/pit.md": b"a reference"}
RELEASED = {"a-skill/SKILL.md": {sha256(BEFORE): "0.6.0"}}


def _states(installed: dict[str, bytes]) -> dict[str, FileState]:
    verdict = judge("a-skill", installed, shipped=SHIPPED, released=RELEASED)
    return {f.path: f.state for f in verdict.files}


def test_the_same_bytes_are_current() -> None:
    assert _states({"SKILL.md": NOW})["SKILL.md"] is FileState.CURRENT


def test_bytes_from_an_earlier_release_are_outdated_and_say_which() -> None:
    """The release is carried as the table's value, so provenance costs no extra entry."""
    verdict = judge("a-skill", {"SKILL.md": BEFORE}, shipped=SHIPPED, released=RELEASED)
    file_verdict = next(f for f in verdict.files if f.path == "SKILL.md")
    assert file_verdict.state is FileState.OUTDATED
    assert file_verdict.released_in == "0.6.0"


def test_bytes_from_no_release_are_modified() -> None:
    assert _states({"SKILL.md": MINE})["SKILL.md"] is FileState.MODIFIED


def test_a_shipped_file_that_is_not_there_is_absent() -> None:
    assert _states({"SKILL.md": NOW})["references/pit.md"] is FileState.ABSENT


def test_a_path_we_never_shipped_is_not_ours() -> None:
    installed = {"SKILL.md": NOW, "notes.md": MINE}
    verdict = judge("a-skill", installed, shipped=SHIPPED, released=RELEASED)
    assert {f.path: f.state for f in verdict.files}["notes.md"] is FileState.UNKNOWN
    assert verdict.not_ours == ("notes.md",)


def test_only_modified_needs_asking() -> None:
    """The whole gate in one assertion.

    `UNKNOWN` is absent from the writable set for a different reason than `MODIFIED`: it is not a
    place we write at all, rather than a place we need permission for.
    """
    safe = {FileState.CURRENT, FileState.OUTDATED, FileState.ABSENT}
    assert safe == WRITABLE_WITHOUT_FORCE


def test_the_worst_file_speaks_for_the_skill() -> None:
    """A one-line edit must not lock the other files, but must still be what the reader hears."""
    verdict = judge(
        "a-skill",
        {"SKILL.md": NOW, "references/pit.md": MINE},
        shipped=SHIPPED,
        released=RELEASED,
    )
    assert verdict.state is FileState.MODIFIED
    assert verdict.needs_force == ("references/pit.md",)


def test_the_release_history_is_keyed_by_the_skills_own_path() -> None:
    """A hash known for one skill does not vouch for the same bytes under another skill.

    Two skills can legitimately ship an identical file -- the repeated "how to invoke the CLI"
    preamble is one (PRD §11.2 has each SKILL.md carry it rather than link sideways). Keying the
    table by `<skill>/<path>` keeps one skill's history from answering for another's.
    """
    assert _states({"SKILL.md": BEFORE})["SKILL.md"] is FileState.OUTDATED
    other = judge("another-skill", {"SKILL.md": BEFORE}, shipped=SHIPPED, released=RELEASED)
    assert other.files[0].state is FileState.MODIFIED


@pytest.mark.parametrize("name", sorted(shipped_skills()))
def test_every_shipped_skill_has_an_entrypoint(name: str) -> None:
    """PRD §11.2: the required entrypoint of a skill directory is its `SKILL.md`."""
    assert "SKILL.md" in shipped_skills()[name], f"{name} ships no SKILL.md"


def test_paths_are_posix_so_a_windows_build_and_a_unix_one_agree() -> None:
    """A backslash key would make the same file a different entry, and untouched installs
    would come back `modified` on the other platform."""
    for files in shipped_skills().values():
        assert not any("\\" in path for path in files), files
