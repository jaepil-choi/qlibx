"""`vqapr check <run-id>` — prove a registered run is ready without starting it or touching a file.

Two properties make this verb worth having, and both are about what it does NOT do.

**It collects.** `preflight_run` raises on the first thing it finds, which is right for a
gate standing in front of a run: the first refusal is the reason the run must not start, and
proving the rest costs time the caller did not ask for. But it makes preparing a declaration a
sequence of round trips -- fix the dataset, re-run, learn the agenda is missing, re-run, learn the
account holds an unlisted name. `check` runs the same judgments and reports every INDEPENDENT one
together, so an agent repairing its own setup receives the whole list.

**It does not mutate.** No file under `.vqapr/` is created, moved or rewritten. That is asserted
byte-for-byte in the tests rather than claimed here, and the claim stops exactly there: `check`
imports user code, because `weights` and `records` are Python and there is no way to judge a
component without loading it. What it guarantees is that *vqapr* writes nothing.

**Dependent checks are reported, not silently dropped.** Some judgments cannot run until an
earlier one passes -- there is no point resolving execution targets for a run the workspace does
not hold. Those are reported as `blocked`, naming what blocked them, so the reader can tell
"this passed" from "this never ran" from "this failed".

**A registered run since record `139`.** The argument is a run id; the phases are the workspace,
the run's registration, the judgments, and preflight. There is no file to check: the
materialization spec retired with record `148` (a datamodel is a `runs:` entry), and a path given
here is refused by name.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.run import preflight_refusal, refuse_a_path
from vqapr.domain.errors import InputError, Stage, VqaprError
from vqapr.flow.declaration.judgments import JUDGMENT_CODES
from vqapr.flow.declaration.verify import RunVerdict, verify_run
from vqapr.public import Workspace

STAGE = Stage.CHECK

SIMULATION_CODES = frozenset(JUDGMENT_CODES)
"""The judgments this verb makes about a registered RUN -- `flow/declaration/judgments.py`'s list,
not a copy.

This was a hand-written tuple of the codes the judges raise, and it drifted: a judge was added
there and the tuple here still counted the old number. The judges own their codes; this verb
publishes them.
"""

CODES = (
    *JUDGMENT_CODES,
    "run.declaration_invalid",
    "preflight.refused",
)
"""Everything this verb can emit as a failure: the judgments, plus two framework-invariant codes.

The two named here (`cli/run.preflight_refusal`) carry a bare `TypeError`/`ValueError` from a
framework invariant, which has no structured body of its own and would otherwise surface as an
`unhandled` failure.

`judgment.blocked` (`flow/declaration/judgments.JUDGMENT_BLOCKED`) is deliberately NOT here. It is
the entry for a judgment that could not answer; on the run path `RunVerdict.require_frozen` raises
it, while this verb reads the same verdict and reports such an entry under `blocked`, never under
`failures`.
"""


@dataclass(frozen=True, slots=True)
class _Phase:
    """One independently-runnable judgment, and what it needs before it can run."""

    name: str
    needs: tuple[str, ...] = ()


_PHASES = (
    _Phase("workspace"),
    _Phase("run", needs=("workspace",)),
    _Phase("judgments", needs=("run",)),
    _Phase("preflight", needs=("run",)),
)
"""The order judgments become answerable in, and nothing more.

