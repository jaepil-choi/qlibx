"""The scaffold is the authoring contract's proof, so its shape is pinned rather than described.

Every number here is a spec acceptance criterion, and each one was failing before this step: the
emitted strategy was 111 lines and made the author hand-mint a `uuid5`, assemble `source_refs` from
the window's accesses, and read `context.account.version` -- three pieces of framework bookkeeping
that have exactly one correct value and no bearing on the signal being expressed.

The point is not brevity for its own sake. A 40-line ceiling is enforceable evidence that the
ceremony is gone, because ceremony is what made the file long.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from vqapr.authoring import Rebalance
from vqapr.extension.component import ComponentKind
from vqapr.extension.scaffold import render

BANNED = ("uuid5", "source_refs", "account_version", "strategy_id")
"""Identity and provenance the FRAMEWORK owns. AC-A2 forbids all four from authored code.

Each was in the old template. `uuid5` minted the intent id, `source_refs` was rebuilt by hand from
`context.window.accesses`, and `account_version` was copied off the context -- and the Flow then
recomputed every one of them and refused the intent if the author's version disagreed. Work that
can only be done one way, checked by the thing that asked for it.
"""


def _strategy(**overrides: object) -> str:
    settings: dict[str, object] = {
        "dataset_id": "prices",
        "field": "close",
        "lookback": 20,
    }
    settings.update(overrides)
    return render(ComponentKind.STRATEGY_MODEL, "demo", **settings)  # type: ignore[arg-type]


def test_the_emitted_strategy_fits_in_forty_lines() -> None:
    """AC-A1. Was 111 lines; the ceremony is what made it long."""
    body = _strategy()

    assert len(body.splitlines()) <= 40, (
        f"the scaffold grew back to {len(body.splitlines())} lines, which usually means framework "
        "bookkeeping returned to authored code"
    )


@pytest.mark.parametrize("token", BANNED)
def test_no_framework_bookkeeping_reaches_authored_code(token: str) -> None:
    """AC-A2, one assertion per token so a regression names which one came back."""
    assert token not in _strategy(), (
        f"{token!r} is back in the scaffold: it is derived by the framework, and an author who "
        "writes it by hand can only get it wrong"
    )


def test_the_author_never_rescales_or_names_the_grid() -> None:
    """AC-A6. Rounding onto the canonical grid is arithmetic, not a research decision."""
    body = _strategy()

    assert "rescale" not in body
    assert "QUANTUM" not in body


def test_the_scaffold_states_relative_conviction_not_absolute_weights() -> None:
    """AC-A6's positive half: the author says what they like; the package does the arithmetic."""
    assert "Rebalance.of(long=" in _strategy()


def test_relative_weights_normalise_to_an_exact_book() -> None:
    """The invariant `Rebalance` already enforced, now reachable without hand arithmetic.

    `sum(weights) + cash == 1` EXACTLY -- and an author computing that by hand has to land on one
    to the last digit, where a single-ulp miss is refused by the same check that catches a real
    mistake. Relative conviction cannot make that error, because no total is ever stated.
    """
    book = Rebalance.of(long={"A": 2, "B": 1}, invested="0.9")

    assert sum(book.target_weights.values()) + book.cash_weight == Decimal(1)
    assert book.target_weights["A"] == book.target_weights["B"] * 2


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        ("three equal, a 1/3 split that does not divide", {"long": {"A": 1, "B": 1, "C": 1}}),
        ("seven equal", {"long": {f"N{i}": 1 for i in range(7)}}),
        ("dollar neutral", {"long": {"A": 1}, "short": {"B": 1}}),
        ("uneven sides", {"long": {"A": 1}, "short": {"B": 1, "C": 1, "D": 1}}),
        ("awkward invested", {"long": {"A": 1, "B": 2}, "invested": "0.333"}),
        (
            "3 long vs 7 short",
            {
                "long": {f"L{i}": 1 for i in range(3)},
                "short": {f"S{i}": i + 1 for i in range(7)},
                "invested": "0.8",
            },
        ),
    ],
)
def test_every_book_is_exact_and_inside_its_own_budget(label: str, kwargs: dict) -> None:
    """The arithmetic every authored strategy depends on, over inputs that do not divide evenly.

    Two real defects were found here by running these cases rather than reasoning about them.

    First, the rounding crumb was settled in CASH. Three shorts at -0.5/3 leave -1e-12, which
    pushed cash to 1.000000000001 -- one step past fully-uninvested -- and a book that is
    arithmetically perfect was refused for a rounding artifact. The crumb now lands on the largest
    position, where it is proportionally smallest and cannot move cash across a bound.

    Second, and worse: cash was computed as `1 - invested`. For a SIGNED book `invested` is GROSS
    exposure while `sum(weights)` is NET, so a dollar-neutral book -- fully invested, netting to
    zero -- produced a residual of about 1. Cash is the net residual; those are different numbers
    and only one of them is cash.
    """
    book = Rebalance.of(**kwargs)

    assert sum(book.target_weights.values()) + book.cash_weight == Decimal(1), label
    assert all(book.budget.validates_target(v) for v in book.target_weights.values()), label
    assert book.budget.validates_cash(book.cash_weight), label


