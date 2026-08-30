"""`vqapr run <spec.yaml>` — freeze a declaration and execute it.

The spec is a projection of `RunDefinition`, not a second declaration language. Anything the
framework can derive — requirements, datasets, sources — is deliberately absent: restating it
here would let the file drift from the registered components, and preflight rejects that drift.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.cli.inputs import INCOMPLETE, VALUE_INVALID, InputError, read_yaml_mapping

# `register` owns the CLI spelling of a component kind and imports nothing from this module, so
# naming it here adds no cycle. The judgments take it as a callable rather than importing it
# themselves, which is what keeps `flow/` free of `cli`.
from vqapr.cli.register import cli_kind
from vqapr.domain.errors import (
    ExplainTopic,
    Failure,
    FailureFamily,
    FailureSource,
    VqaprError,
)
from vqapr.flow.judgments import judgments, materialization_judgments
from vqapr.flow.run_records import RunRecordExists, RunRecordLive
from vqapr.flow.run_spec import _REQUIRED_BY_KIND, MATERIALIZATION, SIMULATION
from vqapr.flow.store_spec import StoreSpec
from vqapr.public import (
    AccountMode,
    AccountSnapshot,
    ConstraintSet,
    MonitoringPolicy,
    OperationRole,
    RunDefinition,
    StrategyConfig,
    ValuationConfig,
    Workspace,
    preflight_run,
)
from vqapr.public import run as execute_run
from vqapr.workspace import WORKSPACE_DIRECTORY

_REQUIRED = _REQUIRED_BY_KIND[SIMULATION]
"""Every key this command cannot execute without.

`RunDefinition` permits `start`, `end`, `exchange`, `execution_input` and the initial account to be
absent, because a definition is also built in-process by callers who supply them another way. This
command always continues into `preflight_run` and then `run`, and both refuse without them. Listing
only three keys here meant the other five surfaced from deep inside the framework as
`stage: "unhandled"` — which tells an agent the framework broke, when the truth is its spec was
incomplete. Checking them here names all of the missing keys at once instead.
"""


def _timestamp(value: object, *, name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif not isinstance(value, str):
        raise InputError(
            VALUE_INVALID,
            requirement=f"{name} must be an ISO-8601 timezone-aware datetime",
            observed=f"{type(value).__name__}: {value!r}",
            retry=f"write {name} with an explicit UTC offset, then retry",
            examples=["2024-01-02T00:00:00+09:00"],
        )
    else:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise InputError(
                VALUE_INVALID,
                requirement=f"{name} must be an ISO-8601 timezone-aware datetime",
                observed=f"{name}={value!r}",
                retry=f"write {name} with an explicit UTC offset, then retry",
                examples=["2024-01-02T00:00:00+09:00"],
            ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputError(
            VALUE_INVALID,
            requirement=(
                f"{name} must include a UTC offset; a date or naive datetime does not identify "
                "one instant"
            ),
            observed=f"{name}={parsed.isoformat()!r}",
            retry=f"write {name} with an explicit UTC offset, then retry",
            examples=["2024-01-02T00:00:00+09:00"],
        )
    return parsed


def _strategy(document: dict[str, Any], workspace: Workspace) -> StrategyConfig:
    declared = document["strategy"]
    if not isinstance(declared, dict):
        raise TypeError("strategy must be a mapping")
    component = workspace.component(str(declared["component"]))
    return StrategyConfig(
        component=component,
        agenda_id=str(declared["agenda_id"]),
        agenda_role=OperationRole.STRATEGY_CALLBACK,
    )


def _valuation(document: dict[str, Any]) -> ValuationConfig:
    """Build the valuation declaration.

    Valuation declares no mark source. The book is valued from the prices the venue published as
    executable at the execution instant, which the run already reads to fill against.
    """
    declared = document["valuation"]
    if not isinstance(declared, dict):
        raise TypeError("valuation must be a mapping")
    if "mark" in declared:
        raise ValueError(
            "valuation.mark no longer exists: the book is valued from the execution table, "
            "so remove the mark declaration"
        )
    return ValuationConfig(
        agenda_id=str(declared["agenda_id"]),
        agenda_role=OperationRole.VALUATION,
    )


def _constraints(document: dict[str, Any], workspace: Workspace) -> ConstraintSet:
    declared = document.get("constraints") or ()
    return ConstraintSet(tuple(workspace.component(str(name)) for name in declared))


def _nearest_spec_value(written: str, permitted: list[str], key_path: str) -> str:
    """What to write instead, in the case this file's parser accepts.

    `register._nearest_hint` answers the same question and is deliberately not reused here: it
    lowercases its suggestion, which is right for a declaration (`kind: strategy`) and wrong for a
    run spec, which is parsed by member NAME. Suggesting `long_only` to a reader whose file must
    say `LONG_ONLY` swaps one unusable value for another -- the exact failure this issue is about.

    A near miss is named because a one-character typo is invisible to whoever typed it. Repeating
    the permitted set instead would say nothing `requirement` has not already said.
    """
    close = get_close_matches(written.upper(), permitted, n=1)
    if close:
        return (
            f"set {key_path} to {close[0]!r}, which is the closest permitted value to {written!r}"
        )
    return f"replace {written!r} at {key_path} with one of: {', '.join(permitted)}"


_FRAMEWORK_TABLES = ("vqapr.account", "vqapr.fill", "vqapr.weight")
"""The three tables every run records, which nobody declares and which are not news.

