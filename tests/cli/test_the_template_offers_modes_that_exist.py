"""The run-spec template offers account modes that actually exist.

`docs/issues/017`. `vqapr new run-spec` emitted `mode: LONG_ONLY` with the comment
`# LONG_ONLY or LONG_SHORT`, reading as a closed set of exactly two. The book was long/short, so
the author took the value the template offered. **`LONG_SHORT` does not exist and never did** --
the members are `LONG_ONLY` and `SIGNED` -- and the refusal that followed carried
`observed: KeyError: 'LONG_SHORT'`, an exception repr where the permitted set belonged.

`slowed` for a reporter who could go read the enum. `blocked` for a first-time user without it on
screen.
"""

from __future__ import annotations

from vqapr.account.account import AccountMode
from vqapr.cli.new import _ACCOUNT_MODES, _RUN_SPEC_TEMPLATE


def test_the_template_never_names_a_mode_that_does_not_exist() -> None:
    """The regression itself, stated as the property rather than as one banned spelling."""
    comment = next(
        line for line in _RUN_SPEC_TEMPLATE.splitlines() if line.strip().startswith("mode:")
    )

    offered = comment.split("#", 1)[1]
    real = {mode.name for mode in AccountMode}

    named = {word.strip() for word in offered.split(" or ")}
    unknown = named - real

    assert not unknown, (
        f"the template offers {unknown}, which {'is' if len(unknown) == 1 else 'are'} not "
        f"{'a member' if len(unknown) == 1 else 'members'} of AccountMode ({sorted(real)})"
    )


def test_the_template_offers_every_mode_there_is() -> None:
    """A closed-set comment that omits a member is the same defect pointed the other way.

    An author who needs a signed book and is shown only `LONG_ONLY` is no better off than one who
    is shown a value that does not exist.
    """
    comment = next(
        line for line in _RUN_SPEC_TEMPLATE.splitlines() if line.strip().startswith("mode:")
    )

    for mode in AccountMode:
        assert mode.name in comment, f"the template never offers {mode.name}"


def test_the_offered_list_is_derived_from_the_enum_not_restated() -> None:
    """Why this cannot drift again: the comment IS the enum, rendered.

    A hand-written list is a second definition of a closed set, and this issue is what that costs.
    """
    assert " or ".join(mode.name for mode in AccountMode) == _ACCOUNT_MODES
    assert _ACCOUNT_MODES in _RUN_SPEC_TEMPLATE


def test_the_template_spells_modes_the_way_the_parser_accepts_them() -> None:
    """`.name`, not `.value`.

    The spec is parsed by member name (`LONG_ONLY`); `.value` is the lowercase `long_only` a
    reader must not type into the file. Offering the wrong spelling would swap one unusable value
    for another.
    """
    for mode in AccountMode:
        assert mode.name in _ACCOUNT_MODES
        assert mode.value not in _ACCOUNT_MODES, (
            f"the template offers {mode.value!r}, which is the enum's value rather than the name "
            "the spec parser accepts"
        )
