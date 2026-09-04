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
the run's registration, the judgments, and preflight. A materialization spec (`datamodel:`) is
still a file, and is checked as one.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.run import preflight_refusal, refuse_a_path
from vqapr.domain.errors import ExplainTopic, Failure, FailureSource, VqaprError
from vqapr.flow.judgments import judgments
from vqapr.inputs import InputError
from vqapr.public import Workspace, preflight_run

STAGE = "run.check"

SIMULATION_CODES = (
    "check.execution.not_after_decision",
    "check.period.uncovered",
    "check.lookback.uncovered",
    "check.dataset.unregistered",
    "check.field.absent",
    "check.weights.mode_conflict",
    "check.weights.venue_conflict",
    "check.universe.absent",
)
"""The eight judgments this verb makes about a registered RUN.

Each is a question a run must answer YES to before it starts, and each is asked independently of
the others -- and of every strategy the run names -- so a declaration with four defects reports
four refusals rather than the first one four times.
"""

CODES = (
    *SIMULATION_CODES,
    f"{STAGE}.declaration_invalid",
    f"{STAGE}.preflight_refused",
)
"""Everything this verb can emit: the judgments, plus two framework-invariant codes.

The two `run.check.*` codes name a bare `TypeError`/`ValueError` from a framework invariant, which
has no structured body of its own and would otherwise surface as `stage: unhandled`.
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
    blocked: list[dict[str, str]] = []
    done: set[str] = set()

    workspace: Workspace | None = None
    definition: object | None = None
    phases = _PHASES
    source = None

    for phase in phases:
        unmet = [need for need in phase.needs if need not in done]
        if unmet:
            blocked.append({"check": phase.name, "blocked_by": ", ".join(unmet)})
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
                judged, could_not_answer = judgments(definition, workspace)  # type: ignore[arg-type]
                blocked.extend(could_not_answer)
                failures.extend(_render(failure, source) for failure in judged)
                if judged:
                    continue
            elif phase.name == "preflight":
                preflight_run(project_root, definition)  # type: ignore[arg-type]
        except VqaprError as error:
            # The framework already judged this and said why, in codes a reader may already have
            # handling for. Re-wrapping would replace an actionable refusal with a vaguer one.
            failures.extend(_render(failure, source) for failure in error.failures)
            continue
        except InputError as error:
            failures.append(_from_input(error, source))
            continue
        except Exception as error:
            # Every exception type, not a listed few: these are the cases most likely to mean a
            # phase is broken, and letting them escape renders the whole envelope as
            # `stage: "unhandled"` -- the framework broke, when the truth is the run was wrong.
            failures.append(_render(preflight_refusal(phase.name, error, target), source))
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
        "stage": STAGE,
        "checked": [phase.name for phase in phases],
        "passed": passed,
        "blocked": blocked,
        "failures": failures,
    }


def _render(failure: Failure, spec: Path | None) -> dict[str, Any]:
    """One refusal in the envelope's own shape, matching `VqaprError.as_dict` field for field.

    A materialization refusal knows the id it could not resolve but not the file that named it,
    so the file is supplied here when the refusal has none of its own. A run's refusals carry a
    `runs.<id>` key path into the declaration document instead; the document itself is not known
    to a registered run.
    """
    source = failure.source
    if spec is not None and source.file is None:
        source = replace(source, file=str(spec))
    return {
        "code": failure.code,
        "source": source.as_dict(),
        "requirement": failure.requirement,
        "observed": failure.observed,
        "fix": failure.fix,
        "explain": str(failure.explain),
        "examples": list(failure.examples),
        "example_total": failure.example_total,
    }


def _from_input(error: InputError, spec: Path | None) -> dict[str, Any]:
    """An input refusal's own body, kept whole and told which file it came from, when known."""
    carried = error.source
    source = FailureSource(
        file=carried.file or (None if spec is None else str(spec)),
        key_path=carried.key_path,
        line=carried.line,
    )
    return {
        "code": error.code,
        "source": source.as_dict(),
        "requirement": error.requirement,
        "observed": error.observed,
        "fix": error.fix,
        "explain": str(ExplainTopic.DECLARATION_SHAPE),
        "examples": list(error.examples),
        "example_total": error.example_total,
    }


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "target",
        help=(
            "the id of a registered run to check (the same id `vqapr run` takes), or the path of "
            "a materialization spec"
        ),
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    body = check(str(args.target), project_root)
    if body["ok"]:
        return success(
            STAGE,
            checked=body["checked"],
            passed=body["passed"],
            blocked=body["blocked"],
        )
    return body
