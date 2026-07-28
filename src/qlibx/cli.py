"""qlibx command line interface."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import qlib

from qlibx.alpha import list_budget_policies, list_operations, operation_spec
from qlibx.catalog import ConfigDrivenDataLoader, DataCatalog
from qlibx.discovery import discover_data, inspect_data
from qlibx.documentation import (
    ERROR_GUIDANCE,
    EXAMPLES,
    SCHEMAS,
    TOPICS,
    error_guidance,
    public_example,
    public_schema,
    task_guide,
)
from qlibx.errors import QlibxError
from qlibx.extensions import extension_contract, list_extension_contracts
from qlibx.onboarding import (
    apply_instruction,
    detect_instruction_targets,
    plan_instruction,
    remove_instruction,
)
from qlibx.profiles import execution_profile_requirements, plan_execution_profile
from qlibx.project import Project
from qlibx.registration import data_requirements, plan_registration, register_dataset
from qlibx.skill import apply_agent_skill, plan_agent_skill


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _print(value: Any) -> None:
    print(json.dumps(_jsonable(value), ensure_ascii=False, indent=2, default=str))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="qlibx")
    commands = root.add_subparsers(dest="command", required=True)
    project = commands.add_parser("project")
    project_commands = project.add_subparsers(dest="action", required=True)
    for action in ("init", "status"):
        item = project_commands.add_parser(action)
        item.add_argument("--root", default=".")

    data = commands.add_parser("data")
    data_commands = data.add_subparsers(dest="action", required=True)
    requirements = data_commands.add_parser("requirements")
    requirements.add_argument("--information-field", action="append", default=[])
    discover = data_commands.add_parser("discover")
    discover.add_argument("--root", default=".")
    discover.add_argument("--path")
    discover.add_argument("--no-recursive", action="store_true")
    discover.add_argument("--limit", type=int, default=100)
    inspect = data_commands.add_parser("inspect")
    inspect.add_argument("--root", default=".")
    inspect.add_argument("--path", required=True)
    inspect.add_argument("--table")
    inspect.add_argument("--sample-rows", type=int, default=5)
    for action in ("plan", "register"):
        item = data_commands.add_parser(action)
        item.add_argument("--root", default=".")
        item.add_argument("--dataset", required=True)
    catalog = data_commands.add_parser("catalog")
    catalog.add_argument("--root", default=".")
    preview = data_commands.add_parser("preview")
    preview.add_argument("--root", default=".")
    preview.add_argument("--dataset", required=True)
    preview.add_argument("--start")
    preview.add_argument("--end")
    preview.add_argument("--ticker", action="append")
    preview.add_argument("--as-of")
    preview.add_argument("--limit", type=int, default=5)

    qlib_command = commands.add_parser("qlib")
    qlib_commands = qlib_command.add_subparsers(dest="action", required=True)
    qlib_commands.add_parser("status")
    qlib_requirements = qlib_commands.add_parser("requirements")
    qlib_requirements.add_argument(
        "--target-semantics",
        choices=("long_only", "signed_weight", "enhanced_index"),
        default="long_only",
    )
    qlib_plan = qlib_commands.add_parser("plan")
    qlib_plan.add_argument("--root", default=".")
    qlib_plan.add_argument("--config", default="config/qlibx/execution.yaml")
    agent = commands.add_parser("agent")
    agent_commands = agent.add_subparsers(dest="action", required=True)
    skill = agent_commands.add_parser("skill")
    skill.add_argument("--output", required=True)
    skill.add_argument("--target", choices=("codex", "claude", "generic"), default="generic")
    skill.add_argument("--apply", action="store_true")
    skill.add_argument("--force", action="store_true")
    instruction = agent_commands.add_parser("instruction")
    instruction.add_argument("--root", default=".")
    instruction.add_argument("--target", action="append", default=[])
    instruction.add_argument("--detect", action="store_true")
    instruction.add_argument("--apply", action="store_true")
    instruction.add_argument("--remove", action="store_true")
    alpha = commands.add_parser("alpha")
    alpha_commands = alpha.add_subparsers(dest="action", required=True)
    alpha_commands.add_parser("operations")
    alpha_operation = alpha_commands.add_parser("operation")
    alpha_operation.add_argument("name")
    alpha_commands.add_parser("budgets")
    docs = commands.add_parser("docs")
    docs.add_argument("topic", nargs="?")
    schema = commands.add_parser("schema")
    schema.add_argument("name", nargs="?")
    examples = commands.add_parser("examples")
    examples.add_argument("name", nargs="?")
    errors = commands.add_parser("errors")
    errors.add_argument("code", nargs="?")
    extension = commands.add_parser("extension")
    extension_commands = extension.add_subparsers(dest="action", required=True)
    extension_commands.add_parser("contracts")
    extension_contract_parser = extension_commands.add_parser("contract")
    extension_contract_parser.add_argument("name")
    return root


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "project":
        project = (
            Project.initialize(args.root) if args.action == "init" else Project.load(args.root)
        )
        value = {
            "root": str(project.root),
            "config": str(project.paths.config),
            "generated_data": str(project.paths.generated_data),
            "state": str(project.paths.state),
            "research": str(project.paths.research),
            "extensions": str(project.paths.extensions),
            "compatibility": {
                "project_schema": "supported",
                "project_schema_version": 1,
                "qlib_adapter": ("supported" if qlib.__version__ == "0.9.7" else "incompatible"),
                "pyqlib_version": qlib.__version__,
            },
        }
        if args.action == "status" and (project.paths.config / "data" / "base.yaml").exists():
            value["catalog"] = DataCatalog.from_project(project).describe()
        _print(value)
    elif args.command == "data":
        if args.action == "requirements":
            _print(data_requirements(tuple(args.information_field)))
        elif args.action == "discover":
            project = Project.load(args.root)
            _print(
                {
                    "read_only": True,
                    "mutates": [],
                    "candidates": discover_data(
                        project,
                        args.path,
                        recursive=not args.no_recursive,
                        limit=args.limit,
                    ),
                }
            )
        elif args.action == "inspect":
            project = Project.load(args.root)
            _print(
                inspect_data(
                    project,
                    args.path,
                    table=args.table,
                    sample_rows=args.sample_rows,
                )
            )
        else:
            project = Project.load(args.root)
            if args.action == "plan":
                _print(plan_registration(project, args.dataset))
            elif args.action == "register":
                _print(register_dataset(project, args.dataset))
            elif args.action == "catalog":
                _print(DataCatalog.from_project(project).describe())
            else:
                loader = ConfigDrivenDataLoader.from_project(project)
                table = loader.load_table(
                    args.dataset,
                    start=args.start,
                    end=args.end,
                    tickers=args.ticker,
                    limit=args.limit,
                    as_of=args.as_of,
                )
                _print(
                    {
                        "dataset": args.dataset,
                        "rows": len(table),
                        "columns": list(table.columns),
                        "records": table.to_dict(orient="records"),
                    }
                )
    elif args.command == "qlib":
        if args.action == "status":
            _print({"required": True, "module": qlib.__name__, "version": qlib.__version__})
        elif args.action == "requirements":
            _print(execution_profile_requirements(args.target_semantics))
        else:
            _print(plan_execution_profile(Project.load(args.root), args.config))
    elif args.command == "alpha":
        if args.action == "operations":
            _print({"schema": "alpha_operation", "operations": list_operations()})
        elif args.action == "budgets":
            _print({"schema": "budget_policy", "policies": list_budget_policies()})
        else:
            _print({args.name: operation_spec(args.name).describe()})
    elif args.command == "docs":
        _print(
            {"version": 1, "topics": sorted(TOPICS)}
            if args.topic is None
            else {args.topic: task_guide(args.topic)}
        )
    elif args.command == "schema":
        _print(
            {"schemas": sorted(SCHEMAS)}
            if args.name is None
            else {args.name: public_schema(args.name)}
        )
    elif args.command == "examples":
        _print(
            {"examples": sorted(EXAMPLES)}
            if args.name is None
            else {args.name: public_example(args.name)}
        )
    elif args.command == "errors":
        _print(
            {"error_codes": sorted(ERROR_GUIDANCE)}
            if args.code is None
            else error_guidance(args.code)
        )
    elif args.command == "extension":
        _print(
            {"contracts": list_extension_contracts()}
            if args.action == "contracts"
            else {args.name: extension_contract(args.name)}
        )
    elif args.command == "agent" and args.action == "skill":
        plan = plan_agent_skill(args.output, target=args.target)
        if args.force and not args.apply:
            raise QlibxError(
                "QLIBX_SKILL_FORCE_WITHOUT_APPLY",
                "--force has no effect during dry-run",
                action="Review the dry-run, then use --apply --force.",
            )
        skill_path = apply_agent_skill(plan, force=args.force) if args.apply else None
        _print(
            {
                "target": plan.target,
                "root": plan.root,
                "package_version": plan.package_version,
                "instruction_schema_version": plan.instruction_schema_version,
                "applied": args.apply,
                "skill": skill_path,
                "preserves_unmanaged_files": plan.preserves_unmanaged_files,
                "files": [{"path": file.path, "action": file.action} for file in plan.files],
            }
        )
    else:
        project = Project.load(args.root)
        if args.detect and not args.target:
            _print({"read_only": True, "targets": detect_instruction_targets(project)})
            return 0
        if not args.target:
            raise QlibxError(
                "QLIBX_INSTRUCTION_TARGET_REQUIRED",
                "No instruction target was selected",
                action="Use --detect, then select one or more --target paths.",
            )
        plans = tuple(
            remove_instruction(project, target)
            if args.remove
            else plan_instruction(project, target)
            for target in args.target
        )
        if args.apply:
            for plan in plans:
                apply_instruction(plan)
        _print(
            {
                "applied": args.apply,
                "plans": [
                    {
                        "path": plan.path,
                        "action": plan.action,
                        "changed": plan.before != plan.after,
                        "before_digest": plan.before_digest,
                        "preview": plan.after,
                    }
                    for plan in plans
                ],
            }
        )
    return 0


def main() -> None:
    try:
        raise SystemExit(dispatch(parser().parse_args()))
    except QlibxError as error:
        _print(error.to_dict())
        raise SystemExit(2) from error
