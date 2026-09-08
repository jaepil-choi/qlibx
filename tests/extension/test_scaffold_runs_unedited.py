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

import tests.sample.journey as journey
from vqapr.public import Workspace


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

    The scaffold gets a FRESH id and a FRESH run. Writing it under the sample's own strategy id
    is what produced the false verification this test exists to prevent: `install` had already
    registered a component there, so the registration was refused and the run executed the
    SAMPLE while the result was read as proof of the scaffold.
    Everything else -- the source, the class, the decision -- is the emitted file exactly as it
    was written, and the assertions below are about what that file does, not about its shape.
    """
    panel = journey.install(tmp_path)
    sessions = journey.sessions(panel)
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

    # A FRESH id, so nothing of the sample's strategy is in the path. Reusing the sample's id
    # looks simpler and is worthless: `install` already registered a component there, the
    # re-registration is correctly refused as a conflict, and the run then executes the SAMPLE
    # while the test reports success. That mistake was made once here already -- a green
    # end-to-end result that proved nothing about the scaffold.
    assert (
        Path(str(Workspace.open(tmp_path).component("alpha").path)).name == source.name
    ), "the workspace is not holding the scaffold, so the run below would prove nothing"

    # The run is a registration of its own (record 139), under a FRESH id for the same reason
    # the strategy has one: `install` already registered the sample's run, and executing that
    # would run the sample while the result was read as proof of the scaffold. It declares its
    # own sessions and wall time (record 148): every day the sample panel has, at the callback,
    # sliced to the period below -- no agenda or config is registered beside it.
    runs = tmp_path / "runs.yaml"
    runs.write_text(
        yaml.safe_dump(
            {
                "runs": {
                    "scaffold": {
                        "strategies": {"alpha": {}},
                        "sessions_from": journey.DATASET_ID,
                        "timezone": journey.VENUE,
                        "at": journey.CALLBACK.strftime("%H:%M"),
                        "instruments": list(panel.instruments),
                        "start": f"{sessions[2].isoformat()}T00:00:00{journey.OFFSET}",
                        "end": f"{sessions[-1].isoformat()}T23:59:59{journey.OFFSET}",
                        "exchange": journey.EXCHANGE_ID,
                        "execution": {
                            "dataset": journey.EXECUTION_ID,
                            "fill": {
                                "selector": "same_day",
                                "at": "15:30",
                                "timezone": journey.VENUE,
                                "trade_price": "close",
                            },
                        },
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


def test_the_datamodel_scaffold_registers_its_run_without_a_single_edit(tmp_path: Path) -> None:
    """The `runs:` block `vqapr new datamodel` emits is one `register` takes as written.

    Record 148: the declaration carries the run that computes the model, so registering the file
    registers a datamodel run under `<id>-run` -- a run `list runs` knows by kind and `check`
    reaches all the way through. What it does NOT prove is that the run computes anything: the
    instruments are placeholders the reader fills, and registration does not validate a universe.
    """
    journey.install(tmp_path)
    source = tmp_path / "scaffolded_model.py"

    code, created = _cli(
        tmp_path, "new", "datamodel", "signal",
        "--dataset", journey.DATASET_ID, "--lookback", "2", "--out", str(source),
    )
    assert code == 0, created

    code, registered = _cli(tmp_path, "register", created["declaration"])
    assert code == 0, registered
    assert registered["registered"]["components"] == ["signal"]
    assert registered["registered"]["runs"] == ["signal-run"]

    code, runs = _cli(tmp_path, "list", "runs")
    assert code == 0, runs
    row = next(row for row in runs["items"] if row["run_id"] == "signal-run")
    assert row["kind"] == "datamodel"

    # The emitted block is a run `check` can judge as written: every phase answers, and none of
    # them refuses the declaration's SHAPE. (The placeholder instruments are not a judgment
    # today; whether an instrument the sessions dataset never holds should be one is open.)
    code, checked = _cli(tmp_path, "check", "signal-run")
    assert not any(
        failure["code"] == "unhandled" for failure in checked.get("failures", [])
    ), checked
    assert checked["checked"] == ["workspace", "run", "judgments", "preflight"]
    assert not any(
        failure["code"] == "run.declaration_invalid" for failure in checked.get("failures", [])
    ), "the scaffold's shape was refused, not its placeholders"


@pytest.mark.slow
def test_the_datamodel_scaffold_computes_a_dataset_without_a_single_edit(tmp_path: Path) -> None:
    """With real instruments in place of the placeholders, the emitted `compute()` runs to a
    registered dataset.

    Record `173` made a DataModel's output types declarable-only, and the scaffold's trailing
    return was a `Decimal`: the unedited file was refused at its first session as
    `datamodel.output.field_type` (found by the 0.7.0 scenario trace). The scaffold crosses back
    to `float` now; this test is what keeps it that way.
    """
    panel = journey.install(tmp_path)
    source = tmp_path / "scaffolded_model.py"

    code, created = _cli(
        tmp_path, "new", "datamodel", "signal",
        "--dataset", journey.DATASET_ID, "--lookback", "2", "--out", str(source),
    )
    assert code == 0, created
    declaration = Path(created["declaration"])
    text = declaration.read_text(encoding="utf-8")
    first, second = panel.instruments[:2]
    text = text.replace("    - INSTRUMENT_A", f"    - {first}").replace(
        "    - INSTRUMENT_B", f"    - {second}"
    )
    declaration.write_text(text, encoding="utf-8")

    code, registered = _cli(tmp_path, "register", str(declaration))
    assert code == 0, registered

    code, ran = _cli(tmp_path, "run", "signal-run")
    assert code == 0, ran
    assert ran["ok"] is True, ran

    code, datasets = _cli(tmp_path, "list", "datasets")
    assert code == 0, datasets
    assert any(row["dataset_id"] == "signal-values" for row in datasets["items"]), datasets
