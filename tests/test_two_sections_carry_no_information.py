"""The retired sections of `workspace.yaml` are read and dropped, never refused.

Record `144` (deletion campaign Step 3) retired `valuation_configs` and `monitoring_policies`:
each restated an agenda's own `role` under a second key. Record `148` retired `agendas` and
`strategy_configs` with them: a run declares its sessions and the one wall time `at` itself, every
strategy is called on every session, and the agenda preflight runs on is derived from the run. Four
sections, one rule, asserted here:

- a `workspace.yaml` written by 0.3.0 still opens, and the next write that changes the document
  drops all four -- what they said is either restated by the run or was never information;
- a user's declaration document that still carries any of them is refused by name, the way any
  unknown section is, so the author learns what to delete rather than what to add;
- a 0.3.0 `runs:` entry, which named agendas instead of declaring its clock, is refused at open
  naming the run, because a run without `timezone`, `at` and sessions cannot be executed;
- `register_run` is the public registrar and the retired registrars and types are gone from the
  surface.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from vqapr.domain.errors import VqaprError
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.public import AccountMode, AccountSnapshot, RunDefinition, StrategyEntry, register_run
from vqapr.workspace import Workspace

RETIRED_SECTIONS = """valuation_configs:
  daily-valuation:
    agenda_role: VALUATION
monitoring_policies:
  daily-valuation:
    agenda_role: MONITORING
agendas:
  daily-valuation:
    role: VALUATION
    timezone: Asia/Seoul
    provenance: test
    occurrences:
    - occurrence_id: daily-valuation-2024-01-02
      date: '2024-01-02'
      time: '15:31:00'
      fold: 0
      offset: '+09:00'
strategy_configs:
  alpha:
    agenda_id: daily-valuation
    agenda_role: STRATEGY_CALLBACK
"""
RETIRED_KEYS = ("valuation_configs", "monitoring_policies", "agendas", "strategy_configs")


def _strategy(name: str, root: Path) -> ComponentRef:
    return ComponentRef.of(
        name, ComponentKind.STRATEGY_MODEL, root / f"{name}.py", "Strategy", fingerprint="a" * 64
    )


def _run(run_id: str, strategy: str) -> RunDefinition:
    return RunDefinition(
        run_id=run_id,
        strategies=(StrategyEntry(strategy),),
        instruments=("A",),
        timezone="Asia/Seoul",
        at=time(15, 29),
        sessions=(date(2024, 1, 2),),
        initial_account_snapshot=AccountSnapshot(0, Decimal("1000"), {}),
        initial_account_mode=AccountMode.LONG_ONLY,
    )


def test_a_workspace_written_by_0_3_0_opens_and_the_next_write_drops_the_four_sections(
    tmp_path: Path,
) -> None:
    workspace = Workspace.create(tmp_path)
    with Workspace.transaction(workspace) as t:
        t.register_component(_strategy("alpha", tmp_path))
    # What 0.3.0 wrote beside that component: an agenda, the strategy's binding to it, and the
    # agenda's role restated twice more.
    path = workspace.path
    path.write_text(path.read_text(encoding="utf-8") + RETIRED_SECTIONS, encoding="utf-8")
    assert set(RETIRED_KEYS) <= set(yaml.safe_load(path.read_text(encoding="utf-8")))

    reopened = Workspace.open(tmp_path)
    assert [str(ref.component_id) for ref in reopened.components] == ["alpha"]
    for retired in ("agendas", "strategy_configs", "valuation_configs", "register_agenda"):
        assert not hasattr(reopened, retired), f"the workspace still exposes {retired}"

    # An idempotent re-registration writes nothing, so the sections outlive it; the next write
    # that changes the document rewrites all of it, and they are gone.
    with Workspace.transaction(reopened) as t:
        assert t.register_component(_strategy("alpha", tmp_path)) is False
    assert set(RETIRED_KEYS) <= set(yaml.safe_load(path.read_text(encoding="utf-8")))
    with Workspace.transaction(reopened) as t:
        t.register_run(_run("daily", "alpha"))
    rewritten = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert not set(RETIRED_KEYS) & set(rewritten), sorted(set(RETIRED_KEYS) & set(rewritten))
    assert set(rewritten["runs"]) == {"daily"}
    assert Workspace.open(tmp_path).run_definition("daily") == _run("daily", "alpha")


def test_a_0_3_0_run_that_named_agendas_is_refused_at_open_naming_the_run(tmp_path: Path) -> None:
    """A run without its clock cannot be executed, so it is refused where it is read.

    The four sections are dropped silently because nothing in them is needed; a run entry is
    different, because `timezone`, `at` and the sessions are what `vqapr run` now needs from it,
    and 0.3.0 did not write them.
    """
    workspace = Workspace.create(tmp_path)
    with Workspace.transaction(workspace) as t:
        t.register_component(_strategy("alpha", tmp_path))
    path = workspace.path
    path.write_text(
        path.read_text(encoding="utf-8")
        + "runs:\n"
        + "  krx-2024:\n"
        + "    instruments: [A]\n"
        + "    start: '2024-01-02T00:00:00+09:00'\n"
        + "    end: '2024-01-03T00:00:00+09:00'\n"
        + "    valuation: {agenda_id: daily-valuation}\n"
        + "    exchange: null\n"
        + "    execution_input: null\n"
        + "    initial_account: null\n"
        + "    strategies: {alpha: {}}\n",
        encoding="utf-8",
    )

    with pytest.raises(VqaprError) as refused:
        Workspace.open(tmp_path)
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"] == "workspace.open.invalid"
    assert "krx-2024" in failure["observed"], failure["observed"]


@pytest.mark.parametrize("section", RETIRED_KEYS)
def test_a_declaration_that_still_carries_a_retired_section_is_refused_by_name(
    tmp_path: Path, section: str
) -> None:
    from vqapr.declarations import SECTIONS, apply

    assert section not in SECTIONS
    document = {"datasets": {}, section: {"daily": {"agenda_id": "daily"}}}
    with pytest.raises(VqaprError) as refused:
        apply(document, tmp_path, base=tmp_path)
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"].endswith("unknown_section")
    assert section in failure["observed"]
    assert "remove" in failure["fix"]


def test_register_run_is_a_public_name_and_the_retired_registrars_and_types_are_not() -> None:
    import vqapr.public as public

    assert callable(register_run)
    for retired in (
        "register_agenda",
        "register_strategy_config",
        "register_valuation_config",
        "register_monitoring_policy",
        "OperationAgenda",
        "StrategyConfig",
        "ValuationConfig",
        "MonitoringPolicy",
    ):
        assert not hasattr(public, retired), f"vqapr.public still exposes {retired}"
        assert retired not in public.__all__
