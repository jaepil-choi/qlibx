"""`vqapr run <spec.yaml>` — freeze a declaration and execute it.

The spec is a projection of `RunDefinition`, not a second declaration language. Anything the
framework can derive — requirements, datasets, sources — is deliberately absent: restating it
here would let the file drift from the registered components, and preflight rejects that drift.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from vqapr.cli.envelope import success
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

_REQUIRED = ("strategy", "valuation", "instruments")


def _timestamp(value: object, *, name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an ISO-8601 timestamp string")
    return datetime.fromisoformat(value)


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
    return snapshot, AccountMode[str(declared["mode"]).upper()]


def definition_from_document(document: dict[str, Any], workspace: Workspace) -> RunDefinition:
    """Build a `RunDefinition` without re-implementing its invariants.

    Pairing rules (exchange with execution input, start with end, snapshot with mode) are
    enforced by `RunDefinition.__post_init__`, so this function only shapes values.
    """
    missing = [key for key in _REQUIRED if key not in document]
    if missing:
        raise ValueError(f"run spec is missing required keys: {', '.join(missing)}")
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
    parser.add_argument("spec", type=Path)


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    document = yaml.safe_load(args.spec.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TypeError("a run spec must be a YAML mapping")
    workspace = Workspace.open(project_root)
    frozen = preflight_run(project_root, definition_from_document(document, workspace))
    result = execute_run(project_root, frozen)
    return success(
        "run.complete",
        occurrences=len(result.occurrences),
        account_version=result.final_state.version,
    )
