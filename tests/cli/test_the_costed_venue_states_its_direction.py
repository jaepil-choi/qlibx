"""The skill says the KRX profile is long-only, where a reader decides to use it.

`docs/issues/020`. `vqapr new exchange <id> --profile krx` is the realistic profile and the skill's
Costs section recommends it. `krx_listings` produces `ListingAccess.LONG_ONLY` rules, so

    --profile krx  +  initial_account.mode: SIGNED

is a pairing nothing refuses at scaffold time and that cannot hold a position. The scaffold's own
class docstring says it in passing -- *"long positions only"* -- but the skill's two cost sections,
which are where a reader goes to *decide* this, never mentioned direction at all. The reporter spent
about ten minutes re-reading them looking for the sentence that turned out not to be there.
"""

from __future__ import annotations

from pathlib import Path

from vqapr.cli.main import main
from vqapr.cli.new import _RUN_SPEC_TEMPLATE
from vqapr.public import ListingAccess, krx_listings


def _installed_skill(tmp_path: Path) -> str:
    (tmp_path / ".git").mkdir()
    main(["--project-root", str(tmp_path), "skill", "install"])
    return (tmp_path / ".agents/skills/vqapr/SKILL.md").read_text(encoding="utf-8")


def test_the_krx_profile_really_is_long_only() -> None:
    """The premise, checked against the source rather than taken from the issue.

    If this ever changes, the skill sentences below become false and must change with it.
    """
    rules = krx_listings(["005930", "069500"])
    for rule in rules.values():
        assert rule.access is ListingAccess.LONG_ONLY


def test_the_installed_skill_states_the_direction_where_a_reader_decides(
    tmp_path: Path,
) -> None:
    """The merge condition, on the text an agent actually reads."""
    text = _installed_skill(tmp_path)

    assert "long-only" in text, "the skill still never says the krx profile is long-only"
    assert "ListingAccess" in text, (
        "the skill does not name ListingAccess, so a reader cannot find the knob that changes it"
    )
    assert "SIGNED" in text, "the skill does not say what a long/short book needs instead"


def test_the_skill_names_the_pairing_that_cannot_work(tmp_path: Path) -> None:
    """Naming the combination is the part that saves the ten minutes.

    A reader who knows the venue is long-only and the account is SIGNED still has to notice that
    the two must agree; the skill now says so outright rather than leaving it to be inferred.
    """
    text = _installed_skill(tmp_path)

    assert "initial_account.mode: SIGNED" in text or "mode: SIGNED" in text
    # Line-wrap-insensitive: the sentence spans a newline in the source.
    collapsed = " ".join(text.split())
    assert "nothing refuses at scaffold time" in collapsed, (
        "the skill does not warn that this pairing is accepted at scaffold time and fails later"
    )
    assert "cannot hold a position" in collapsed


def test_the_run_spec_template_says_the_venue_must_agree() -> None:
    """The second place a reader meets `mode:`, and the one they meet first."""
    assert "The venue must permit the direction too" in _RUN_SPEC_TEMPLATE
    assert "krx" in _RUN_SPEC_TEMPLATE
    assert "access=SIGNED" in _RUN_SPEC_TEMPLATE


def test_the_template_still_derives_its_mode_list() -> None:
    """This branch edits the same line `fix/017-template-account-mode` fixed.

    That branch replaced a hand-written `LONG_ONLY or LONG_SHORT` with a list derived from the
    enum. Extending the comment must not quietly restore a hand-written one.
    """
    from vqapr.account.account import AccountMode
    from vqapr.cli.new import _ACCOUNT_MODES

    assert " or ".join(mode.name for mode in AccountMode) == _ACCOUNT_MODES
    assert _ACCOUNT_MODES in _RUN_SPEC_TEMPLATE
    assert "LONG_SHORT" not in _RUN_SPEC_TEMPLATE
