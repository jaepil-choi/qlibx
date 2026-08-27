"""Adversarial attacks on claim 2: `check` collects ALL independent failures, not just some.

Written against a version where two of these were BROKEN. They are fixed; the tests remain as the
pins that keep them fixed, and this docstring records what was actually wrong rather than the
speculation it started as.

1. **Six independent defects at once** -- the shipped suite only ever tried four. `check` reports
   every judgment that can answer and caps nothing.

2. **A judgment raising an unexpected exception type.** It used to propagate straight out of
   `check()`, crashing the one verb that exists in order never to crash. `_judgments` now catches
   bare `Exception`, records the judgment as `blocked` with its exception type, withholds
   `judgments` from `passed`, and returns `ok: false`. The other judgments still report.

3. **Three advertised codes that could never fire.** `check.dataset.unregistered`,
   `check.field.absent` and `check.lookback.uncovered` read requirements off the raw `ComponentRef`
   that `workspace.component()` returns -- which has no `requirements` attribute at all, so a
   `getattr(..., ())` fallback always won and the loop body never executed, for any spec against
   any workspace. `check` now LOADS the component, and all three fire; this file proves the first
   of them end to end below.

   Note on evidence: `refusal_codes.baseline.json`'s `coverage_gap` was originally cited as
   corroboration and does not corroborate anything of the sort. It is the set of codes not observed
   during one harness pass, and it also lists four codes this very file proves do fire. Reachability
   has to be demonstrated, not inferred from a coverage list.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from vqapr.cli import check as check_module
from vqapr.cli.check import check
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.extension.fingerprint import fingerprint_component
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.workspace import Workspace

_SPAN = (datetime(2024, 1, 2, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC))


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    space = Workspace.create(tmp_path)
    registration = DatasetRegistration.of(
        "prices",
        "prices-source",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
    ).with_span(*_SPAN)
    space.register_dataset(registration, SourceSpec.of("prices-source", "prepared/prices"))
    return tmp_path


def test_six_simultaneous_independent_defects_all_report(workspace: Path) -> None:
    """Not four -- the shipped suite's own maximum -- but six, chosen to be independent.

    1. universe absent (no instruments)
    2. period reversed (start >= end)
    3. weights mode conflict (long-only account holding a short)
    4. an execution ordering defect (an agenda occurrence at/after the fill's local_time)
    5. an unresolvable strategy component (declaration-phase VqaprError)
    6. everything above ALSO leaves preflight blocked, which must be reported as blocked, not
       silently absorbed into the failure count or dropped.

    If `check` silently capped collection anywhere -- at four, at "the first exception type it
    hits", or by short-circuiting once VqaprError classes start appearing -- this is the test that
    would show fewer than expected codes.
    """
    space = Workspace.open(workspace)
    late_agenda = OperationAgenda.from_occurrences(
        agenda_id="late-agenda",
        role=OperationRole.STRATEGY_CALLBACK,
        timezone="Asia/Seoul",
        occurrences=(
            OperationOccurrence(
                "o1",
                OperationRole.STRATEGY_CALLBACK,
                LocalInstantDeclaration(
                    datetime(2024, 1, 2).date(),
                    datetime(2024, 1, 2, 15, 30).time(),
                    "Asia/Seoul",
                    0,
                    "+09:00",
                ),
            ),
        ),
        provenance="qa fixture",
    )
    space.register_agenda(late_agenda)

    exec_dir = workspace / "exec"
    exec_dir.mkdir()
    (exec_dir / "placeholder").write_text("x", encoding="utf-8")
    Workspace.open(workspace).register_execution_input(
        ExecutionInputRegistration.of(
            "my-exec",
            ExecutionTableSpec(
                source=SourceSpec.of("exec-src", exec_dir),
                trade_at_field="trade_at",
                instrument_field="instrument",
                is_tradable_field="is_tradable",
                price_fields={"close": "close"},
            ),
            FillConvention(
                selector=FillSelector.NEXT_ELIGIBLE,
                local_time=datetime(2024, 1, 1, 15, 30).time(),
                timezone="Asia/Seoul",
                trade_price="close",
            ),
        )
    )

    document = {
        "strategy": {"agenda_id": "late-agenda", "component": "absent-component"},
        "valuation": {"agenda_id": "absent-val-agenda"},
        "instruments": [],  # defect 1
        "start": "2025-06-01T00:00:00+00:00",  # defect 2 (period reversed)
        "end": "2024-01-01T00:00:00+00:00",
        "exchange": "absent-exchange",
        "execution_input": "my-exec",
        "initial_account": {
            "mode": "LONG_ONLY",
            "cash": "1000",
            "positions": {"A": "-5"},  # defect 3
        },
    }
    spec_path = workspace / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(document), encoding="utf-8")

    body = check(spec_path, workspace)

    reported = {entry["code"] for entry in body["failures"]}
    assert reported == {
        "check.universe.absent",
        "check.period.uncovered",
        "check.execution.not_after_decision",
        "check.weights.mode_conflict",
        "workspace.component.lookup.missing",
    }, f"expected five independent refusals, got {sorted(reported)}"
    assert len(body["failures"]) == 5, (
        f"six-defect spec produced {len(body['failures'])} refusal(s), not five+blocked: "
        f"{[f['code'] for f in body['failures']]}"
    )
    assert any(entry["check"] == "preflight" for entry in body["blocked"]), (
        "preflight could never run because declaration failed, and must be reported as blocked"
    )


def test_an_unexpected_exception_type_inside_one_judgment_is_reported_as_blocked(
    workspace: Path,
) -> None:
    """An unexpected exception type inside one judgment is reported, not propagated.

        It used to escape `check()` entirely, crashing the verb whose own docstring promises it
        "returns the envelope body rather than raising, because a refusal here is the ANSWER to the
        question asked". `_judgments` now catches bare `Exception`: the judgment is recorded as
        `blocked` with its exception type, `judgments` is withheld from `passed`, and `ok` is
        false. A judgment that could not look is never reported as one that passed.
        """
    document = {
        "strategy": {"agenda_id": "absent", "component": "absent"},
        "valuation": {"agenda_id": "absent"},
        "instruments": [],
        "start": "2025-06-01T00:00:00+00:00",
        "end": "2024-01-01T00:00:00+00:00",
        "exchange": "absent",
        "execution_input": "absent",
        "initial_account": {"mode": "LONG_ONLY", "cash": "1000", "positions": {"A": "-5"}},
    }
    spec_path = workspace / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(document), encoding="utf-8")

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("a judgment's own dependency broke in a way check does not catch")

    original = check_module._judge_universe
    check_module._judge_universe = _boom
    try:
        body = check(spec_path, workspace)
    finally:
        check_module._judge_universe = original

    # Reported, not raised, and not silently swallowed either. A judgment that could not look did
    # not pass, so `ok` is false and the reason names the exception -- the third answer this
    # envelope already carries.
    assert body["ok"] is False
    assert "judgments" not in body["passed"], (
        "a judgment that could not run was reported as passed, so a spec nothing was proven "
        "about reads as clean and ready"
    )
    reasons = [entry["blocked_by"] for entry in body["blocked"] if entry["check"] == "universe"]
    assert reasons and "RuntimeError" in reasons[0], body["blocked"]

    # And the other judgments still reported, which is the property this verb exists for.
    assert {entry["code"] for entry in body["failures"]} >= {"check.period.uncovered"}


def test_the_three_dataset_codes_are_reachable_once_the_model_is_loaded(tmp_path: Path) -> None:
    """The three dataset judgments are reachable now that the component is loaded.

        They were dead: `workspace.component()` returns a `ComponentRef`, which has no
        `requirements` attribute, so `getattr(component, "requirements", ())` always took the
        fallback and the loop never ran. The codes sat in `CODES` looking implemented.

        The failure mode is invisible by nature -- a dead judgment reports nothing, which is
        exactly what a passing judgment reports -- so this pins the distinction directly.
        """
    space = Workspace.create(tmp_path)
    SPAN = (datetime(2024, 1, 2, tzinfo=UTC), datetime(2025, 6, 2, tzinfo=UTC))
    registration = DatasetRegistration.of(
        "prices",
        "prices-source",
        instrument_field="instrument",
        available_at="available_at",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
    ).with_span(*SPAN)
    space.register_dataset(registration, SourceSpec.of("prices-source", "prepared/prices"))

    source = tmp_path / "strategy.py"
    source.write_text(
        "from vqapr.public import StrategyModel, DataRequirement, RowsLookback, NoDecision\n\n"
        "class Strategy(StrategyModel):\n"
        "    def requirements(self):\n"
        "        return (\n"
        "            DataRequirement.of(\n"
        "                's', 'totally-unregistered-dataset', fields=('close',), "
        "lookback=RowsLookback(6)\n"
        "            ),\n"
        "        )\n"
        "    def on_occurrence(self, context):\n"
        "        return NoDecision('qa probe')\n",
        encoding="utf-8",
    )
    space.register_component(
        ComponentRef.of(
            "my-strat",
            ComponentKind.STRATEGY_MODEL,
            source,
            "Strategy",
            fingerprint=fingerprint_component(
                source, kind=ComponentKind.STRATEGY_MODEL, object_name="Strategy"
            ),
        )
    )

    document = {
        "strategy": {"agenda_id": "absent", "component": "my-strat"},
        "valuation": {"agenda_id": "absent"},
        "instruments": ["A"],
        "start": "2025-01-01T00:00:00+00:00",
        "end": "2025-02-01T00:00:00+00:00",
        "exchange": "absent",
        "execution_input": "absent",
        "initial_account": {"mode": "LONG_ONLY", "cash": "1000", "positions": {}},
    }
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(document), encoding="utf-8")

    body = check(spec_path, tmp_path)
    codes = {entry["code"] for entry in body["failures"]}
    # Fixed: `_judge_datasets_and_fields` now LOADS the component instead of reading a
    # `requirements` attribute off the `ComponentRef`, which never had one. The judgment reaches.
    assert "check.dataset.unregistered" in codes, (
        "the dataset judgment is dead again: it is reading the ComponentRef rather than the "
        "loaded model, so the loop body never runs and the code only looks implemented"
    )

    # Direct confirmation at the unit level: the raw ComponentRef workspace.component() returns
    # has no `requirements` attribute, so the getattr default always wins.
    ws = Workspace.open(tmp_path)
    ref = ws.component("my-strat")
    # The fact that made the old implementation dead, kept as the reason the fix is shaped the
    # way it is: a ComponentRef is an identity, a path and a fingerprint. Only the LOADED model
    # knows what it reads.
    assert not hasattr(ref, "requirements"), (
        "ComponentRef gained a requirements attribute; if that is deliberate, the judgment could "
        "read it directly, but until then loading the component is what makes it reachable"
    )
