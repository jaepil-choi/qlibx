"""Read the project's registered instrument roster at run start, and report it.

**Moved out of `vqapr.public` by record `111`, and made public on the way.** `cli/run.py` imported
`registered_roster` -- a PRIVATE name -- from the package's documented surface, which is the shape
that tells you a module has outgrown its role: the facade had a private consumer. It is
`registered_roster` here, and the CLI reaches it by that name.

The reading is deliberately fresh rather than frozen, and `docs/issues/042` is why the guard around
it is narrow. See `registered_roster` for both.
"""

from __future__ import annotations

from pathlib import Path

from vqapr.domain.errors import (
    ExplainTopic,
    Failure,
    FailureFamily,
    VqaprError,
)

# Hoisted from four function-local imports by record `115`. They were deferred inside
# `vqapr.public`, where the facade sits above everything and importing eagerly would have been
# a cycle. That justification did not travel with the code: this module is in `flow/`, and
# `flow/orchestration.py` already imports `vqapr.workspace` at module scope. An architecture
# review of VB002 found them being carried at full weight against a ratchet whose stated point
# is that lowering it is the goal.
from vqapr.domain.roster import build_roster
from vqapr.domain.roster_export import read_roster_table
from vqapr.workspace import Workspace


def registered_roster(root_path: Path | None) -> object | None:
    """The project's instrument roster, read FRESH at run start, or `None` when none is registered.

    Read rather than frozen, and its digest is stated in the run record rather than compared
    against a recorded one. A roster grows as a matter of course -- a daily batch lists new
    tickers, issuers delist, a name is reclassified -- so a gate here would refuse every morning,
    including on runs that never touch the new name (issue 009).

    This is the first workspace read on the `run` path, which until now consumed only `frozen.*`.
    It is one small JSON file plus the tables it points at, done once per run.
    """
    if root_path is None:
        return None

    try:
        space = Workspace.open(root_path)
    except Exception:
        # A run assembled outside a workspace has no roster to find, and saying so by returning
        # `None` is honest. The refusal, when it comes, belongs at the point something asks what
        # an instrument is -- not here, where nothing has been asked yet.
        return None
    # OUTSIDE the guard above, deliberately. `registered_instruments()` raises a typed
    # `workspace.instruments.unreadable` for a roster whose POINTER is damaged, and its docstring
    # states why: "'no roster' and 'a roster whose record is damaged' are different states, and
    # only the first is ordinary." Catching it here collapsed them -- a truncated
    # `.vqapr/instruments.json` made a registered roster read as absent, so the run completed with
    # every fill recording `kind: None` and a KRX-shaped venue charged the ETF sleeve at the share
    # rate, which is `docs/issues/007` returning silently. Found by the structural audit in
    # `docs/refactoring/`, C1.
    pointer = space.registered_instruments()
    if pointer is None:
        return None
    # A REGISTERED roster that cannot be read is refused, not degraded. `list instruments` reports
    # the same failure as `unreadable` and carries on, because it is an orientation command and a
    # moved table should not remove the answer it can still give. A run is the opposite: it is
    # about to charge and size every fill, and continuing without the categories would produce a
    # complete, reproducible book computed as if nothing had a category -- silently, since a run
    # with no roster at all is legal. That is the failure this slice exists to make impossible.
    #
    # Bare exceptions were reaching the envelope as `stage: "unhandled"` here.
    try:
        tables = {
            str(kind): read_roster_table(Path(str(path)))
            for kind, path in dict(pointer["tables"]).items()
        }
        return build_roster(tables)
    except (OSError, ValueError, KeyError, TypeError) as unreadable:
        declared = ", ".join(
            f"{kind}={path}" for kind, path in sorted(dict(pointer["tables"]).items())
        )
        raise VqaprError(
            stage="run.roster",
            family=FailureFamily.DATA,
            failures=[
                Failure.bounded(
                    code="run.roster.unreadable",
                    requirement=(
                        "a registered instrument roster must be readable at run start, because "
                        "every fill is charged and sized against the category it declares"
                    ),
                    observed=f"{unreadable} (declared tables: {declared})",
                    fix=(
                        "restore the roster tables at the paths above, or re-register the roster "
                        "with `vqapr register <instruments>.yaml`; `vqapr list instruments` shows "
                        "what this project has registered"
                    ),
                    explain=ExplainTopic.RUN_PRECONDITION,
                )
            ],
            mutation=False,
            retry_precondition="restore or re-register the roster tables, then retry",
        ) from unreadable


def roster_report(root_path: Path | None, registry: object | None) -> dict[str, object] | None:
    """Which roster a run read, and what it said, or `None` when none was registered.

    `None` is the answer that matters. A run with no roster completes with every fill recording
    `kind: None`, and before this it did so in silence: nothing in the success envelope or the
    frozen record distinguished it from a run whose categories were known. On an academic venue
    that is harmless; on a KRX-shaped venue every name is then charged identically while
    `cost_by_kind()` collapses to one unlabelled bucket -- the report that would expose it is the
    one the gap erases.

    The per-category counts come from the roster already loaded for this run rather than from a
    second read, so what is reported is what was bound to the venue, not what the file says now.
    """
    if root_path is None:
        return None

    try:
        space = Workspace.open(root_path)
    except Exception:
        return None
    # Same split as `registered_roster`: an absent workspace is `None`, a DAMAGED roster pointer
    # is the typed refusal. `cli/run.py`'s `_roster_envelope` already catches that refusal and
    # reports `known: true, stale: true` -- the honest answer for a run that read its roster and
    # then lost the record of it. Swallowing it here produced `known: false` instead, which is the
    # same envelope a genuinely rosterless run gets and the opposite of the truth.
    pointer = space.registered_instruments()
    if pointer is None:
        return None
    report: dict[str, object] = {
        "digest": str(pointer["digest"]),
        "tables": sorted(str(kind) for kind in dict(pointer["tables"])),
    }
    histogram = getattr(registry, "histogram", None)
    if histogram is not None:
        report["by_kind"] = dict(histogram)
        report["instruments"] = sum(dict(histogram).values())
    return report
