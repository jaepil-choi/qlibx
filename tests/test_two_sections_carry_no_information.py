"""`valuation_configs` and `monitoring_policies` are gone (record `144`, deletion campaign Step 3).

Each restated an agenda's own `role` under a second key, and a run names the agenda it values
with itself. Three things follow, asserted here:

- a `workspace.yaml` written by 0.3.0 still opens, and the next write drops the two sections --
  they carried no information, so nothing is lost and no meaning is kept in two spellings;
- a user's declaration document that still carries either section is refused by name, the
  way any unknown section is, so the author learns what to delete rather than what to add;
- a run whose valuation agenda is registered under role `valuation` is accepted with no other
  registration -- what the retired registry used to demand at preflight after registration had
  already accepted the run.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest
import yaml

from vqapr.domain.errors import VqaprError
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.public import register_run
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.workspace import Workspace

RETIRED_SECTIONS = """valuation_configs:
  daily-valuation:
    agenda_role: VALUATION
monitoring_policies:
  daily-valuation:
    agenda_role: MONITORING
"""


def _valuation_agenda(agenda_id: str = "daily-valuation") -> OperationAgenda:
    return OperationAgenda(
        agenda_id=agenda_id,
        role=OperationRole.VALUATION,
        timezone="Asia/Seoul",
        occurrences=(
            OperationOccurrence(
                f"{agenda_id}-2024-01-02",
                OperationRole.VALUATION,
                LocalInstantDeclaration(date(2024, 1, 2), time(15, 31), "Asia/Seoul", 0, "+09:00"),
            ),
        ),
        provenance="test",
    )


def test_a_workspace_written_by_0_3_0_opens_and_the_next_write_drops_the_two_sections(
    tmp_path: Path,
) -> None:
    workspace = Workspace.create(tmp_path)
    workspace.register_agenda(_valuation_agenda())
    # What 0.3.0 wrote beside that agenda: the same role, under two more keys.
    path = workspace.path
    path.write_text(path.read_text(encoding="utf-8") + RETIRED_SECTIONS, encoding="utf-8")
    assert "valuation_configs" in yaml.safe_load(path.read_text(encoding="utf-8"))

    reopened = Workspace.open(tmp_path)
    assert [agenda.agenda_id for agenda in reopened.agendas] == ["daily-valuation"]
    assert not hasattr(reopened, "valuation_configs")

    # An idempotent re-registration writes nothing, so the sections outlive it; the next write
    # that changes the document rewrites all of it, and they are gone.
    reopened.register_agenda(_valuation_agenda())
    assert "valuation_configs" in yaml.safe_load(path.read_text(encoding="utf-8"))
    reopened.register_agenda(_valuation_agenda(agenda_id="another-valuation"))
    rewritten = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "valuation_configs" not in rewritten
    assert "monitoring_policies" not in rewritten
    assert set(rewritten["agendas"]) == {"daily-valuation", "another-valuation"}


def test_a_declaration_that_still_carries_either_section_is_refused_by_name(tmp_path: Path) -> None:
    from vqapr.declarations import apply

    document = {
        "datasets": {},
        "valuation_configs": {"daily-valuation": {"agenda_id": "daily-valuation"}},
    }
    with pytest.raises(VqaprError) as refused:
        apply(document, tmp_path, base=tmp_path)
    failure = refused.value.as_dict()["failures"][0]
    assert failure["code"].endswith("unknown_section")
    assert "valuation_configs" in failure["observed"]
    assert "remove" in failure["fix"]


def test_register_run_is_a_public_name_and_the_two_registrars_are_not() -> None:
    import vqapr.public as public

    assert callable(register_run)
    assert not hasattr(public, "register_valuation_config")
    assert not hasattr(public, "register_monitoring_policy")
    assert "ValuationConfig" in public.__all__, "the run's own valuation binding keeps its type"
