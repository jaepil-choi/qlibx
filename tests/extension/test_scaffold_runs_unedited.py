"""AC-A3 / AC-M8: the emitted scaffold registers, checks and runs with ZERO edits.

This is the landing gate the plan calls out, and the reason Step 7 lands as one unit: a scaffold
that is short and ceremony-free but does not RUN has moved the problem rather than solved it. Two
prior attempts reverted after splitting the scaffold from the loader and the sample.

Driven through the real CLI by argv, not by calling the functions, because the claim is about what
an agent typing these commands experiences.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import vqapr.agent.sample.journey as journey
from vqapr.public import (
    OperationRole,
    StrategyConfig,
    Workspace,
    register_agenda,
    register_strategy_config,
)


def _cli(project_root: Path, *argv: str) -> tuple[int, dict]:
    # `PYTHONUTF8=1` and an explicit encoding: this host's default code page is cp949, and a
    # refusal carrying a non-ASCII character otherwise fails to decode and arrives as `None` --
    # a test failure that says nothing about the thing under test.
    result = subprocess.run(
        [sys.executable, "-m", "vqapr", "--project-root", str(project_root), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    try:
        return result.returncode, json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.returncode, {"raw": (result.stdout or result.stderr)[-400:]}


@pytest.mark.slow
def test_the_scaffold_registers_checks_and_runs_without_a_single_edit(tmp_path: Path) -> None:
    """The whole authoring contract, end to end, as an agent would drive it.

    The scaffold gets a FRESH id with its own agenda and config. Writing it under the sample's own
    strategy id is what produced the false verification this test exists to prevent: `install` had
    already registered a component there, so the registration was refused and the run executed the
    SAMPLE while the result was read as proof of the scaffold.
    Everything else -- the source, the class, the decision -- is the emitted file exactly as it
    was written, and the assertions below are about what that file does, not about its shape.
    """
    panel = journey.install(tmp_path)
    sessions = journey._sessions(panel)
    source = tmp_path / "scaffolded.py"

    code, created = _cli(
        tmp_path, "new", "strategy", "alpha",
        "--dataset", journey.DATASET_ID, "--lookback", "2", "--out", str(source),
    )
    assert code == 0, created
    body = source.read_text(encoding="utf-8")
    assert len(body.splitlines()) <= 40

    # Registered by naming a KIND, an ID and a .py -- no YAML wrapper around the component.
    code, registered = _cli(tmp_path, "register", "strategy", "alpha", str(source))
    assert code == 0, registered
    assert registered["component"]["object"], "the registration must name the class it found"

    # A FRESH id with its own agenda and its own config, so nothing of the sample's strategy is in
    # the path. Reusing the sample's id looks simpler and is worthless: `install` already
    # registered a component there, the re-registration is correctly refused as a conflict, and
    # the run then executes the SAMPLE while the test reports success. That mistake was made once
    # here already -- a green end-to-end result that proved nothing about the scaffold.
    assert (
        Path(str(Workspace.open(tmp_path).component("alpha").path)).name == source.name
    ), "the workspace is not holding the scaffold, so the run below would prove nothing"

    register_agenda(
        tmp_path,
        journey._agenda(
            "alpha-callback", OperationRole.STRATEGY_CALLBACK, journey.CALLBACK, sessions
        ),
    )
    register_strategy_config(
        tmp_path,
        StrategyConfig(
            component=Workspace.open(tmp_path).component("alpha"),
            agenda_id="alpha-callback",
            agenda_role=OperationRole.STRATEGY_CALLBACK,
        ),
    )

    # The run is a registration of its own (record 139), under a FRESH id for the same reason
    # the strategy has one: `install` already registered the sample's run, and executing that
    # would run the sample while the result was read as proof of the scaffold.
    runs = tmp_path / "runs.yaml"
    runs.write_text(
        yaml.safe_dump(
            {
                "runs": {
                    "scaffold": {
                        "strategies": {"alpha": {}},
                        "valuation": {"agenda_id": journey.VALUATION_AGENDA},
                        "monitoring": {"agenda_id": journey.MONITORING_AGENDA},
                        "instruments": list(panel.instruments),
                        "start": f"{sessions[2].isoformat()}T00:00:00{journey.OFFSET}",
                        "end": f"{sessions[-1].isoformat()}T23:59:59{journey.OFFSET}",
                        "exchange": journey.EXCHANGE_ID,
                        "execution_input": journey.EXECUTION_ID,
                        "initial_account": {
                            "mode": "LONG_ONLY",
                            "cash": str(journey.OPENING_CASH),
                            "positions": {},
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    code, registered_run = _cli(tmp_path, "register", str(runs))
    assert code == 0, registered_run
    assert registered_run["registered"]["runs"] == ["scaffold"]

    code, checked = _cli(tmp_path, "check", "scaffold")
    assert code == 0, checked
    assert checked["ok"] is True, checked["failures"]

    code, ran = _cli(tmp_path, "run", "scaffold")
    assert code == 0, ran
    assert ran["ok"] is True
    assert list(ran["strategies"]) == ["alpha"], "the run executed the scaffold and only it"
    scaffolded = ran["strategies"]["alpha"]

    # It TRADED. A scaffold that runs but never decides would satisfy `ok: true` while proving
    # nothing about the intent, execution or account-commit paths -- which is exactly what the old
    # Hold template did.
    assert scaffolded["occurrences"] > 0
    assert scaffolded["account_version"] > 0, (
        "the scaffold ran without ever committing a fill, so the authoring contract's decision "
        "path is unexercised"
    )
