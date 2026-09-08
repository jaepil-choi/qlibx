"""Read the project's registered instrument roster at run start, and report it.

**Moved out of `vqapr.public` by record `111`, and made public on the way.** `cli/run.py` imported
`registered_roster` -- a PRIVATE name -- from the package's documented surface, which is the shape
that tells you a module has outgrown its role: the facade had a private consumer. It is
`registered_roster` here, and the CLI reaches it by that name.

The reading is deliberately fresh rather than frozen, and `docs/issues/042` and `docs/issues/050`
are why the guard around it is narrow. **The roster is read exactly once per run**: what that read
produced is carried in a `RegisteredRoster` and handed to `roster_report`, so the record describes
the roster the fills were classified by rather than the file as it stands when the record is
written. See `registered_roster` for all of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vqapr.domain.errors import Failure, Stage, Status, VqaprError

# Hoisted from four function-local imports by record `115`. They were deferred inside
# `vqapr.public`, where the facade sits above everything and importing eagerly would have been
# a cycle. That justification did not travel with the code: this module is in `flow/`, and
# `flow/orchestration.py` already imports `vqapr.workspace` at module scope. An architecture
# review of VB002 found them being carried at full weight against a ratchet whose stated point
# is that lowering it is the goal.
from vqapr.domain.instruments import InstrumentRoster, build_roster, read_roster_table
from vqapr.workspace import Workspace

WORKSPACE_ABSENT = "workspace.missing"
"""The one refusal from `Workspace.open` that means "there is no roster here to find".

`Workspace.open` also raises `workspace.unreadable` for a permission problem and
`workspace.invalid` for a file that does not decode. Those are damaged workspaces, not absent
ones, and `docs/issues/050` is what treating them as absent cost.
"""


@dataclass(frozen=True, slots=True)
class RegisteredRoster:
    """One read of the roster: the registry a run binds to, and the pointer facts beside it.

    The three travel together because they are one observation. `digest` and `tables` used to be
    re-read from `.vqapr/instruments.json` when the record was written, minutes after `registry`
    was built from it, so a `vqapr register` landing mid-run made the frozen record state the NEW
    roster's digest beside fills classified by the OLD one -- and report the pair as a single
    consistent fact. That is `docs/issues/050`, half two.
    """

    registry: InstrumentRoster
    digest: str
    tables: tuple[str, ...]


def registered_roster(root_path: Workspace | Path | None) -> RegisteredRoster | None:
    """The project's instrument roster, read FRESH at run start, or `None` when none is registered.

    Read rather than frozen, and its digest is stated in the run record rather than compared
    against a recorded one. A roster grows as a matter of course -- a daily batch lists new
    tickers, issuers delist, a name is reclassified -- so a gate here would refuse every morning,
    including on runs that never touch the new name (issue 009).

    This is the first workspace read on the `run` path, which until now consumed only `frozen.*`.
    It is one small JSON file plus the tables it points at, done once per run -- and once is
    literal: `roster_report` is handed what this returned rather than reading it again. A caller
    that already holds the `Workspace` passes it (`docs/issues/070`): the document is not opened
    again for the pointer it merely locates.
    """
    if root_path is None:
        return None

    try:
        space = root_path if isinstance(root_path, Workspace) else Workspace.open(root_path)
    except VqaprError as unopened:
        # NARROW, by `docs/issues/050`. A run assembled outside a workspace has no roster to find,
        # and saying so by returning `None` is honest: the refusal, when it comes, belongs at the
        # point something asks what an instrument is -- not here, where nothing has been asked
        # yet. But `Workspace.open` decodes `.vqapr/workspace.yaml`, and a file that is corrupt or
        # half-written -- a crash mid-write, a `vqapr register` landing mid-run, a hand edit --
        # makes it raise `workspace.open.invalid` instead. Catching that too collapsed the two
        # states this module keeps apart four lines below, and a project that HAS a roster read as
        # one that never had one: the run continued and every fill recorded `kind: None`, which on
        # a KRX-shaped venue charges the ETF sleeve at the share rate. `docs/issues/007` through a
        # `try/except` written for a different case.
        if not _absent_workspace(unopened):
            raise
        return None
    # OUTSIDE the guard above, deliberately. `registered_instruments()` raises a typed
    # `roster.unreadable` for a roster whose POINTER is damaged, and its docstring
    # states why: "'no roster' and 'a roster whose record is damaged' are different states, and
    # only the first is ordinary." Catching it here collapsed them -- a truncated
    # `.vqapr/instruments.json` made a registered roster read as absent, so the run completed with
    # every fill recording `kind: None` and a KRX-shaped venue charged the ETF sleeve at the share
    # rate, which is `docs/issues/007` returning silently. Found by the structural audit in
    # `docs/diagnostics/2026-08-31-vqapr-structural-refactoring.md`, C1.
    pointer = space.registered_instruments()
    if pointer is None:
        return None
    pointer_tables = pointer["tables"]
    if not isinstance(pointer_tables, dict):
        raise RuntimeError("roster pointer left the workspace without a tables object")
    declared_tables = dict(pointer_tables)
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
            str(kind): read_roster_table(Path(str(path))) for kind, path in declared_tables.items()
        }
        registry = build_roster(tables)
    except (OSError, ValueError, KeyError, TypeError) as unreadable:
        declared = ", ".join(f"{kind}={path}" for kind, path in sorted(declared_tables.items()))
        raise VqaprError(
            stage=Stage.READ,
            failures=[
                Failure.bounded(
                    code="roster.unreadable",
                    status=Status.UNAVAILABLE,
                    cause=unreadable,
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
                )
            ],
            mutation=False,
            retry_precondition="restore or re-register the roster tables, then retry",
        ) from unreadable
    # The digest and the table list are taken HERE, from the pointer this registry was built from,
    # and travel with it. See `RegisteredRoster`.
    return RegisteredRoster(
        registry=registry,
        digest=str(pointer["digest"]),
        tables=tuple(sorted(str(kind) for kind in declared_tables)),
    )


def roster_report(read: RegisteredRoster | None) -> dict[str, object] | None:
    """Which roster a run read, and what it said, or `None` when none was registered.

    `None` is the answer that matters. A run with no roster completes with every fill recording
    `kind: None`, and before this it did so in silence: nothing in the success envelope or the
    frozen record distinguished it from a run whose categories were known. On an academic venue
    that is harmless; on a KRX-shaped venue every name is then charged identically while the
    report's cost by kind collapses to one "unknown" bucket -- the report that would expose it
    is the one the gap erases.

    **Every field comes from the read this was handed, and nothing is read here.** The docstring
    used to claim that and it was true of the counts alone: `digest` and `tables` came from a
    second `registered_instruments()`, so a `vqapr register` during a long run made the record
    state one roster's digest beside another roster's counts (`docs/issues/050`, half two). Taking
    a `RegisteredRoster` rather than a project root is what makes the claim structural: there is no
    path from here to the file.
    """
    if read is None:
        return None
    report: dict[str, object] = {"digest": read.digest, "tables": list(read.tables)}
    histogram = read.registry.histogram
    report["by_kind"] = dict(histogram)
    report["instruments"] = sum(dict(histogram).values())
    return report


def _absent_workspace(refusal: VqaprError) -> bool:
    """Whether this refusal says the workspace is not there, as opposed to not readable."""
    return bool(refusal.failures) and all(
        failure.code == WORKSPACE_ABSENT for failure in refusal.failures
    )