`run` looks the registration up and cannot without a workspace; the judgments and preflight read
the definition it found. Everything else runs regardless of what else failed.
"""


def check(target: str | Path, project_root: Path) -> dict[str, Any]:
    """Run every answerable judgment and report all of them together.

    Returns the envelope body rather than raising, because a refusal here is the ANSWER to the
    question asked. `run` raises on the same conditions; `check` was asked whether they hold.
    """
    target = str(target)
    refuse_a_path(target, verb="check")
    failures: list[dict[str, Any]] = []
    passed: list[str] = []
    blocked: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    done: set[str] = set()

    workspace: Workspace | None = None
    definition: object | None = None
    # One reading of the declaration serves both the judgments phase and the preflight phase
    # (`flow/declaration/verify.py`): the judgments' answers and the freeze's refusal come out
    # of one call, made when the first of the two phases asks.
    verdict: RunVerdict | None = None
    phases = _PHASES

    for phase in phases:
        unmet = [need for need in phase.needs if need not in done]
        if unmet:
            # A phase whose need failed is skipped, not blocked: `blocked` is reserved for a
            # judgment that could not answer (a failure with a cause); this is a phase that was
            # never asked, and it is listed by name so the reader sees what was not proven.
            skipped.append({"check": phase.name, "blocked_by": ", ".join(unmet)})
            continue

        blocked_before = len(blocked)
        try:
            if phase.name == "workspace":
                workspace = Workspace.open(project_root)
            elif phase.name == "run":
                assert workspace is not None
                definition = workspace.run_definition(target)
            elif phase.name == "judgments":
                assert workspace is not None
                # The only phase that collects rather than raises. The blocked list is extended
                # BEFORE the `continue` below, because the phase loop compares `len(blocked)`
                # against `blocked_before` further down to decide whether this phase may be
                # reported as passed.
                assert definition is not None
                if verdict is None:
                    verdict = verify_run(workspace, definition)  # type: ignore[arg-type]
                # A blocked judgment is a `Failure` (`judgment.blocked`, status 500/502 by its
                # cause, `observed` naming the judge, the exception whole in `cause`), rendered
                # through the one shape -- under `blocked`, not `failures`, because nothing was
                # proven either way.
                blocked.extend(entry.as_dict() for entry in verdict.blocked)
                failures.extend(failure.as_dict() for failure in verdict.failures)
                if verdict.failures:
                    continue
            elif phase.name == "preflight":
                # The freeze's half of the same verdict: what it refused with is raised here so
                # the handlers below render it as they always have. Same workspace snapshot as
                # the judgments read (`docs/issues/archive/070`).
                assert workspace is not None and definition is not None
                if verdict is None:
                    verdict = verify_run(workspace, definition)  # type: ignore[arg-type]
                if verdict.refusal is not None:
                    raise verdict.refusal
        except VqaprError as error:
            # The framework already judged this and said why, in codes a reader may already have
            # handling for. Re-wrapping would replace an actionable refusal with a vaguer one.
            # Every entry below is `Failure.as_dict()` -- the envelope's one failure shape, not a
            # copy of it.
            refused = list(error.failures)
            if phase.name == "preflight":
                # The freeze proves again what the judgments already answered, for callers that
                # freeze without judging. Occurrences the judgments listed are not listed a second
                # time under the freeze's code (record `259`: 403 of them were, and the second
                # listing's repair was wrong for 402).
                listed = {tuple(entry["examples"]) for entry in failures if entry["examples"]}
                refused = [
                    failure
                    for failure in refused
                    if not (failure.examples and tuple(failure.examples) in listed)
                ]
            failures.extend(failure.as_dict() for failure in refused)
            continue
        except InputError as error:
            # An input refusal's own body, kept whole: the same code, source and fields it would
            # carry from any other verb, rendered through the same shape.
            failures.append(error.as_failure().as_dict())
            continue
        except Exception as error:
            # Every exception type, not a listed few: these are the cases most likely to mean a
            # phase is broken, and letting them escape renders the whole envelope as
            # `stage: "unhandled"` -- the framework broke, when the truth is the run was wrong.
            failures.append(preflight_refusal(phase.name, error, target).as_dict())
            continue

        done.add(phase.name)
        if phase.name == "judgments" and len(blocked) > blocked_before:
            # A judgment that could not look did not pass. The phase is still `done`, because the
            # phases depending on it can still be answered, but claiming it PASSED would report a
            # run nothing was proven about as clean and ready.
            continue
        passed.append(phase.name)

    return {
        # A blocked judgment is not a failure, but it is not a clean bill either: nothing was
        # proven where it could not look.
        "ok": not failures and not blocked,
        "stage": str(STAGE),
        "checked": [phase.name for phase in phases],
        "passed": passed,
        "skipped": skipped,
        "blocked": blocked,
        "failures": failures,
    }


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "target",
        help="the id of a registered run to check (the same id `vqapr run` takes)",
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    body = check(str(args.target), project_root)
    if body["ok"]:
        return success(
            str(STAGE),
            checked=body["checked"],
            passed=body["passed"],
            skipped=body["skipped"],
            blocked=body["blocked"],
        )
    return body
