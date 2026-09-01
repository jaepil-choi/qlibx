"""`vqapr check <spec.yaml>` — prove a run is ready without starting it or touching anything.

Two properties make this verb worth having, and both are about what it does NOT do.

**It collects.** `preflight_run` raises on the first thing it finds, which is right for a
gate standing in front of a run: the first refusal is the reason the run must not start, and
proving the rest costs time the caller did not ask for. But it makes preparing a declaration a
sequence of round trips -- fix the dataset, re-run, learn the agenda is missing, re-run, learn the
account holds an unlisted name. Each round trip is a full workspace open and a full re-read.
`check` runs the same judgments and reports every INDEPENDENT one together, so an agent repairing
its own setup receives the whole list.

**It does not mutate.** No file under `.vqapr/` is created, moved or rewritten. That is asserted
byte-for-byte in the tests rather than claimed here, and the claim stops exactly there: `check`
imports user code, because `weights` and `records` are Python and there is no way to judge a
component without loading it. `loading.py` executes a user module through
`spec_from_file_location`, so arbitrary user code can write anywhere it likes. This verb does not
sandbox that and does not pretend to; what it guarantees is that *vqapr* writes nothing.

**Dependent checks are reported, not silently dropped.** Some judgments cannot run until an
earlier one passes -- there is no point resolving execution targets for a strategy whose component
will not import. Those are reported as `blocked`, naming what blocked them, so the reader can tell
"this passed" from "this never ran" from "this failed". Reporting them as passed would be a lie,
and omitting them would make a partial report look complete.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.register import cli_kind
from vqapr.cli.run import (
    definition_from_document,
    require_declared_keys,
    spec_kind,
)
from vqapr.domain.errors import ExplainTopic, Failure, FailureSource, VqaprError
from vqapr.flow.judgments import judgments, materialization_judgments
from vqapr.flow.run_spec import MATERIALIZATION
from vqapr.inputs import InputError, read_yaml_mapping
from vqapr.public import Workspace, preflight_run

STAGE = "run.check"

SIMULATION_CODES = (
    "check.execution.not_after_decision",
    "check.period.uncovered",
    "check.lookback.uncovered",
    "check.field.absent",
    "check.weights.mode_conflict",
    "check.weights.venue_conflict",
    "check.universe.absent",
)
"""The eight judgments this verb makes about a SIMULATION spec.

Each is a question a run must answer YES to before it starts, and each is asked independently of
the others so a declaration with four defects reports four refusals rather than the first one four
times.

Eight, and adding a ninth is a decision rather than a detail. That is why the materialization
judgments below are a separate tuple instead of an extension of this one: they are not more
questions about a simulation, they are the questions a different kind of run has to answer.
"""

MATERIALIZATION_CODES = (
    "check.materialize.component_unregistered",
    "check.materialize.component_wrong_kind",
    "check.materialize.component_unloadable",
    "check.materialize.output_registered",
    "check.materialize.no_evaluation_instants",
    "check.materialize.no_instruments",
    "check.materialize.requirement_unregistered",
    "check.materialize.lookback_uncovered",
    "check.materialize.evaluation_instant_invalid",
)
"""The judgments this verb makes about a MATERIALIZATION spec.

Every one is a refusal `materialize()` raises later, hoisted to where it costs nothing. A verb that
certifies a spec the next command rejects is worse than no verb, because it teaches the reader to
stop trusting it -- `docs/issues/012` records that divergence still open on the simulation side,
and extending `run` without extending `check` would have opened a second one in the task meant to
close a door.

Separately namespaced so the eight above stay a statement about simulations. A reader counting the
judgments a simulation settles gets eight whether or not this tuple ever grows.
"""

CODES = (
    *SIMULATION_CODES,
    *MATERIALIZATION_CODES,
    f"{STAGE}.declaration_invalid",
    f"{STAGE}.preflight_refused",
)
"""Everything this verb can emit: both judgment sets, plus two framework-invariant codes.

The two `run.check.*` codes are different in kind from either set: they name a bare
`TypeError`/`ValueError` from a framework invariant, which has no structured body of its own and
would otherwise surface as `stage: unhandled` -- telling an agent the framework broke when its spec
was wrong. Refusals that DO have a code keep it; `check` is not a second name for a defect that
already has one.
"""


@dataclass(frozen=True, slots=True)
class _Phase:
    """One independently-runnable judgment, and what it needs before it can run."""

    name: str
    needs: tuple[str, ...] = ()


_PHASES = (
    _Phase("spec"),
    _Phase("workspace"),
    _Phase("judgments", needs=("spec", "workspace")),
    _Phase("declaration", needs=("spec", "workspace")),
    _Phase("preflight", needs=("declaration",)),
)
"""The order judgments become answerable in, and nothing more.

