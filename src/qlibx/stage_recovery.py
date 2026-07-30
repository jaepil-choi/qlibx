"""Repair paths for each journey stage. Owned by the skill layer, not by the core.

PRD 5.6 gave the core one job at a failure: report the stage and what the contract expected,
and stop. PRD 5.3 gives this module the other half -- for every stage, the failures that
actually occur there and **more than one way out of each**, because a repair is rarely unique
and the core is not allowed to guess which one fits the user's data.

That is why this content lives here rather than in ``documentation``. ``documentation`` backs
``qlibx docs`` and ``qlibx errors <stage>``, which are core surfaces; a repair path reachable
from those surfaces would be the core prescribing again, one import removed.
``test_the_core_cannot_reach_a_repair_path`` holds that line.

Every failure below quotes a message the package really raises. A recovery guide for errors
that do not occur is worse than none: it reads as authoritative and sends the agent looking for
a symptom it will never see.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from qlibx.errors import STAGES


@dataclass(frozen=True, slots=True)
class RepairPath:
    """One legitimate way out, and the fact that selects it over the others.

    ``choose_when`` is the part that carries the weight. A list of paths without criteria
    moves the guess from the core to the agent instead of ending it.
    """

    action: str
    choose_when: str
    ask_user_first: bool


@dataclass(frozen=True, slots=True)
class StageFailure:
    """A failure the agent will actually receive, and every repair open to it."""

    symptom: str
    paths: tuple[RepairPath, ...]
    rerun: str


# Two or more paths per failure is the requirement, not a stylistic preference: a single path
# is the core's prescription rebuilt one layer up, which PRD 5.3 rejects by name.
STAGE_RECOVERY: Mapping[str, tuple[StageFailure, ...]] = {
    "ONBOARDING": (
        StageFailure(
            symptom="`Skill file has different content: <path>` -- a generated file was edited.",
            paths=(
                RepairPath(
                    action=(
                        "Keep the user's file and hand-carry whatever the new generated version "
                        "adds into it."
                    ),
                    choose_when=(
                        "The edit is deliberate project policy the user wants to survive every "
                        "regeneration."
                    ),
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Replan and apply with `--force`, then re-apply the user's edit on top.",
                    choose_when=(
                        "The difference is only that their copy is an older generated version."
                    ),
                    ask_user_first=True,
                ),
                RepairPath(
                    action=(
                        "Generate into a scratch directory instead and show the user the diff "
                        "between the two."
                    ),
                    choose_when="You cannot tell which of the two files is ahead.",
                    ask_user_first=False,
                ),
            ),
            rerun="`qlibx agent skill --output <dir> --target <target>`, then the same with "
            "`--apply`",
        ),
        StageFailure(
            symptom="`No instruction target was selected` -- no instruction file was named.",
            paths=(
                RepairPath(
                    action="Detect the instruction files that exist and let the user pick.",
                    choose_when="The repository already has an `AGENTS.md` or `CLAUDE.md`.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Create a new instruction file at a location the user names.",
                    choose_when="The repository has none and the user wants one.",
                    ask_user_first=True,
                ),
            ),
            rerun="`qlibx agent instruction --root . --detect`",
        ),
    ),
    "PROJECT": (
        StageFailure(
            symptom=(
                "`paths.<name> escapes the project: <path>` -- a configured path leaves the root."
            ),
            paths=(
                RepairPath(
                    action="Move the location under the project root and update `qlibx.yaml`.",
                    choose_when="The data belongs to this project and qlibx may write to it.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action=(
                        "Leave the file where it is and reach it as a read-only source through "
                        "data discovery instead of a configured project path."
                    ),
                    choose_when="It is shared or external data the project only ever reads.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Point the project root at the enclosing directory.",
                    choose_when="The root was drawn too narrowly and the path is genuinely inside.",
                    ask_user_first=True,
                ),
            ),
            rerun="`qlibx project status --root <root>`",
        ),
        StageFailure(
            symptom="`qlibx.yaml schema_version must be 1` -- the project file is another schema.",
            paths=(
                RepairPath(
                    action="Migrate the existing file to schema 1 field by field.",
                    choose_when="The file carries settings the user still wants.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action=(
                        "Initialize a fresh project in a scratch directory and port the settings "
                        "across."
                    ),
                    choose_when="The file came from a different qlibx version and is mostly stale.",
                    ask_user_first=True,
                ),
            ),
            rerun="`qlibx project status --root <root>`",
        ),
    ),
    "DATA_REGISTRATION": (
        StageFailure(
            symptom=(
                "`Mapped source columns do not exist: [...]` -- the mapping names a column the "
                "source does not have."
            ),
            paths=(
                RepairPath(
                    action=(
                        "Show the user the real column inventory and remap to the column they "
                        "identify."
                    ),
                    choose_when="The intended column is present under a different name.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action=(
                        "Preprocess the source into a new file that carries the column, then "
                        "register that file."
                    ),
                    choose_when="The value has to be derived, not renamed.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Drop the mapping.",
                    choose_when=(
                        "The user confirms that information is not needed for this project."
                    ),
                    ask_user_first=True,
                ),
            ),
            rerun="`qlibx data plan --root . --dataset <id>`, then `qlibx data register`",
        ),
        StageFailure(
            symptom=(
                "`Availability source must be date/timestamp, got <type>` -- the column chosen as "
                "`available_at` does not parse."
            ),
            paths=(
                RepairPath(
                    action="Parse the column at preprocessing time and register the parsed file.",
                    choose_when="It really is a timestamp stored as text or as an integer date.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Choose a different column as the availability axis.",
                    choose_when="A true 'when this became knowable' timestamp exists elsewhere.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action=(
                        "Keep the event column and declare `available_at.offset_days` from it."
                    ),
                    choose_when=(
                        "The file records when the event happened, and the user can state the lag "
                        "before it was knowable."
                    ),
                    ask_user_first=True,
                ),
            ),
            rerun="`qlibx data plan --root . --dataset <id>`, then `qlibx data register`",
        ),
    ),
    "UNIVERSE": (
        StageFailure(
            symptom=(
                "`Universe has N rows sharing an (available_at, ticker) key` -- membership is "
                "ambiguous."
            ),
            paths=(
                RepairPath(
                    action=(
                        "De-duplicate at the source, keeping the row the user names as "
                        "authoritative."
                    ),
                    choose_when="The duplicates are the same fact recorded twice.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Split the file into separate universes and register the one in scope.",
                    choose_when=(
                        "The duplicates are two different membership definitions in one file."
                    ),
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Remap the ticker column and re-register.",
                    choose_when="One instrument appears under two identifiers.",
                    ask_user_first=True,
                ),
            ),
            rerun="`qlibx data register --root . --dataset <universe>`",
        ),
        StageFailure(
            symptom=(
                "`Universe membership is missing for N registered date/ticker cells` -- the "
                "rectangle has holes."
            ),
            paths=(
                RepairPath(
                    action="Fill the missing cells as False during preprocessing.",
                    choose_when=(
                        "The user confirms that absence means non-membership. qlibx refuses this "
                        "reading on its own, which is why the failure exists."
                    ),
                    ask_user_first=True,
                ),
                RepairPath(
                    action=(
                        "Narrow the registered date or ticker range to what the universe covers."
                    ),
                    choose_when="The source never claimed to cover the wider rectangle.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Obtain the missing membership from the source and re-register.",
                    choose_when="The gap is in the extract, not in the data.",
                    ask_user_first=False,
                ),
            ),
            rerun="`qlibx data register --root . --dataset <universe>`",
        ),
    ),
    "STRATEGY_CONTRACT": (
        StageFailure(
            symptom=(
                "`universe is inherited from qlibx.pandas_strategy` or `Strategy must declare at "
                "least one Strategy-specific pandas input`."
            ),
            paths=(
                RepairPath(
                    action="Remove `universe` from the manifest inputs.",
                    choose_when="The manifest declared the inherited universe explicitly.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Declare the input the Strategy actually consumes.",
                    choose_when="The Strategy reads data beyond the inherited universe.",
                    ask_user_first=False,
                ),
            ),
            rerun="`qlibx strategy requirements --root . --strategy <id>`",
        ),
        StageFailure(
            symptom=(
                "A requirement gap from `qlibx strategy plan`: `ready` is false and roles are "
                "unresolved."
            ),
            paths=(
                RepairPath(
                    action=(
                        "Bind the role to a registered field in `config/qlibx/bindings/<id>.yaml` "
                        "after the user approves the exact mapping."
                    ),
                    choose_when="A registered dataset already carries that meaning.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Register the missing dataset first, then bind -- back to registration.",
                    choose_when="Nothing registered carries it.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Change the manifest to require a role the project can supply.",
                    choose_when="The Strategy can be written against data that already exists.",
                    ask_user_first=True,
                ),
            ),
            rerun="`qlibx strategy plan --root . --strategy <id> --binding <binding>`",
        ),
        StageFailure(
            symptom="`Strategy lookback.kind must be rows` or `lookback.value must be a positive "
            "integer`.",
            paths=(
                RepairPath(
                    action="Express the window as a row count.",
                    choose_when="The Strategy thinks in observations.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action=(
                        "Convert the user's calendar window to rows using the dataset frequency "
                        "and record the conversion as an assumption."
                    ),
                    choose_when="The user specified days or months.",
                    ask_user_first=True,
                ),
            ),
            rerun="`qlibx strategy requirements --root . --strategy <id>`",
        ),
    ),
    "STRATEGY_RUN": (
        StageFailure(
            symptom=(
                "A passed-through failure from the Strategy callable, e.g. `TypeError: "
                "unsupported operand type(s) for -: 'str' and 'float'`."
            ),
            paths=(
                RepairPath(
                    action="Cast the column inside the Strategy.",
                    choose_when=(
                        "The Strategy should tolerate the value and the registered data is right "
                        "as it stands."
                    ),
                    ask_user_first=True,
                ),
                RepairPath(
                    action=(
                        "Preprocess the source and re-register the dataset with the right dtype."
                    ),
                    choose_when="The text is a defect that every future Strategy would trip over.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Branch on the value in the Strategy and give it its meaning.",
                    choose_when="The text is a category, not a broken number.",
                    ask_user_first=True,
                ),
            ),
            rerun=(
                "`qlibx strategy preview --root . --strategy <id> --binding <binding> "
                "--decision-time <time>`"
            ),
        ),
        StageFailure(
            symptom=(
                "`Child requested dataset <name>, which the parent context does not hold` -- the "
                "child reached outside the parent's bounded slice."
            ),
            paths=(
                RepairPath(
                    action="Widen the parent manifest to declare the dataset.",
                    choose_when="The parent legitimately needs it and may see it at decision time.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Narrow the child to the inputs the parent holds.",
                    choose_when="The child was written against the whole catalog by mistake.",
                    ask_user_first=False,
                ),
            ),
            rerun=(
                "`qlibx strategy preview --root . --strategy <id> --binding <binding> "
                "--decision-time <time>`"
            ),
        ),
        StageFailure(
            symptom=(
                "`Feedback history carries N event(s) Qlib had not confirmed` or `Feedback "
                "history is not ordered by confirmed_at`."
            ),
            paths=(
                RepairPath(
                    action="Filter the history to confirmed events and sort by `confirmed_at`.",
                    choose_when="The unconfirmed events are the caller's own bookkeeping.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Resume the run from the last confirmed checkpoint instead.",
                    choose_when="The history was assembled from an interrupted run.",
                    ask_user_first=True,
                ),
            ),
            rerun="the same `run_strategy_execution(...)` call",
        ),
    ),
    "ALPHA": (
        StageFailure(
            symptom=(
                "`Unknown alpha operation: '<name>'` -- `context['available']` lists what is "
                "registered."
            ),
            paths=(
                RepairPath(
                    action="Use one of the registered operations from `context['available']`.",
                    choose_when="One of them matches the intent.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action=(
                        "Register an `OperationSpec`, or promote a validated `signal_transform` "
                        "extension."
                    ),
                    choose_when="Nothing registered does what the research needs.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Correct the name to the registered one it resembles.",
                    choose_when=(
                        "The user confirms the near-match is the operation they meant. Never "
                        "substitute a similar name silently."
                    ),
                    ask_user_first=True,
                ),
            ),
            rerun="`qlibx alpha operations`, then `qlibx alpha plan <name>`",
        ),
        StageFailure(
            symptom=(
                "A requirement gap from `qlibx alpha plan` or `qlibx alpha exposure-plan`: a role "
                "such as `group_label` is unresolved."
            ),
            paths=(
                RepairPath(
                    action="Supply the role from a registered dataset after the user approves it.",
                    choose_when="A registered dataset carries that meaning.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Choose an operation or metric that does not require the role.",
                    choose_when="The research question tolerates the simpler measurement.",
                    ask_user_first=True,
                ),
                RepairPath(
                    action="Register the data that carries the role, then plan again.",
                    choose_when="The role is essential and the data exists outside the project.",
                    ask_user_first=True,
                ),
            ),
            rerun=(
                "`qlibx alpha plan <name> --provided-input <role>` or `qlibx alpha exposure-plan "
                "--metric <metric>`"
            ),
        ),
    ),
    "PORTFOLIO": (
        StageFailure(
            symptom=(
                "`physical lower/upper bounds are incomplete or incompatible` -- raised as a plain "
                "`ValueError`; see the note above."
            ),
            paths=(
                RepairPath(
                    action="Complete the bounds for every physical instrument.",
                    choose_when="The instrument set is the one the user intends to hold.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Restrict the instrument set to those with usable bounds.",
                    choose_when="The missing instruments are not investable here.",
                    ask_user_first=True,
                ),
            ),
            rerun="the same `construct_enhanced_index(...)` call",
        ),
        StageFailure(
            symptom=(
                "`price must uniquely cover every positive-price physical instrument` -- also a "
                "plain `ValueError`."
            ),
            paths=(
                RepairPath(
                    action="De-duplicate the price input to one row per instrument.",
                    choose_when="The same instrument is priced twice.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Source the missing prices and rerun.",
                    choose_when="Instruments in the target have no price at all.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Drop the unpriced instruments from the target.",
                    choose_when="The user accepts a smaller investable set for this run.",
                    ask_user_first=True,
                ),
            ),
            rerun="the same `construct_enhanced_index(...)` call",
        ),
    ),
    "EXECUTION": (
        StageFailure(
            symptom=(
                "`Long-only weight output must be finite, non-negative, and sum to at most 1` -- "
                "the weights do not fit the declared scenario."
            ),
            paths=(
                RepairPath(
                    action="Normalize the weights before submitting them.",
                    choose_when="The sum exceeded 1 by construction and leverage was not intended.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Scale with a registered budget policy (`fixed` or `flexible`).",
                    choose_when="The scaling rule should be explicit and recorded in the lineage.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Move the run to `signed_weight` or `enhanced_index` semantics.",
                    choose_when="The negative weights are intended shorts, not an error.",
                    ask_user_first=True,
                ),
            ),
            rerun=(
                "`qlibx qlib requirements --target-semantics <semantics>`, then `qlibx qlib plan "
                "--root . --config <config>`"
            ),
        ),
        StageFailure(
            symptom=(
                "`Dataset <name> has no DatetimeIndex, so availability must be declared` or "
                "`Availability matrix for <name> does not share the dataset's axes`."
            ),
            paths=(
                RepairPath(
                    action="Declare an availability matrix on exactly the dataset's axes.",
                    choose_when=(
                        "The dataset is a matrix whose availability differs from its index."
                    ),
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Reindex the dataset on its availability timestamp.",
                    choose_when="Availability and the index are the same fact.",
                    ask_user_first=True,
                ),
            ),
            rerun="`qlibx qlib plan --root . --config <config>`",
        ),
    ),
    "RESEARCH_RECORD": (
        StageFailure(
            symptom=(
                "`A different envelope already claims artifact <id>` or `Export destination "
                "already has content: <path>`."
            ),
            paths=(
                RepairPath(
                    action="Export to a fresh destination.",
                    choose_when="Both artifacts are evidence and both must survive.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Verify the stored artifact's digest and reuse it.",
                    choose_when="The digest matches, so the content is already published.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Publish under a new artifact id.",
                    choose_when=(
                        "The content genuinely differs. A published record is durable evidence; "
                        "overwriting one is not a repair."
                    ),
                    ask_user_first=True,
                ),
            ),
            rerun="the same `ResearchCatalog` publish or export call",
        ),
        StageFailure(
            symptom="`Artifact <id> payload does not match its recorded digest`.",
            paths=(
                RepairPath(
                    action="Rerun the producer and publish a new artifact.",
                    choose_when=(
                        "The producer is deterministic and its frozen inputs are available."
                    ),
                    ask_user_first=False,
                ),
                RepairPath(
                    action=(
                        "Stop using the artifact as evidence and record that it was altered "
                        "outside qlibx."
                    ),
                    choose_when="The payload was edited in place and the producer cannot be rerun.",
                    ask_user_first=True,
                ),
            ),
            rerun="the same `ResearchCatalog` read after republishing",
        ),
    ),
    "REPORTING": (
        StageFailure(
            symptom=(
                "`unknown included report sections: [...]` or `report order must exactly cover "
                "selected sections` -- raised as a plain `ValueError`; see the note above."
            ),
            paths=(
                RepairPath(
                    action="Add the missing section to the selection.",
                    choose_when="The order is the list the user curated.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Remove the section from the order.",
                    choose_when="The selection is the list the user curated.",
                    ask_user_first=False,
                ),
            ),
            rerun="the same report composition call",
        ),
        StageFailure(
            symptom=(
                "`analysis input is not a backtest run: <run_id>` -- also a plain `ValueError`."
            ),
            paths=(
                RepairPath(
                    action="Point the analysis at a run the execution stage produced.",
                    choose_when="The user wants backtest analysis.",
                    ask_user_first=False,
                ),
                RepairPath(
                    action="Compose the report from stored artifact analysis sections instead.",
                    choose_when="The evidence to report on is an artifact, not a run.",
                    ask_user_first=False,
                ),
            ),
            rerun="the same report composition call",
        ),
    ),
}

# Stages whose failures are not in the agent vocabulary yet. Saying so is the honest thing:
# an agent told to expect `stage: "PORTFOLIO"` would wait for a field that never arrives.
UNCLASSIFIED_STAGES: Mapping[str, str] = {
    "PORTFOLIO": (
        "Portfolio construction still raises plain `ValueError`, so these failures carry no "
        "`stage`, no `expected` and no `context`. Match them by message and treat this section "
        "as the stage guide anyway."
    ),
    "REPORTING": (
        "Report composition still raises plain `ValueError`, so these failures carry no `stage`, "
        "no `expected` and no `context`. Match them by message."
    ),
}


def stage_recovery_markdown() -> str:
    """Render the reference the generated skill package ships.

    The contract line for each stage is read from ``errors.STAGES`` rather than retyped, so the
    skill cannot describe a stage the core no longer defines that way.
    """
    lines = [
        "# Repairing a qlibx failure, by journey stage",
        "",
        "qlibx reports the stage you are stuck in and what the contract expected. It does not",
        "tell you how to fix it, because more than one repair is usually valid and which one is",
        "right depends on what the data means. That choice is yours and the user's.",
        "",
        "So every failure below lists **several paths**. Read `choose this when`, decide with the",
        "evidence you have, and ask the user wherever it says to. Do not take the first path",
        "because it is first, and do not present one path to the user as though it were the only",
        "one.",
        "",
        "Run `qlibx errors <stage>` for the core's own statement of what a stage owns.",
        "",
    ]
    for stage, responsibility in STAGES.items():
        lines.extend([f"## {stage}", "", f"Stage code: `{stage}`", "", responsibility, ""])
        note = UNCLASSIFIED_STAGES.get(stage)
        if note is not None:
            lines.extend([f"> {note}", ""])
        for failure in STAGE_RECOVERY[stage]:
            lines.extend([f"### {failure.symptom}", "", "Paths:", ""])
            for index, path in enumerate(failure.paths, start=1):
                confirmation = (
                    "ask the user before taking this path"
                    if path.ask_user_first
                    else "no confirmation needed"
                )
                lines.extend(
                    [
                        f"{index}. {path.action}",
                        f"   - Choose this when: {path.choose_when}",
                        f"   - Confirmation: {confirmation}.",
                    ]
                )
            lines.extend(["", f"Then rerun: {failure.rerun}.", ""])
    return "\n".join(lines)


__all__ = [
    "STAGE_RECOVERY",
    "UNCLASSIFIED_STAGES",
    "RepairPath",
    "StageFailure",
    "stage_recovery_markdown",
]
