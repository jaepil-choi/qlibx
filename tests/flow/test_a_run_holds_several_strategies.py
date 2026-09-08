"""A run is configuration and holds several strategies; each strategy is its own output.

Record `139` (campaign Step 7); design `docs/design/the-panel-the-surface-and-the-run.md` §4;
architecture §17.3-17.6. The acceptance criteria from the campaign, verbatim: one run holding
three strategies, run with `--jobs 3`, produces **three NAV series**; `run.json` answers what
`record.json` could not -- which `.py` ran, the strategy's own fingerprint, which execution
convention, which instruments; counting `ou-ff5@*` directories is the number of tweaks.

The run here is the shipped sample journey with the sample strategy registered under three ids,
because a record is only worth freezing if a real run produced it.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

import tests.sample.journey as journey
from vqapr.flow.record import (
    RUN_FILENAME,
    STRATEGY_FILENAME,
    RunRecordConflict,
    RunRecordExists,
    read_run_record,
    read_strategy_record,
    read_typed_table,
    strategy_refs,
)
from vqapr.public import (
    StrategyEntry,
    Workspace,
    preflight_run,
    register_run,
    register_strategy_model,
)
from vqapr.public import run as execute_run

STRATEGIES = ("ou-k0", "ou-pca5", "ou-ff5")


def _project(tmp_path: Path) -> tuple[Path, Path]:
    """The sample workspace, plus the sample strategy registered three more times under new ids."""
    project = tmp_path / "project"
    project.mkdir()
    panel = journey.install(project)
    # No per-strategy binding to register (record `148`): every strategy of the run is called
    # on the run's sessions at its `at`, so registering the model is all a strategy needs.
    for name in STRATEGIES:
        register_strategy_model(project, name, journey.STRATEGY_SOURCE, "SampleReversal5d")
    definition = journey.definition(panel, run_id='comparison').replace(
                     strategies=tuple(StrategyEntry(name) for name in STRATEGIES),
                 )
    register_run(project, definition)
    return project, tmp_path / "store"


def test_preflight_freezes_one_run_layer_and_one_layer_per_strategy(tmp_path: Path) -> None:
    project, _ = _project(tmp_path)
    workspace = Workspace.open(project)

    frozen = preflight_run(project, workspace.run_definition("comparison"))

    assert [layer.component_id for layer in frozen.strategies] == list(STRATEGIES)
    assert len({layer.identity for layer in frozen.strategies}) == 3, (
        "three components, three strategy identities"
    )
    again = preflight_run(project, workspace.run_definition("comparison"))
    assert frozen.identity == again.identity
    # The strategies share the run layer: one universe, one period, one venue, one panel set.
    assert frozen.requirements, "the union of what the strategies read"
    # Same run, fewer strategies. The run id stays: since record `148` the strategy's agenda is
    # derived from the run (`<run_id>.sessions`), so a strategy's identity folds the run it is
    # asked in, and only the OTHER strategies of that run are what must not change it.
    only = workspace.run_definition('comparison').replace(strategies=(StrategyEntry('ou-k0'),))
    alone = preflight_run(project, only).strategy("ou-k0")
    assert alone.identity == frozen.strategy("ou-k0").identity, (
        "a strategy's identity is its own: adding strategies to the run does not change it"
    )


def test_a_strategy_the_run_names_without_a_registration_is_refused_by_name(tmp_path: Path) -> None:
    """A registered model is all a strategy needs (record `148`); an unregistered one is refused.

    Before `148` a strategy also needed a registered binding to an agenda, and a run naming a
    model without one was refused. The binding is derived now, so the only thing a run can name
    that does not exist is the component itself -- and a run that merely names a registered
    model registers cleanly.
    """
    project, _ = _project(tmp_path)
    register_strategy_model(project, "registered-only", journey.STRATEGY_SOURCE, "SampleReversal5d")
    workspace = Workspace.open(project)
    named = workspace.run_definition('comparison').replace(
                run_id='x',
                strategies=(StrategyEntry('registered-only'),),
            )
    register_run(project, named)
    assert Workspace.open(project).run_definition("x").strategies == named.strategies

    from vqapr.domain.errors import VqaprError

    unregistered = named.replace(run_id='y', strategies=(StrategyEntry('unregistered'),))
    with pytest.raises(VqaprError) as refused:
        register_run(project, unregistered)
    assert "'unregistered'" in refused.value.as_dict()["failures"][0]["requirement"]


@pytest.mark.slow
def test_three_strategies_in_one_run_leave_three_nav_series(tmp_path: Path) -> None:
    """The acceptance criterion: one run, three strategies, three NAV series, two records."""
    project, store = _project(tmp_path)
    workspace = Workspace.open(project)
    frozen = preflight_run(project, workspace.run_definition("comparison"))

    outcome = execute_run(project, frozen, store_root=store)

    assert set(outcome.results) == set(STRATEGIES)
    refs = strategy_refs(store, "comparison")
    assert [ref.rsplit("@", 1)[0] for ref in refs] == sorted(STRATEGIES)
    navs = {}
    for ref in refs:
        rows = [
            row
            for row in read_typed_table(store, "comparison", "vqapr.account", ref)
            if row["instrument"] == "_ACCOUNT"
        ]
        assert rows and all(isinstance(row["nav"], Decimal) for row in rows)
        navs[ref] = [row["nav"] for row in rows]
    assert len(navs) == 3, "each strategy has its own account and its own NAV series"

    # run.json: what record.json could not answer (architecture §17.3.1).
    run_record = read_run_record(store, "comparison")
    assert run_record["instruments"] == list(frozen.instruments)
    assert run_record["execution_input"]["execution_input_id"] == journey.EXECUTION_ID
    assert run_record["execution_input"]["fill"]["selector"], "which convention (034)"
    assert run_record["exchange"]["component_id"] == journey.EXCHANGE_ID
    assert [entry["component_id"] for entry in run_record["strategies"]] == list(STRATEGIES)
    assert all(entry["source_digest"] for entry in run_record["datasets"]), "A7"
    # strategy.json: which .py ran and the strategy's OWN fingerprint (§17.3.2).
    record = read_strategy_record(store, "comparison", refs[0])
    assert record["component"]["path"].endswith(".py")
    assert record["fingerprint"] == record["component"]["fingerprint"]
    assert record["source_digest"][record["strategy_id"]] == record["fingerprint"], (
        "as loaded equals as registered when nothing was edited"
    )
    assert record["contract"]["accepted_intents"] > 0
    assert outcome.records[record["strategy_id"]]["strategy_ref"] == refs[0]


@pytest.mark.slow
def test_jobs_runs_the_strategies_in_processes_and_the_records_come_back(tmp_path: Path) -> None:
    project, store = _project(tmp_path)
    workspace = Workspace.open(project)
    frozen = preflight_run(project, workspace.run_definition("comparison"))

    outcome = execute_run(project, frozen, store_root=store, jobs=3)

    assert outcome.results == {}, "a worker's result does not cross the process boundary"
    assert set(outcome.records) == set(STRATEGIES)
    assert len(strategy_refs(store, "comparison")) == 3
    assert all(record["account"]["version"] > 0 for record in outcome.records.values())


def test_a_strategy_record_is_content_addressed(tmp_path: Path) -> None:
    """Same run + same fingerprint = same directory; a tweak lands beside it; data unchanged."""
    project, store = _project(tmp_path)
    workspace = Workspace.open(project)
    frozen = preflight_run(project, workspace.run_definition("comparison"))

    execute_run(project, frozen, store_root=store, strategies=["ou-k0"])
    (ref,) = strategy_refs(store, "comparison")
    assert ref.startswith("ou-k0@")

    # The same strategy again is a retry or an overwrite, and the reader says which in one flag.
    with pytest.raises(RunRecordExists):
        execute_run(project, frozen, store_root=store, strategies=["ou-k0"])
    execute_run(project, frozen, store_root=store, strategies=["ou-k0"], replace_record=True)
    assert strategy_refs(store, "comparison") == (ref,)

    # A tweak -- an edited file re-registered under the same id -- is a new fingerprint, a new
    # directory beside the old one.
    tweaked = tmp_path / "ou_k0_tweaked.py"
    tweaked.write_text(
        journey.STRATEGY_SOURCE.read_text(encoding="utf-8") + "\n# tweaked\n", encoding="utf-8"
    )
    register_strategy_model(project, "ou-k0", tweaked, "SampleReversal5d")
    workspace = Workspace.open(project)
    tweaked = preflight_run(project, workspace.run_definition("comparison"))
    execute_run(project, tweaked, store_root=store, strategies=["ou-k0"])
    refs = strategy_refs(store, "comparison")
    assert len(refs) == 2 and all(r.startswith("ou-k0@") for r in refs), (
        "counting `ou-k0@*` is the number of tweaks (§17.4)"
    )


def test_a_changed_run_under_an_old_id_is_refused_naming_both_digests(tmp_path: Path) -> None:
    project, store = _project(tmp_path)
    workspace = Workspace.open(project)
    frozen = preflight_run(project, workspace.run_definition("comparison"))
    execute_run(project, frozen, store_root=store, strategies=["ou-k0"])

    changed = workspace.run_definition('comparison').replace(instruments=frozen.instruments[:1])
    with pytest.raises(RunRecordConflict) as refused:
        execute_run(
            project, preflight_run(project, changed), store_root=store, strategies=["ou-k0"]
        )
    assert "rm run comparison" in str(refused.value)
    assert (store / "runs" / "comparison" / RUN_FILENAME).is_file(), "the old run.json stands"


def test_a_killed_strategy_leaves_rows_and_no_record_and_run_json_stands(tmp_path: Path) -> None:
    """A run killed midway still says what it attempted; the strategy that died is not listed."""
    project, store = _project(tmp_path)
    workspace = Workspace.open(project)
    frozen = preflight_run(project, workspace.run_definition("comparison"))

    import vqapr.flow.orchestration as orchestration

    original = orchestration.freeze_strategy_record

    def die(*args, **kwargs):
        raise KeyboardInterrupt

    orchestration.freeze_strategy_record = die
    try:
        with pytest.raises(KeyboardInterrupt):
            execute_run(project, frozen, store_root=store, strategies=["ou-k0"])
    finally:
        orchestration.freeze_strategy_record = original

    run_json = json.loads((store / "runs" / "comparison" / RUN_FILENAME).read_text("utf-8"))
    assert [entry["component_id"] for entry in run_json["strategies"]] == list(STRATEGIES)
    directory = store / "runs" / "comparison" / "strategies"
    (killed,) = [child for child in directory.iterdir()]
    assert (killed / "tables").is_dir() and not (killed / STRATEGY_FILENAME).exists()
    assert strategy_refs(store, "comparison") == ()
