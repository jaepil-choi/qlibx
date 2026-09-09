"""A mistyped closed-set value is refused with the permitted set, not an exception repr.

`docs/issues/archive/017`, message half. `AccountMode[str(...).upper()]` raised a bare `KeyError`, which
reached the envelope as:

    "observed": "KeyError: 'LONG_SHORT'"

The reader is told their value was rejected and left to discover the legal ones themselves -- for
this journey, by reading the enum in installed source. A closed set is the one case where a refusal
can always be complete: the alternatives are known, finite, and cheap to print.

Since record `139` a run is a registered declaration, so the account mode is judged where every
other closed set in a declaration is judged -- `declarations._enum`, the helper `register` learned
this on expensively (`fill.selector`: six consecutive guesses on price words, because the field
name argues for a vocabulary the members do not use).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import pytest

from vqapr.account.account import AccountMode
from vqapr.project.registration import _enum, apply
from vqapr.domain.errors import VqaprError
from vqapr.project.store import Workspace


class _Selector(StrEnum):
    """A second closed set, so the helper is proven general rather than fitted to one field."""

    SAME_DAY = "same_day"
    NEXT_ELIGIBLE = "next_eligible"


def _failure(error: VqaprError) -> dict:
    return error.as_dict()["failures"][0]


def _register_run_with_mode(root: Path, mode: str) -> dict:
    Workspace.create(root)
    document = {
        "runs": {
            "r": {
                "instruments": ["A"],
                "start": "2024-01-02T00:00:00+09:00",
                "end": "2024-01-03T00:00:00+09:00",
                "sessions_from": "prices",
                "timezone": "Asia/Seoul",
                "at": "15:29",
                "exchange": "venue",
                "execution": {
                    "dataset": "venue-daily",
                    "fill": {"at": "15:30", "timezone": "Asia/Seoul", "trade_price": "close"},
                },
                "initial_account": {"cash": "1000", "mode": mode, "positions": {}},
                "writes": "r-weights",
                "strategies": {"alpha": {}},
            }
        }
    }
    with pytest.raises(VqaprError) as raised:
        apply(document, root, base=root, declaration=root / "runs.yaml")
    return _failure(raised.value)


def test_the_account_mode_refusal_names_the_permitted_set(tmp_path: Path) -> None:
    """The journey's own value, and the exact shape it produced."""
    failure = _register_run_with_mode(tmp_path, "LONG_SHORT")

    assert failure["code"] == "declaration.value_not_permitted"
    assert failure["requirement"] == "runs.r.initial_account.mode must be one of: long_only, signed"
    assert failure["examples"] == ["long_only", "signed"]
    assert failure["source"]["key_path"] == "runs.r.initial_account.mode"


def test_no_exception_repr_reaches_observed(tmp_path: Path) -> None:
    """The defect itself: `observed` carried `KeyError: 'LONG_SHORT'`.

    An exception type is a fact about this package's implementation. What belongs in `observed` is
    what the reader wrote.
    """
    observed = _register_run_with_mode(tmp_path, "LONG_SHORT")["observed"]

    assert "KeyError" not in observed, "the refusal still reports an exception repr"
    assert "LONG_SHORT" in observed, "the refusal no longer says what was actually written"


def test_the_suggestion_names_the_nearest_member(tmp_path: Path) -> None:
    """A near-miss hint: a one-character typo is invisible to whoever typed it."""
    fix = _register_run_with_mode(tmp_path, "LONG_SHORT")["fix"]

    assert "'long_only'" in fix, f"the hint does not name the nearest member: {fix}"


@pytest.mark.parametrize(
    ("enum", "written", "key_path", "expected"),
    [
        (AccountMode, "LONG_SHORT", "initial_account.mode", "long_only, signed"),
        (_Selector, "CLOSE", "fill.selector", "same_day, next_eligible"),
    ],
)
def test_the_refusal_is_the_same_shape_on_two_different_keys(
    enum: type[StrEnum], written: str, key_path: str, expected: str
) -> None:
    """Verified on two keys, because a fix fitted to one field is not a fix to the class.

    The second case is the `fill.selector` vocabulary trap by name: `CLOSE` is a price word, and
    the members are scheduling words, so no number of guesses gets there without the list.
    """
    with pytest.raises(VqaprError) as raised:
        _enum(enum, written, name=key_path)

    failure = _failure(raised.value)

    assert failure["requirement"] == f"{key_path} must be one of: {expected}"
    assert failure["observed"] == written
    assert failure["source"]["key_path"] == key_path
    assert "KeyError" not in failure["observed"]
    assert failure["examples"] == expected.split(", ")


def test_a_value_with_no_near_miss_still_gets_the_whole_set() -> None:
    """The fallback path: when nothing is close, the advice is the list itself."""
    with pytest.raises(VqaprError) as raised:
        _enum(AccountMode, "zzzzzzzz", name="initial_account.mode")

    fix = _failure(raised.value)["fix"]

    assert "long_only" in fix and "signed" in fix


def test_a_permitted_value_is_still_accepted_in_either_case(tmp_path: Path) -> None:
    """The other half: the gate must let legal values through, in either spelling.

    The refusal that follows is about the unregistered ids the run names, not about the mode.
    """
    for spelling in ("SIGNED", "signed"):
        failure = _register_run_with_mode(tmp_path / spelling, spelling)
        assert failure["code"] == "run.reference_invalid", failure
    assert _enum(AccountMode, "signed", name="k") is AccountMode.SIGNED