def test_a_short_only_book_is_expressible() -> None:
    """Every short-only book used to be refused -- all of them, by its own budget.

    `cash_upper` was pinned at 1 while `cash_lower` was correctly widened for shorts, and that
    asymmetry made the refusal name CASH when the real problem was a bound that cannot represent
    short-sale proceeds. Selling short raises cash: a book that is only short holds MORE than its
    NAV in cash, by exactly what it shorted. The arithmetic was right and the bound was wrong.
    """
    book = Rebalance.of(short={"A": 1, "B": 1})

    assert all(weight < 0 for weight in book.target_weights.values())
    assert book.cash_weight == Decimal(2), "shorting the whole book must raise cash above NAV"
    assert sum(book.target_weights.values()) + book.cash_weight == Decimal(1)


def test_a_name_cannot_be_long_and_short_at_once() -> None:
    """A contradiction, not a netting instruction.

    The short silently overwrote the long, so a leg the author wrote disappeared and the book was
    neither of the two things asked for. It was masked, too: the resulting net always tripped a
    cash bound, so the author got a refusal about cash that never mentioned the duplicate.
    """
    with pytest.raises(ValueError, match="long and short the same name"):
        Rebalance.of(long={"A": 1, "B": 1}, short={"A": 1})


def test_invested_means_gross_exposure_for_a_signed_book() -> None:
    """A long/short book puts `invested` to work in total, not net of the hedge."""
    book = Rebalance.of(long={"A": 1}, short={"B": 1}, invested="0.8")

    gross = sum(abs(weight) for weight in book.target_weights.values())
    assert gross == Decimal("0.8"), f"gross exposure is {gross}, not the 0.8 the author asked for"


def test_a_short_book_is_signed_without_the_author_saying_so() -> None:
    """The budget follows from what was asked for rather than being declared a second time."""
    book = Rebalance.of(long={"A": 1}, short={"B": 1})

    assert book.target_weights["B"] < 0
    assert sum(book.target_weights.values()) + book.cash_weight == Decimal(1)


def test_a_side_is_chosen_by_its_mapping_never_by_a_sign() -> None:
    """One intention must not have two spellings that disagree.

    `short={"A": 2}` means twice as short. Accepting `short={"A": -2}` would make the same wish
    expressible two ways, and the two would cancel rather than agree.
    """
    with pytest.raises(ValueError, match="must be positive"):
        Rebalance.of(short={"A": -2})


@pytest.mark.parametrize(
    ("label", "body", "expected"),
    [
        ("plain", "class Mine(StrategyModel): pass\n", "Mine"),
        # `import X as Y` used to produce a false "defines 0" about a file defining exactly one.
        ("aliased", "class Mine(SM): pass\n", "Mine"),
        # The dangerous one: only the intermediate matched, so registration SUCCEEDED naming the
        # wrong class and the run executed Base while the author believed Mine ran.
        ("inheritance chain", "class Base(StrategyModel): pass\nclass Mine(Base): pass\n", "Mine"),
        # A class in an `if` is still a class the file defines.
        ("nested", "if True:\n    class Mine(StrategyModel): pass\n", "Mine"),
    ],
)
def test_the_authored_class_is_found_however_it_was_written(
    label: str, body: str, expected: str, tmp_path: Path
) -> None:
    """The count AC-A4 rests on has to be right, so the search has to see what is really there.

    Matching direct bases by bare name in the module body only was wrong three ways, and each way
    produced a confident wrong answer rather than an error.
    """
    from vqapr.cli.register import _sole_subclass

    source = tmp_path / f"{label.replace(' ', '_')}.py"
    source.write_text(
        "from vqapr.authoring import StrategyModel\n"
        "from vqapr.authoring import StrategyModel as SM\n\n" + body,
        encoding="utf-8",
    )

    assert _sole_subclass(source, ComponentKind.STRATEGY_MODEL, "demo") == expected, label


def test_a_scaffold_with_no_strategy_is_refused_by_count(tmp_path: Path) -> None:
    """AC-A4. Wrote none, versus which one did you mean: different mistakes, different repairs."""
    from vqapr.cli.inputs import InputError
    from vqapr.cli.register import _sole_subclass

    empty = tmp_path / "empty.py"
    empty.write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(InputError) as refused:
        _sole_subclass(empty, ComponentKind.STRATEGY_MODEL, "demo")

    assert "defines 0" in (refused.value.as_dict()["failures"][0]["observed"] or "")


def test_a_scaffold_with_two_strategies_names_both(tmp_path: Path) -> None:
    """AC-A4's other half: the count AND the names, because the reader has to choose."""
    from vqapr.cli.inputs import InputError
    from vqapr.cli.register import _sole_subclass

    crowded = tmp_path / "two.py"
    crowded.write_text(
        "from vqapr.authoring import StrategyModel\n\n"
        "class First(StrategyModel):\n    pass\n\n"
        "class Second(StrategyModel):\n    pass\n",
        encoding="utf-8",
    )

    with pytest.raises(InputError) as refused:
        _sole_subclass(crowded, ComponentKind.STRATEGY_MODEL, "demo")

    observed = refused.value.as_dict()["failures"][0]["observed"] or ""
    assert "defines 2" in observed
    assert "First" in observed and "Second" in observed
