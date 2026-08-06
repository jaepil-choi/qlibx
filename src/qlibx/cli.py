"""Thin command-line wrapper around the public project facade."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from qlibx.data import DatasetRegistration
from qlibx.errors import OperationOutcome
from qlibx.models import QlibxModel
from qlibx.onboarding import AgentTarget, OnboardingRequest
from qlibx.project import QlibxProject


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qlibx",
        description="PIT-safe quantitative research and execution engine",
    )
    commands = parser.add_subparsers(dest="command")

    project = commands.add_parser("project")
    project_commands = project.add_subparsers(dest="project_command")
    init = project_commands.add_parser("init")
    init.add_argument("root", nargs="?", default=".")
    init.add_argument("--apply", action="store_true")
    status = project_commands.add_parser("status")
    status.add_argument("root", nargs="?", default=".")
    onboard = project_commands.add_parser("onboard")
    onboard.add_argument("root", nargs="?", default=".")
    onboard.add_argument("--target", choices=[item.value for item in AgentTarget], required=True)
    onboard.add_argument("--custom-root")
    onboard.add_argument("--apply", action="store_true")

    dataset = commands.add_parser("dataset")
    dataset_commands = dataset.add_subparsers(dest="dataset_command")
    register = dataset_commands.add_parser("register")
    register.add_argument("root")
    register.add_argument("registration")

    artifact = commands.add_parser("artifact")
    artifact_commands = artifact.add_subparsers(dest="artifact_command")
    list_command = artifact_commands.add_parser("list")
    list_command.add_argument("root")
    list_command.add_argument("--include-failure", action="store_true")
    return parser


def jsonable(value: object) -> object:
    if isinstance(value, QlibxModel):
        return value.model_dump(mode="json")
    if isinstance(value, OperationOutcome):
        return {
            "status": value.status.value,
            "result": jsonable(value.result),
            "diagnostics": [jsonable(item) for item in value.diagnostics],
            "errors": [error.model_dump(mode="json") for error in value.errors],
        }
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return value


def emit(value: object) -> None:
    print(json.dumps(jsonable(value), ensure_ascii=False, indent=2, default=str))


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "project" and args.project_command == "init":
            emit(QlibxProject.init(args.root, apply=args.apply))
            return 0
        if args.command == "project" and args.project_command == "status":
            project = QlibxProject.open(args.root)
            emit(
                {
                    "root": str(project.root),
                    "config": project.config,
                    "datasets": project.registry_snapshot().datasets,
                    "artifacts": project.artifacts.list_envelopes(include_failure=True),
                }
            )
            return 0
        if args.command == "project" and args.project_command == "onboard":
            project = QlibxProject.open(args.root)
            request = OnboardingRequest(
                target=AgentTarget(args.target),
                custom_root=args.custom_root,
            )
            results = project.onboard((request,), apply=args.apply)
            emit(results)
            return 1 if any(result.error for result in results) else 0
        if args.command == "dataset" and args.dataset_command == "register":
            payload: Any = yaml.safe_load(Path(args.registration).read_text(encoding="utf-8"))
            registration = DatasetRegistration.model_validate_json(
                json.dumps(payload, ensure_ascii=False)
            )
            outcome = QlibxProject.open(args.root).register_dataset(registration)
            emit(outcome)
            return 0 if not outcome.errors else 1
        if args.command == "artifact" and args.artifact_command == "list":
            project = QlibxProject.open(args.root)
            emit(project.artifacts.list_envelopes(include_failure=args.include_failure))
            return 0
    except Exception as exc:
        emit({"status": "failed", "error": type(exc).__name__, "message": str(exc)})
        return 1
    parser.print_help()
    return 0


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))