`declaration` cannot be built without both a spec to read and a workspace to resolve ids against;
`preflight` cannot freeze a definition that was never built. Everything else runs regardless of
what else failed, which is what makes collecting possible at all.
"""

_MATERIALIZATION_PHASES = (
    _Phase("spec"),
    _Phase("workspace"),
    _Phase("judgments", needs=("spec", "workspace")),
)
"""The same order, minus the two phases that are `RunDefinition`-shaped.

`declaration` builds a `RunDefinition` and `preflight` freezes one, and a materialization has
neither -- no venue, no execution table, no account, no trading period. Running them anyway is not
a near miss: `_judge_period` returns `check.period.uncovered` for any spec without `start`/`end`,
and `ok` is `not failures and not blocked`, so `check` would refuse every valid materialization
spec ever written. That is the mirror of the defect this slice opened with -- a verb refusing what
`run` would accept -- and it is the reason the fork is here rather than at the readers.
"""


def phases_for(document: dict[str, Any] | None) -> tuple[_Phase, ...]:
    """Which phases answer questions about this spec.

    Falls back to the simulation tuple when the document could not be read at all, so a spec that
    fails at the `spec` phase still reports the phases it was measured against.
    """
    if document is None:
        return _PHASES
    try:
        return _MATERIALIZATION_PHASES if spec_kind(document) == MATERIALIZATION else _PHASES
    except InputError:
        # Which kind it is, is itself the refusal. The `spec` phase reports it; this only has to
        # pick a tuple to name in `checked`.
        return _PHASES





def check(spec: Path, project_root: Path) -> dict[str, Any]:
    """Run every answerable judgment and report all of them together.

    Returns the envelope body rather than raising, because a refusal here is the ANSWER to the
    question asked. `run` raises on the same conditions; `check` was asked whether they hold.
    """
    # Rendered bodies rather than `Failure` objects, because two of the three sources already have
    # one: a `VqaprError` carries structured failures and an `InputError` carries its own body.
    # Round-tripping those back through `Failure.bounded` would rebuild what already exists and
    # hand the refusal-code inventory codes it cannot fold.
    failures: list[dict[str, Any]] = []
    passed: list[str] = []
    blocked: list[dict[str, str]] = []
    done: set[str] = set()

    document: dict[str, Any] | None = None
    workspace: Workspace | None = None
    definition: object | None = None

    # Read before the loop, because which phases apply depends on what the spec declares and the
    # loop cannot be iterating a tuple it has not chosen yet. Failures are left to the `spec`
    # phase below, which re-reads and reports them properly -- this only picks the tuple.
    try:
        document = read_yaml_mapping(spec, what="a run spec")
    except Exception:
        document = None
    phases = phases_for(document)
    document = None

    for phase in phases:
        unmet = [need for need in phase.needs if need not in done]
        if unmet:
            blocked.append({"check": phase.name, "blocked_by": ", ".join(unmet)})
            continue

        blocked_before = len(blocked)
        try:
            if phase.name == "spec":
                document = read_yaml_mapping(spec, what="a run spec")
                require_declared_keys(document)
            elif phase.name == "workspace":
                workspace = Workspace.open(project_root)
            elif phase.name == "judgments":
                assert document is not None and workspace is not None
                if phases is _MATERIALIZATION_PHASES:
                    judged = materialization_judgments(
                        document, workspace, project_root, kind_spelling=cli_kind
                    )
                    failures.extend(_render(failure, spec) for failure in judged)
                    if judged:
                        continue
                    done.add(phase.name)
                    passed.append(phase.name)
                    continue
                # The only phase that collects rather than raises. Each judgment is independent,
                # so a spec with four defects must report four refusals -- reporting the first
                # would make the reader fix one thing per round trip, which is the friction this
                # verb exists to remove.
                #
                # The blocked list is extended BEFORE the `continue` below, because the phase loop
                # compares `len(blocked)` against `blocked_before` further down to decide whether
                # this phase may be reported as passed. Extending it after would let a judgment
                # that could not answer be reported as a pass.
                judged, could_not_answer = judgments(document, workspace, spec)
                blocked.extend(could_not_answer)
                failures.extend(_render(failure, spec) for failure in judged)
                if judged:
                    continue
            elif phase.name == "declaration":
                assert document is not None and workspace is not None
                definition = definition_from_document(document, workspace)
            elif phase.name == "preflight":
                preflight_run(project_root, definition)
        except VqaprError as error:
            # The framework already judged this and said why, in codes a reader may already have
            # handling for. Re-wrapping would replace an actionable refusal with a vaguer one --
            # but the framework was handed ids, not a file, so it cannot know WHICH spec named
            # them. `check` does, and adds only that.
            failures.extend(_render(failure, spec) for failure in error.failures)
            continue
        except InputError as error:
            failures.append(_from_input(error, spec))
            continue
        except Exception as error:
            # Every exception type, not a listed few. A `KeyError` from a spec missing a key, an
            # `AttributeError` from a shape nobody expected -- these are the cases most likely to
            # mean a phase is broken, and letting them escape renders the whole envelope as
            # `stage: "unhandled"`: the framework broke, when the truth is the spec was wrong.
            # `check` was asked a question, and every answer it can give belongs in its envelope.
            failures.append(_render(_from_python(phase.name, error, spec), spec))
            continue

        done.add(phase.name)
        if phase.name == "judgments" and len(blocked) > blocked_before:
            # A judgment that could not look did not pass. The phase is still `done`, because the
            # phases depending on it can still be answered, but claiming it PASSED would report a
            # spec nothing was proven about as clean and ready.
            continue
        passed.append(phase.name)

    return {
        # A blocked judgment is not a failure, but it is not a clean bill either: nothing was
        # proven where it could not look. `ok` says the spec is ready to run, and a spec with an
        # unanswered judgment is not something this verb can vouch for.
        "ok": not failures and not blocked,
        "stage": STAGE,
        "checked": [phase.name for phase in phases],
        "passed": passed,
        "blocked": blocked,
        "failures": failures,
    }


def _render(failure: Failure, spec: Path) -> dict[str, Any]:
    """One refusal in the envelope's own shape, matching `VqaprError.as_dict` field for field.

    A framework refusal knows the id it could not resolve but not the document that named it --
    it was handed a string. Every refusal this verb reports came from ONE spec, so the file is
    supplied here when the refusal has none of its own. Anything the refusal did know is left
    exactly as it was.
    """
    source = failure.source
    if source.file is None:
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


def _from_input(error: InputError, spec: Path) -> dict[str, Any]:
    """An input refusal's own body, kept whole and told which file it came from.

    Not rebuilt into a `Failure`. Re-coding it as `run.check.*` would rename a defect the reader
    may already have handling for, and reconstructing it through `Failure.bounded` would hand the
    refusal-code inventory a code it cannot fold statically -- so the code would silently drop out
    of the published inventory. Passing the body through costs neither.
    """
    # `error.fix` is the field the envelope publishes; reading `error.retry` instead was a second
    # definition of the same value, which is the very drift this batch fixed elsewhere. And a
    # source the error already carried is kept rather than overwritten -- the error knows its own
    # key path, and this only knows the file.
    # `error.source` directly: `InputError.__init__` always assigns it, and
    # getattr-with-default on a known type is the exact idiom that left three judgments
    # permanently dead one generation ago.
    carried = error.source
    # MERGED, not replaced. The previous form swapped the whole source out whenever `file` was
    # absent -- which is exactly the case where the error carries a `key_path` and no file, so the
    # one field this function cannot know was the one it discarded. That contradicted the comment
    # above it, and it is why a refusal naming `strategy.component` still reported
    # `key_path: null`.
    source = FailureSource(
        file=carried.file or str(spec),
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


def _from_python(phase: str, error: Exception, spec: Path) -> Failure:
    """A bare TypeError or ValueError from a framework invariant, given an envelope.

    These are the framework's own assertions about a definition's shape. They are real refusals
    with no structured body of their own, so rather than let them surface as `stage: unhandled` --
    which tells an agent the framework broke when its declaration was wrong -- they are named
    here.

    The two codes are written literally rather than selected into a variable so the refusal-code
    inventory's constant folding can see them. A code that reaches the inventory only at runtime
    is a code that drops out of it the first time no fixture happens to trigger this path.
    """
    detail = f"{type(error).__name__}: {error}"
    fix = f"correct the run spec at {spec} so the {phase} phase completes, then check again"
    source = FailureSource(file=str(spec))
    if phase == "declaration":
        return Failure.bounded(
            "run.check.declaration_invalid",
            "the spec must resolve against what the workspace has registered",
            observed=detail,
            fix=fix,
            explain=ExplainTopic.DECLARATION_SHAPE,
            source=source,
        )
    return Failure.bounded(
        "run.check.preflight_refused",
        "every run precondition must hold before the run starts",
        observed=detail,
        fix=fix,
        explain=ExplainTopic.RUN_PRECONDITION,
        source=source,
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "spec",
        type=Path,
        help="path to the run spec YAML to check (the same file `vqapr run` takes)",
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    body = check(Path(args.spec), project_root)
    if body["ok"]:
        return success(
            STAGE,
            checked=body["checked"],
            passed=body["passed"],
            blocked=body["blocked"],
        )
    return body