Excluded from `tables_declared` so the field answers *what did THIS run declare* rather than
restating a constant. A reader comparing two runs learns nothing from three ids that are always
present.
"""


def _tables_declared(store: StoreSpec, result: object) -> list[str]:
    """Every table this run declared, from both surfaces that can declare one.

    `tables_declared` read `store.tables` alone and reported `[]` for a run that declared
    `ff3.formation` and wrote 42 rows to it (`docs/issues/024`). The empty list was not wrong about
    what it measured -- it was measuring one of two surfaces:

    * `store.tables`, declared in the run spec's `store:` section; and
    * `StrategyModel.diagnostics()`, declared on the component itself.

    The journey declared through the second and read the first. So the field is kept and taught to
    report both, rather than removed: a reader asking what a run declared has nowhere else to look,
    and `show run`'s `tables` answers a different question -- what was RECORDED, which is empty for
    a table declared but never formed.

    This does not re-open what the comment at the call site closed. That refusal is about a
    `publishes`-shaped claim: asserting a DATASET exists when `list datasets` shows none. Naming a
    declared diagnostic table is not that claim, and nothing here says a dataset was registered.
    """
    declared = set(store.tables)
    # What the model declared and formed. A table declared on the component but never written is
    # invisible here, which is the honest limit of reading it back from the result: the run record
    # holds what was recorded, not the component's declaration list.
    declared.update(
        table_id
        for table_id in getattr(result, "tables", {})
        if table_id not in _FRAMEWORK_TABLES
    )
    return sorted(declared)


def _closed_set_member(enum: type[Any], value: object, *, key_path: str) -> Any:
    """One member of a closed set, or a refusal that names the set.

    `AccountMode[...]` raises a bare `KeyError`, and the envelope reported it as
    `observed: "KeyError: 'LONG_SHORT'"` -- an exception repr where the permitted values belong.
    The reader is told their value was rejected and left to find the legal ones themselves, which
    for this journey meant reading the enum in installed source (`docs/issues/017`).

    A closed set is the one case where a refusal can always be complete: the alternatives are
    known, finite, and cheap to print. `register.py` already learned this the expensive way -- a
    reader spent six consecutive guesses on `fill.selector` because the field name argued for a
    vocabulary the members do not use -- and this is the same remedy applied on the `run` side.
    """
    try:
        return enum[str(value).upper()]
    except KeyError:
        pass

    permitted = [member.name for member in enum]
    raise InputError(
        VALUE_INVALID,
        requirement=f"{key_path} must be one of: {', '.join(permitted)}",
        observed=f"{key_path}={value!r}",
        retry=_nearest_spec_value(str(value), permitted, key_path),
        examples=permitted,
        source=FailureSource(file=None, key_path=key_path),
    )


def _account(document: dict[str, Any]) -> tuple[AccountSnapshot | None, AccountMode | None]:
    declared = document.get("initial_account")
    if declared is None:
        return None, None
    if not isinstance(declared, dict):
        raise TypeError("initial_account must be a mapping")
    positions = {
        str(name): Decimal(str(quantity))
        for name, quantity in (declared.get("positions") or {}).items()
    }
    snapshot = AccountSnapshot(
        version=int(declared.get("version", 0)),
        cash=Decimal(str(declared["cash"])),
        positions=positions,
    )
    return snapshot, _closed_set_member(
        AccountMode, declared["mode"], key_path="initial_account.mode"
    )


def spec_kind(document: dict[str, Any]) -> str:
    """Which run this spec declares, from the component section it names.

    Refused rather than guessed when the answer is not exactly one. A spec naming both would have
    to be resolved by precedence, and a precedence rule is a thing a reader has to know before
    they can predict what their own file does.

    Raised as an `InputError` rather than added to `check`'s `CODES`: that inventory is the eight
    judgments the verb settles about a spec it could read, and this is the question of which spec
    it is holding. `_from_input` passes an `InputError` through with its own code, so the refusal
    is fully structured either way.
    """
    declared = [kind for kind in _REQUIRED_BY_KIND if kind in document]
    if len(declared) == 1:
        return declared[0]
    raise InputError(
        "check.spec.kind_ambiguous",
        requirement=(
            f"a run spec declares exactly one of `{SIMULATION}:` or `{MATERIALIZATION}:`, "
            "which is what says whether it simulates or materializes"
        ),
        observed=(
            f"declares {', '.join(declared)}" if declared else "declares neither"
        ),
        retry=(
            f"keep the one this spec is for and remove the other; `vqapr new run-spec` emits a "
            f"`{SIMULATION}:` template"
        ),
    )


def require_declared_keys(document: dict[str, Any]) -> None:
    """Reject an incomplete spec before anything is opened.

    This reads only the user's own file, so it runs first. Checking it after `Workspace.open`
    meant an incomplete spec in an uninitialised directory reported the missing workspace and
    said nothing about the spec, sending the user to fix the wrong file.
    """
    required = _REQUIRED_BY_KIND[spec_kind(document)]
    missing = [key for key in required if key not in document]
    if missing:
        raise InputError(
            INCOMPLETE,
            requirement=f"a run spec must declare: {', '.join(required)}",
            observed=f"missing {len(missing)} of {len(required)}: {', '.join(missing)}",
            retry="add the missing keys, then retry",
            examples=missing,
        )
    _require_nested_keys(document)


_NESTED_REQUIRED = {
    "strategy": ("component", "agenda_id"),
    "valuation": ("agenda_id",),
}
"""Keys inside a declared section that the readers index directly.

