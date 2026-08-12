"""Showcase-local proof that missing price coverage cannot shrink the candidate calendar."""

from itertools import product

import pandas as pd
from run import DECLARED_SESSION_DATES, UNIVERSE, validate_declared_market_coverage


def main() -> None:
    complete = pd.DataFrame(
        (
            {"session": session, "instrument": instrument, "close": 100.0}
            for session, instrument in product(DECLARED_SESSION_DATES, UNIVERSE)
        )
    )
    validate_declared_market_coverage(complete)
    incomplete = complete.drop(index=0)
    try:
        validate_declared_market_coverage(incomplete)
    except RuntimeError as exc:
        if "BOUNDED_MARKET_COVERAGE_INCOMPLETE" not in str(exc):
            raise
    else:
        raise AssertionError("one missing instrument/session cell did not fail explicitly")
    if len(DECLARED_SESSION_DATES) != 61:
        raise AssertionError("the declared candidate calendar changed")


if __name__ == "__main__":
    main()
