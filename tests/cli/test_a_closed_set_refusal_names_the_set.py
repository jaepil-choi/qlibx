"""A mistyped closed-set value is refused with the permitted set, not an exception repr.

`docs/issues/017`, message half. `AccountMode[str(...).upper()]` raised a bare `KeyError`, which
reached the envelope as:

    "observed": "KeyError: 'LONG_SHORT'"

The reader is told their value was rejected and left to discover the legal ones themselves -- for
this journey, by reading the enum in installed source. A closed set is the one case where a refusal
can always be complete: the alternatives are known, finite, and cheap to print.

`register.py` already learned this expensively, on `fill.selector`: a reader spent six consecutive
guesses on price words because the field name argues for a vocabulary the members do not use. This
is the same remedy on the `run` side.
"""

from __future__ import annotations

from enum import StrEnum

import pytest

from vqapr.account.account import AccountMode
from vqapr.cli.inputs import InputError
from vqapr.cli.run import _account, _closed_set_member


class _Selector(StrEnum):
    """A second closed set, so the helper is proven general rather than fitted to one field."""

    SAME_DAY = "same_day"
    NEXT_ELIGIBLE = "next_eligible"


def _failure(error: InputError) -> dict:
    return error.as_dict()["failures"][0]


def test_the_account_mode_refusal_names_the_permitted_set() -> None:
    """The journey's own value, and the exact shape it produced."""
    with pytest.raises(InputError) as raised:
        _account({"initial_account": {"cash": "1000", "mode": "LONG_SHORT", "positions": {}}})

    failure = _failure(raised.value)

    assert failure["requirement"] == "initial_account.mode must be one of: LONG_ONLY, SIGNED"
    assert failure["examples"] == ["LONG_ONLY", "SIGNED"]
    assert failure["source"]["key_path"] == "initial_account.mode"


def test_no_exception_repr_reaches_observed() -> None:
    """The defect itself: `observed` carried `KeyError: 'LONG_SHORT'`.

    An exception type is a fact about this package's implementation. What belongs in `observed` is
    what the reader wrote.
    """
    with pytest.raises(InputError) as raised:
        _account({"initial_account": {"cash": "1000", "mode": "LONG_SHORT", "positions": {}}})

    observed = _failure(raised.value)["observed"]

    assert "KeyError" not in observed, "the refusal still reports an exception repr"
    assert "LONG_SHORT" in observed, "the refusal no longer says what was actually written"


def test_the_suggestion_is_spelled_the_way_the_spec_parser_accepts() -> None:
    """A near-miss hint in the wrong case swaps one unusable value for another.

    The run spec is parsed by member NAME, so the suggestion must be `LONG_ONLY` and not the
    enum's lowercase `long_only` value. `register`'s equivalent helper lowercases deliberately,
    which is correct for a declaration and wrong here -- so it is not reused.
    """
    with pytest.raises(InputError) as raised:
        _account({"initial_account": {"cash": "1000", "mode": "LONG_SHORT", "positions": {}}})

    fix = _failure(raised.value)["fix"]

    assert "'LONG_ONLY'" in fix, f"the hint is not in the spelling the parser accepts: {fix}"
    assert "'long_only'" not in fix


@pytest.mark.parametrize(
    ("enum", "written", "key_path", "expected"),
    [
        (AccountMode, "LONG_SHORT", "initial_account.mode", "LONG_ONLY, SIGNED"),
        (_Selector, "CLOSE", "fill.selector", "SAME_DAY, NEXT_ELIGIBLE"),
    ],
)
def test_the_refusal_is_the_same_shape_on_two_different_keys(
    enum: type[StrEnum], written: str, key_path: str, expected: str
) -> None:
    """Verified on two keys, because a fix fitted to one field is not a fix to the class.

    The second case is the `fill.selector` vocabulary trap by name: `CLOSE` is a price word, and
    the members are scheduling words, so no number of guesses gets there without the list.
    """
    with pytest.raises(InputError) as raised:
        _closed_set_member(enum, written, key_path=key_path)

    failure = _failure(raised.value)

    assert failure["requirement"] == f"{key_path} must be one of: {expected}"
    assert failure["observed"] == f"{key_path}={written!r}"
    assert failure["source"]["key_path"] == key_path
    assert "KeyError" not in failure["observed"]
    assert failure["examples"] == expected.split(", ")


def test_a_value_with_no_near_miss_still_gets_the_whole_set() -> None:
    """The fallback path: when nothing is close, the advice is the list itself."""
    with pytest.raises(InputError) as raised:
        _closed_set_member(AccountMode, "zzzzzzzz", key_path="initial_account.mode")

    fix = _failure(raised.value)["fix"]

    assert "LONG_ONLY" in fix and "SIGNED" in fix


def test_a_permitted_value_is_still_accepted() -> None:
    """The other half: the gate must let legal values through, in either case."""
    assert _closed_set_member(AccountMode, "SIGNED", key_path="k") is AccountMode.SIGNED
    assert _closed_set_member(AccountMode, "signed", key_path="k") is AccountMode.SIGNED
