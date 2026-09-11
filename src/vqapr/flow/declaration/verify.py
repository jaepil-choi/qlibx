"""The one door from a registered `RunDefinition` to a `FrozenRun`: `verify_run`.

`docs/design/2026-09-10-one-door-for-a-run.md`. A run declaration used to be read twice on its way
to running: once by the judgments (`judgments.py`, which answer every question independently so
`check` can report every defect at once) and once by the freeze (`preflight.py`, which resolves
names to values and refuses at the first). The two grew apart historically (records `087`, `168`
bolted them in sequence after `run` executed what `check` refused) and each derived the same facts
-- the agenda, the execution table and its horizon, the loaded components, the digests -- so one
`vqapr run` read the execution table five times (`experiments/exp_238`).

This module is the door both verbs and both doors (`cli` and `public.execute`) pass through, and
the `--jobs` worker too, which used to freeze without asking the judgments at all. What it returns
is a `RunVerdict`: the judgments' refusals, the judgments that could not answer, and either the
frozen run or what the freeze refused with -- kept as the exception it raised, because the two
verbs render a refusal differently (`check` as a failure entry with its stage, `run` as the
raised error with its own `retry_precondition`) and both must go on saying exactly what they said.

The facts are read once (`preflight.RunFacts`), and the judges and the freeze read them from
there.
"""

from __future__ import annotations

from dataclasses import dataclass

from vqapr.component.compliance.base import Compliance
from vqapr.component.datamodel import DataModel
from vqapr.component.exchange.base import Exchange
from vqapr.component.loading import load_compliance, load_data_model, load_strategy_model
from vqapr.component.strategy.base import StrategyModel
from vqapr.domain.errors import Failure, Stage, VqaprError
from vqapr.domain.fill import ExecutionHorizon
from vqapr.flow.declaration.frozen import FrozenRun
from vqapr.flow.declaration.judgments import RUN_OUTPUT_STALE, judgments
from vqapr.flow.declaration.preflight import RunFacts
from vqapr.flow.declaration.preflight import preflight_run as _freeze
from vqapr.workspace.registry import Workspace
from vqapr.workspace.run_definition import RunDefinition


@dataclass(frozen=True, slots=True)
class RunResources:
    """What the verification loaded and read, handed to the run so it does not again.

    A `FrozenRun` is a record value -- it is written to `run.json` -- so it cannot carry a live
    strategy instance or a venue. The verification had to load them (to ask what they read, to
    prove the initial memory, to judge the listings) and had to cut the execution horizon; the
    run used to import every component again and scan the horizon again on its first accepted
    intent (record `242`). `run_identity` is the frozen run these belong to: `run` refuses
    resources frozen for another run.
    """

    run_identity: str
    strategy: StrategyModel | None
    datamodel: DataModel | None
    exchange: Exchange | None
    rules: tuple[Compliance, ...]
    horizon: ExecutionHorizon | None

    @classmethod
    def of(cls, facts: RunFacts, frozen: FrozenRun) -> RunResources:
        """The instances `facts` already holds for `frozen`; nothing is loaded or read here."""
        strategy = frozen.strategy
        datamodel = frozen.datamodel
        return cls(
            run_identity=frozen.identity,
            strategy=(
                facts.component(strategy.config.component.component_id, load_strategy_model)
                if strategy is not None
                else None
            ),
            datamodel=(
                facts.component(datamodel.component_id, load_data_model)
                if datamodel is not None
                else None
            ),
            exchange=facts.exchange() if frozen.exchange is not None else None,
            rules=(
                tuple(
                    facts.component(str(ref.component_id), load_compliance)
                    for ref in strategy.compliance.rules
                )
                if strategy is not None
                else ()
            ),
            horizon=(
                facts.horizon() if strategy is not None and frozen.execution is not None else None
            ),
        )


@dataclass(frozen=True, slots=True)
class RunVerdict:
    """What one reading of a run declaration found.

    `failures` are the judgments' refusals (`JUDGMENT_CODES`); `blocked` the judgments that could
    not answer (`judgment.blocked`, the cause whole). `frozen` is the run ready to execute when the
    freeze completed; `refusal` is what the freeze raised when it did not -- a `VqaprError` with
    its own stage and retry precondition, or a bare `TypeError`/`ValueError` from a framework
    invariant, which the verbs render through `cli.run.preflight_refusal`.
    """

    failures: tuple[Failure, ...]
    blocked: tuple[Failure, ...]
    frozen: FrozenRun | None
    refusal: BaseException | None
    resources: RunResources | None = None

    @property
    def ok(self) -> bool:
        return not self.failures and not self.blocked and self.frozen is not None

    def require_ready(self) -> tuple[FrozenRun, RunResources]:
        """The frozen run and what was loaded for it, or the refusal `require_frozen` raises."""
        frozen = self.require_frozen()
        assert self.resources is not None
        return frozen, self.resources

    def require_frozen(self) -> FrozenRun:
        """The frozen run, or the refusal `run` raises: the judgments' first, then the freeze's.

        The rule `require_judged` used to hold (record `087`, no escape flag): a refused or blocked
        judgment refuses the run in `check`'s codes, with the one exception `run.output_stale`,
        which `run --force` is the repair for and so must not be refused by it. A run the
        judgments passed is then refused by the freeze's own error, unchanged.
        """
        refused = [failure for failure in self.failures if failure.code != RUN_OUTPUT_STALE]
        if refused or self.blocked:
            raise VqaprError(stage=Stage.CHECK, failures=[*refused, *self.blocked])
        if self.refusal is not None:
            raise self.refusal
        assert self.frozen is not None
        return self.frozen


def verify_run(workspace: Workspace, definition: RunDefinition) -> RunVerdict:
    """Read one run declaration once: every judgment answered, and the run frozen where it can be.

    The freeze is attempted whatever the judgments found, because `check` reports what the freeze
    refuses beside what the judgments refused (its `preflight` phase needs only the definition),
    and its refusal is kept as raised rather than rendered here.
    """
    if not isinstance(definition, RunDefinition):
        raise TypeError("definition must be a RunDefinition")
    facts = RunFacts(workspace, definition)
    found, blocked = judgments(definition, workspace, facts)
    frozen: FrozenRun | None = None
    refusal: BaseException | None = None
    try:
        frozen = _freeze(workspace, definition, facts)
    except Exception as error:  # rendered by the verb that asked; see the module docstring
        refusal = error
    resources = RunResources.of(facts, frozen) if frozen is not None else None
    return RunVerdict(tuple(found), tuple(blocked), frozen, refusal, resources)


__all__ = ["RunResources", "RunVerdict", "verify_run"]