The top-level check above cannot see them, so writing `component_id:` where the template says
`component:` used to pass it and then surface from the declaration phase as
`observed: "KeyError: 'component'"` with a null `source.key_path` -- a raw Python exception as the
observed value, and a fix naming no cause. It cost a first-time user about four minutes of diffing
against a re-emitted template to find one word.
"""


def _require_nested_keys(document: dict[str, Any]) -> None:
    """Name a missing nested key as a missing key, before the phase that would raise on it.

    Collected across sections, like every other refusal on this surface: a spec wrong in two
    places should cost one command.
    """
    missing: list[str] = []
    for section, keys in _NESTED_REQUIRED.items():
        if section not in document:
            continue
        declared = document.get(section)
        if not isinstance(declared, dict):
            # Shape rather than absence, and the readers already refuse it with a typed message.
            continue
        missing.extend(f"{section}.{key}" for key in keys if key not in declared)
    if not missing:
        return
    first = missing[0]
    raise InputError(
        INCOMPLETE,
        requirement=f"a run spec must declare: {', '.join(sorted(missing))}",
        observed=f"missing {len(missing)}: {', '.join(sorted(missing))}",
        retry=(
            "add the missing keys, then retry; `vqapr new run-spec` emits a template naming "
            "every required key"
        ),
        examples=sorted(missing),
        source=FailureSource(file=None, key_path=first),
    )


def definition_from_document(document: dict[str, Any], workspace: Workspace) -> RunDefinition:
    """Build a `RunDefinition` without re-implementing its invariants.

    Pairing rules (exchange with execution input, start with end, snapshot with mode) are
    enforced by `RunDefinition.__post_init__`, so this function only shapes values.
    """
    require_declared_keys(document)
    exchange = document.get("exchange")
    snapshot, mode = _account(document)
    return RunDefinition(
        strategy=_strategy(document, workspace),
        valuation=_valuation(document),
        constraints=_constraints(document, workspace),
        monitoring=(
            MonitoringPolicy(
                agenda_id=str(document["monitoring"]["agenda_id"]),
                agenda_role=OperationRole.MONITORING,
            )
            if document.get("monitoring")
            else None
        ),
        exchange=workspace.component(str(exchange)) if exchange else None,
        execution_input_id=(
            str(document["execution_input"]) if document.get("execution_input") else None
        ),
        start=_timestamp(document.get("start"), name="start"),
        end=_timestamp(document.get("end"), name="end"),
        initial_account_snapshot=snapshot,
        initial_account_mode=mode,
        initial_model_memory=document.get("initial_model_memory"),
        instruments=tuple(str(name) for name in document["instruments"]),
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--force",
        action="store_true",
        # Says what the flag DOES, which is not what it said. It replaces this run's frozen
        # record under the same --run-id; it does not touch a published dataset or a registration.
        # The two dataset-exists refusals were corrected to stop naming this flag, and leaving the
        # claim alive in --help would send an agent here to read the version that was disproved.
        help=(
            "replace this run id's existing run record instead of refusing. Refusing is the "
            "default because a repeated run under the same --run-id is far more often a retry "
            "than an intended overwrite. This does not remove a published dataset"
        ),
    )
    parser.add_argument(
        "--run-id",
        dest="run_id",
        default=None,
        help="identity for this run's frozen record (defaults to the spec's filename)",
    )
    parser.add_argument(
        "spec",
        type=Path,
        help="path to the run spec YAML (write one with `vqapr new run-spec --out`)",
    )


JUDGMENT_STAGE = "run.judgments"


def _refuse_if_judged(
    failures: list[Failure], blocked: list[dict[str, str]], spec: Path
) -> None:
    """Refuse the run when a judgment refused, or when one could not answer.

    `check` asked these questions and `run` did not, so a spec with a real look-ahead -- a fill at
    15:30 with decisions at or after it -- was refused by one verb and executed by the other. The
    run then wrote a permanent record that `vqapr list runs` shows beside legitimate runs with
    nothing marking it, and there is no command that deletes a run. A reader cannot tell.

    Refusing outright, with no flag to bypass, is the decision recorded in
    `docs/implementations/087`. It is what makes `tables_declared`-style provenance unnecessary
    here: when no invalid run can be produced, no record needs a field admitting it might be one.
    `docs/issues/009` argues against exactly the shape the alternative would have had -- a refusal
    the caller passes a flag to get around, on an event that is ordinary.

    **Blocked counts as refused.** `_judgments` returns questions it could not ANSWER separately
    from questions it answered no to, and `check` treats both as not-ok (`ok` is
    `not failures and not blocked`). Refusing only on the answered-no list would let a spec nothing
    was proven about run to completion -- issue 015's own divergence, reproduced inside its fix.

    The refusals are re-raised in the codes `check` already publishes, not re-coded into a `run.*`
    namespace. A reader who has handling for `check.execution.not_after_decision` gets the same
    code from both verbs, which is the property this closes: a green `run` means what a green
    `check` means, and a red one refuses for the same stated reason.
    """
    if not failures and not blocked:
        return
    reported = list(failures)
    for entry in blocked:
        # A blocked judgment has no code of its own -- it is the absence of an answer, not an
        # answer. It gets one here so the refusal is still a six-field envelope rather than a
        # shape the reader has to special-case.
        reported.append(
            Failure.bounded(
                "run.check.judgment_blocked",
                "every judgment must be answerable before the run starts",
                observed=(
                    f"the {entry.get('check')} judgment could not answer: "
                    f"{entry.get('blocked_by')}"
                ),
                fix=(
                    "run `vqapr check` on this spec to see the full report, then fix what stopped "
                    "the judgment from answering"
                ),
                explain=ExplainTopic.RUN_PRECONDITION,
                source=FailureSource(file=str(spec)),
            )
        )
    raise VqaprError(
        stage=JUDGMENT_STAGE,
        family=FailureFamily.INTENT,
        failures=reported,
    )


def _materialize(
    args: argparse.Namespace, document: dict[str, Any], project_root: Path
) -> dict[str, Any]:
    """Run a registered DataModel, through the verb that already exists."

    A DataModel could be scaffolded, registered and described, and nothing would ever run it:
    `flow/materialize.py` held a real entry point no CLI command called. It is reached here rather
    than through a `materialize` verb of its own, because registration is already symmetric --
    `register.py` maps `datamodel` beside `strategy` -- and a second top-level verb would add an
    asymmetry rather than remove one.

    `--run-id` and `--force` are refused rather than ignored. Both are defined entirely in terms
    of a run record, and a materialization writes none: it registers a dataset. Accepting a flag
    that cannot do what its name says is how a user learns the wrong model of a command.
    """
    from vqapr.public import MaterializationSpec, materialize

    for flag, value in (("--run-id", getattr(args, "run_id", None)),
                        ("--force", getattr(args, "force", False))):
        if value:
            raise InputError(
                VALUE_INVALID,
                requirement=f"{flag} applies to a simulation, which writes a run record",
                observed=f"this spec declares `{MATERIALIZATION}:`, so it registers a dataset",
                retry=f"drop {flag}; to replace the output, remove its dataset registration first",
            )

    output = document["output"]
    if not isinstance(output, dict):
        raise InputError(
            VALUE_INVALID,
            requirement="`output:` must be a mapping declaring dataset_id and value_fields",
            observed=f"found {type(output).__name__}",
            retry="write `output:` with `dataset_id:` and `value_fields:` beneath it",
            source=FailureSource(file=None, key_path="output"),
        )
    missing = [key for key in ("dataset_id", "value_fields") if key not in output]
    if missing:
        raise InputError(
            INCOMPLETE,
            requirement="`output:` must declare dataset_id and value_fields",
            observed=f"missing {', '.join(missing)}",
            retry="add the missing keys under `output:`, then retry",
            examples=missing,
            source=FailureSource(file=None, key_path=f"output.{missing[0]}"),
        )
    # The materialization path gets its own insertion point rather than sharing the simulation's.
    # `run()` returns here before `Workspace.open` is ever reached, and these judgments need a
    # workspace -- so one is opened here, AFTER the `--run-id`/`--force` refusals above. Hoisting
    # the open to the top of `run()` instead would report an unopenable workspace ahead of a
    # misused flag, inverting an order those refusals were deliberately given.
    #
    # A materialization has no `RunDefinition`, so it has no declaration or preflight phase to sit
    # before -- `check` skips both for this kind. Judged here, immediately before the spec it would
    # otherwise build and run.
    _refuse_if_judged(
        materialization_judgments(
            document,
            Workspace.open(project_root),
            project_root,
            kind_spelling=cli_kind,
        ),
        [],
        Path(getattr(args, "spec", "")),
    )

    try:
        spec = MaterializationSpec.of(
            str(output["dataset_id"]),
            value_fields=[str(field) for field in output["value_fields"]],
        )
    except (TypeError, ValueError) as invalid:
        raise InputError(
            VALUE_INVALID,
            requirement="`output:` must describe a materialization this package can write",
            observed=str(invalid),
            retry="correct `output:`, then retry",
            source=FailureSource(file=None, key_path="output"),
        ) from invalid

    times = tuple(
        _timestamp(value, name=f"evaluate_at[{index}]")
        for index, value in enumerate(document["evaluate_at"] or ())
    )
    result = materialize(
        project_root,
        str(document[MATERIALIZATION]),
        spec,
        evaluation_times=[moment for moment in times if moment is not None],
        instruments=[str(name) for name in document["instruments"]],
    )
    # Named from what `MaterializationResult` actually carries. It has `registration`,
    # `output_path`, `lineage_path` and `invocations` -- and no row count: rows are per evaluation
    # on `MaterializationInvocation`, so the total is a sum and is reported under a name that says
    # so rather than as an unqualified "row count".
    return success(
        "materialize.complete",
        dataset_id=str(spec.dataset_id),
        output_path=str(result.output_path),
        lineage_path=str(result.lineage_path),
        evaluations=len(result.invocations),
        rows_total=sum(invocation.row_count for invocation in result.invocations),
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    spec_path = Path(args.spec)
    document = read_yaml_mapping(spec_path, what="a run spec")
    require_declared_keys(document)
    if spec_kind(document) == MATERIALIZATION:
        return _materialize(args, document, project_root)
    workspace = Workspace.open(project_root)
    # One parser owns the `store` keys, and this is its only reader in the CLI. A second place
    # reading `document["store"]` directly is how `root` becomes optional in one path and required
    # in another, with neither wrong on its own.
    store = StoreSpec.of(document.get("store"), base=spec_path.parent)
    # Before the freeze, because the refusal is about the spec rather than about the definition
    # built from it, and because this is the order `check` asks them in: judgments precede
    # declaration and preflight (`cli/check.py`'s `_PHASES`). A spec that cannot pass these has
    # nothing to gain from being frozen first.
    _refuse_if_judged(*judgments(document, workspace, spec_path), spec_path)
    frozen = preflight_run(project_root, definition_from_document(document, workspace))
    run_id = getattr(args, "run_id", None) or spec_path.stem
    try:
        result = execute_run(
            project_root,
            frozen,
            store_root=store.resolve(project_root, WORKSPACE_DIRECTORY),
            run_id=run_id,
            replace_record=bool(getattr(args, "force", False)),
        )
    except RunRecordLive as running:
        # A different remedy from RunRecordExists, and naming the wrong one here would be
        # destructive: `--force` against a live run destroys the rows it is still writing.
        raise InputError(
            VALUE_INVALID,
            requirement="a run id must not already be executing",
            observed=f"{run_id!r} is running now at {running.directory} (pid {running.holder})",
            retry=(
                "wait for that run to finish, or run with --run-id <new-id>. Do NOT use --force: "
                "it would destroy the rows that run is still writing"
            ),
        ) from running
    except RunRecordExists as existing:
        # Choosing a run id twice is a mistake the reader can fix in one flag. Letting the bare
        # FileExistsError escape renders it as `stage: "unhandled"`, which says the framework
        # broke rather than naming the id and the remedy.
        raise InputError(
            VALUE_INVALID,
            requirement="each run must have a run id no record has already been written under",
            observed=f"{run_id!r} already has a record at {existing.directory}",
            retry=(
                f"run with --run-id <new-id>, or replace the existing record deliberately: "
                f"vqapr run {spec_path} --force"
            ),
        ) from existing
    return success(
        "run.complete",
        occurrences=len(result.occurrences),
        # Two counters, reported as two fields. The run state advances on every publication,
        # including a valuation that records a mark without trading; the Account advances only
        # when a fill commits. Reporting the former under the latter's name made an independent
        # valuation clock look like it was moving the books.
        run_state_version=result.final_state.version,
        account_version=result.final_state.account.snapshot.version,
        store_root=str(store.resolve(project_root, WORKSPACE_DIRECTORY)),
        # No `publishes`-shaped field is reported here, and that is deliberate.
        #
        # `store.tables` parses, validates and resolves correctly, but nothing yet turns a
        # declared table into a registered dataset -- `publish_run_record` is the only function
        # that does, and this path does not call it. Echoing a `publishes` claim would be a
        # machine-readable claim that a dataset exists when `list datasets` shows none, and the
        # first reader of this envelope is an agent that would believe it.
        #
        # The batch's own precedent is `_contract_report`, which declines to report
        # weights/forms/records because inventing entries would report a promise nobody made. The
        # same rule applies to a promise the code has not yet kept: AC-P3's parsing half is
        # delivered and tested, its publication half is not, and the envelope says only what is
        # true today.
        tables_declared=_tables_declared(store, result),
        # What this run knew each instrument to be, or that it knew nothing. A run with no
        # registered roster completes with every fill recording `kind: None`, and it used to do so
        # in silence -- no refusal, no warning, nothing in the success envelope. On an academic
        # venue that is harmless; on a KRX-shaped venue it means every name was charged
        # identically while the record says the categories were never known, and `cost_by_kind()`
        # collapses to one unlabelled bucket. Reported on the SUCCESS path on purpose: the run is
        # legitimate, and the thing worth saying is what it was computed against.
        roster=_roster_envelope(project_root),
    )


def _roster_envelope(project_root: Path) -> dict[str, object]:
    """The roster clause of the success envelope, present whether or not one is registered.

    A mapping in every case, including failure, because a reader testing `payload["roster"]` for
    absence should not have to distinguish "no roster" from "this version does not report one".
    `known` is the field that answers the question.

    **This runs after the run completed and its record is on disk.** `_registered_roster` refuses a
    registered-but-unreadable roster, which is right at run START -- nothing has been computed yet
    and the run must not proceed without categories. Here it would be wrong: the tables can become
    unreadable in the minutes a real run takes, and letting that refusal escape would report exit 1
    for a run whose record `run_ids` already lists. The record and the command would disagree about
    whether the run happened.
    """
    from vqapr.domain.errors import VqaprError
    from vqapr.public import roster_report

    try:
        report = roster_report(project_root, _registered_roster_for_report(project_root))
    except VqaprError as vanished:
        # `known: True`, because the run DID know. `_registered_roster` refuses an unreadable
        # roster at run start, so any run reaching this envelope read its roster successfully:
        # its fills carry real `kind` values and the frozen record carries the digest and counts,
        # computed while the tables were readable. Reporting `False` here would give the field the
        # same value as a genuinely rosterless run -- whose note says every fill records
        # `kind: None` -- and a reader testing `roster["known"]` would conclude the opposite of
        # the truth. `stale` is the fact that actually differs: the counts could not be re-read.
        return {
            "known": True,
            "stale": True,
            "note": (
                "this run read a registered roster, and the roster became unreadable before the "
                "envelope was written, so the per-category counts could not be re-read; the "
                f"frozen record states what the run actually used. {vanished}"
            ),
        }
    if report is None:
        return {
            "known": False,
            "note": (
                "no instrument roster is registered, so every fill records kind: None and "
                "cost_by_kind() collapses to one unlabelled bucket; register one with "
                "`vqapr register <instruments>.yaml`"
            ),
        }
    return {"known": True, **report}


def _registered_roster_for_report(project_root: Path) -> object | None:
    from vqapr.public import _registered_roster

    return _registered_roster(project_root)
