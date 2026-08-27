"""show_009 — the same strategy, before and after the authoring contract.

Runs one cross-sectional momentum view twice on committed sample data: once returning a
hand-assembled portfolio the way a user had to before Step 7, and once returning
`Rebalance.of(long=...)`. Both produce the same book, which is the point -- the ceremony was never
carrying information, it was carrying the risk of getting arithmetic wrong.

Reproduce:

```
uv run python showcases/show_009_authoring_contract/run.py
```
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from vqapr.authoring import Rebalance
from vqapr.portfolio.budgets import PortfolioDirection
from vqapr.portfolio.optimize import QUANTUM

OUTPUTS = Path(__file__).parent / "outputs"

SCORES = {
    "A005930": Decimal("0.081"),
    "A000660": Decimal("0.047"),
    "A035420": Decimal("0.019"),
}
INVESTED = Decimal("0.9")


def by_hand() -> dict[str, object]:
    """What an author wrote before: normalise, scale, round, and make it sum to one.

    Every line is arithmetic with one right answer, and every line is a place to be wrong. The
    last one is the trap -- `sum(weights) + cash` is checked EXACTLY, so a residual of one ulp is
    refused by the same invariant that catches a real mistake.
    """
    total = sum(SCORES.values(), Decimal(0))
    weights = {
        name: (score / total * INVESTED).quantize(QUANTUM) for name, score in sorted(SCORES.items())
    }
    # The author has to notice this. Three names rarely divide evenly, so the quantised weights
    # do not sum to `INVESTED`, and cash has to absorb whatever is left rather than being the
    # `1 - INVESTED` the author was thinking of.
    cash = Decimal(1) - sum(weights.values(), Decimal(0))
    return {
        "weights": {name: str(value) for name, value in weights.items()},
        "cash": str(cash),
        "exact": sum(weights.values(), Decimal(0)) + cash == Decimal(1),
        "budget": PortfolioDirection.LONG_ONLY.name,
        "lines_of_arithmetic": 4,
    }


def with_the_contract() -> dict[str, object]:
    """What an author writes now: which names, how much they like them, how much to invest."""
    book = Rebalance.of(long=SCORES, invested=INVESTED)
    return {
        "weights": {name: str(value) for name, value in sorted(book.target_weights.items())},
        "cash": str(book.cash_weight),
        "exact": sum(book.target_weights.values(), Decimal(0)) + book.cash_weight == Decimal(1),
        "budget": book.budget.direction.name,
        "lines_of_arithmetic": 0,
    }


def a_signed_book() -> dict[str, object]:
    """The case the hand-written form gets wrong more often than not.

    `invested` on a signed book is GROSS exposure while `sum(weights)` is NET, so the cash an
    author computes as `1 - invested` is wrong for every long/short book -- and a dollar-neutral
    one, which is fully invested and nets to zero, is wrong by the whole portfolio.
    """
    book = Rebalance.of(long={"A005930": 2, "A000660": 1}, short={"A035420": 1}, invested="0.8")
    gross = sum(abs(value) for value in book.target_weights.values())
    return {
        "weights": {name: str(value) for name, value in sorted(book.target_weights.items())},
        "cash": str(book.cash_weight),
        "gross_exposure": str(gross),
        "budget": book.budget.direction.name,
        "naive_cash_would_have_been": str(Decimal(1) - Decimal("0.8")),
        "actual_cash_is": str(book.cash_weight),
    }


def main() -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    manual = by_hand()
    contract = with_the_contract()
    signed = a_signed_book()

    report = {
        "by_hand": manual,
        "with_the_contract": contract,
        "same_book": (
            manual["weights"] == contract["weights"] and manual["cash"] == contract["cash"]
        ),
        "signed_book": signed,
    }
    (OUTPUTS / "authoring_contract.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )

    print("by hand      :", manual["weights"], "cash", manual["cash"])
    print("with contract:", contract["weights"], "cash", contract["cash"])
    print("same book    :", report["same_book"])
    print()
    print("signed book  :", signed["weights"])
    print("  gross      :", signed["gross_exposure"], "(the invested fraction, put fully to work)")
    print("  cash       :", signed["actual_cash_is"],
          f"(1 - invested would have said {signed['naive_cash_would_have_been']})")
    print()
    print(f"wrote {OUTPUTS / 'authoring_contract.json'}")


if __name__ == "__main__":
    main()
