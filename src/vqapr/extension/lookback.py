"""Which lookback window a component kind may declare, and how much of it.

Beside `scaffold.py`, because that is what it serves. It was `authoring_lookback.py` at the
top level until record `193`, where the name put it next to the authoring contract -- but it
declares nothing an author subclasses. It answers what `vqapr new` should emit, its only
caller is `cli/new.py`, and it reads `ComponentKind` from this package.

**Moved out of `cli/new.py` by record `114`.** This is a domain rule, not an argparse concern: the
strategy scaffold takes rows only, because its emitted `len(values) >= LOOKBACK` guard counts
observations and a calendar window would make that guard count observations against a number of
days (`docs/issues/033`). A second surface that scaffolds a component has to apply the same rule,
and while it lived beside the flag parsing it could only be reached by building a `Namespace`.

Takes the two values rather than a `Namespace`, so a caller that never saw argparse can use it.
"""

from __future__ import annotations

from vqapr.domain.inputs import VALUE_INVALID, InputError
from vqapr.extension.component import ComponentKind

LOOKBACK_DEFAULT = 6
"""Rows of history the scaffold declares when the author does not say."""

DECLARATION_KIND = {
    ComponentKind.DATA_MODEL: "datamodel",
    ComponentKind.STRATEGY_MODEL: "strategy",
}
"""How each scaffoldable kind is spelled on the command line and in a declaration."""


def lookback_declaration(
    kind: ComponentKind, *, rows: int | None, calendar: int | None, instants: int | None = None
) -> dict[str, object]:
    """Which lookback the scaffold declares, and how much of it.

    Two flags rather than one with a unit suffix, because the two are different questions -- N rows
    per name, or N calendar days for everyone -- and a single `--lookback 313` cannot say which was
    meant. Giving both is refused rather than resolved by precedence: a reader should not have to
    know which flag wins to predict what their own command emits.

    The strategy scaffold takes rows only, and says so here rather than emitting a file whose
    `len(values) >= LOOKBACK` guard counts observations against a number of days
    (`docs/issues/033`).
    """
    given = {
        name: value
        for name, value in (
            ("--lookback", rows),
            ("--calendar-lookback", calendar),
            ("--instants-lookback", instants),
        )
        if value is not None
    }
    if len(given) > 1:
        raise InputError(
            VALUE_INVALID,
            requirement=(
                f"{' and '.join(given)} declare {'two' if len(given) == 2 else 'three'} "
                "different windows"
            ),
            observed=" and ".join(f"{name} {value}" for name, value in given.items()),
            retry=(
                "keep --lookback for the table's last N rows (a panel grain), --calendar-lookback "
                "for a window of N days every name shares, or --instants-lookback for each name's "
                "own last N reported instants (a rows grain); drop the others"
            ),
        )
    if instants is not None:
        if instants <= 0:
            raise InputError(
                VALUE_INVALID,
                requirement="--instants-lookback must be a positive number of instants",
                observed=f"--instants-lookback {instants}",
                retry="pass a positive number of instants per name, then retry",
            )
        return {"lookback": instants, "lookback_kind": "instants"}
    if calendar is None:
        return {
            "lookback": LOOKBACK_DEFAULT if rows is None else rows,
            "lookback_kind": "rows",
        }
    if calendar <= 0:
        raise InputError(
            VALUE_INVALID,
            requirement="--calendar-lookback must be a positive number of days",
            observed=f"--calendar-lookback {calendar}",
            retry="pass a positive number of calendar days, then retry",
        )
    if kind is not ComponentKind.DATA_MODEL:
        raise InputError(
            VALUE_INVALID,
            requirement="--calendar-lookback applies to the datamodel scaffold",
            observed=f"--calendar-lookback given for kind {DECLARATION_KIND[kind]}",
            retry=(
                "scaffold the strategy with --lookback, whose signal counts observations per "
                "name, and edit its DatasetInput if you want a calendar window"
            ),
        )
    return {"lookback": calendar, "lookback_kind": "calendar"}
