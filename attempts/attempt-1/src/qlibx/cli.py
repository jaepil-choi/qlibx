"""qlibx command line interface.

Each subcommand binds its own handler with ``set_defaults(handler=...)``, so the parser
declaration and the behavior it triggers sit next to each other and ``dispatch`` stays a
lookup instead of a branching tree. Handlers return the value to print; printing, JSON
encoding, and structured error reporting stay in one place.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import qlib

from qlibx.alpha import (
    exposure_requirements,
    list_budget_policies,
    list_operations,
    operation_spec,
    plan_exposure,
    plan_operation,
)
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
from qlibx.strategy_manifest import (
    load_strategy_binding,
    load_strategy_manifest,
    plan_strategy_binding,
    resolve_strategy_inputs,
)

Handler = Callable[[argparse.Namespace], Any]

QLIB_SUPPORTED_VERSION = "0.9.7"


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


def _selected(name: str | None, one: Callable[[str], Any], all_names: Any, key: str) -> Any:
    """Render one named entry, or the sorted index when no name was given."""
    return {key: sorted(all_names)} if name is None else {name: one(name)}


# --------------------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------------------


def _project(args: argparse.Namespace) -> Any:
    project = Project.initialize(args.root) if args.action == "init" else Project.load(args.root)
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
            "qlib_adapter": (
                "supported" if qlib.__version__ == QLIB_SUPPORTED_VERSION else "incompatible"
            ),
            "pyqlib_version": qlib.__version__,
        },
    }
    if args.action == "status" and (project.paths.config / "data" / "base.yaml").exists():
        value["catalog"] = DataCatalog.from_project(project).describe()
    return value


def _data_requirements(args: argparse.Namespace) -> Any:
    return data_requirements(tuple(args.information_field))


def _data_discover(args: argparse.Namespace) -> Any:
    candidates = discover_data(
        Project.load(args.root),
        args.path,
        recursive=not args.no_recursive,
        limit=args.limit,
    )
    return {"read_only": True, "mutates": [], "candidates": candidates}


def _data_inspect(args: argparse.Namespace) -> Any:
    return inspect_data(
        Project.load(args.root),
        args.path,
        table=args.table,
        sample_rows=args.sample_rows,
    )


def _data_plan(args: argparse.Namespace) -> Any:
    return plan_registration(Project.load(args.root), args.dataset)


def _data_register(args: argparse.Namespace) -> Any:
    return register_dataset(Project.load(args.root), args.dataset)


def _data_catalog(args: argparse.Namespace) -> Any:
    return DataCatalog.from_project(Project.load(args.root)).describe()


def _data_preview(args: argparse.Namespace) -> Any:
    loader = ConfigDrivenDataLoader.from_project(Project.load(args.root))
    bounded = args.as_of is not None
    table = (
        loader.load_table(
            args.dataset,
            as_of=args.as_of,
            start=args.start,
            end=args.end,
            tickers=args.ticker,
            limit=args.limit,
        )
        if bounded
        else loader.load_full_history(
            args.dataset,
            reason="operator preview without a decision time",
            start=args.start,
            end=args.end,
            tickers=args.ticker,
            limit=args.limit,
        )
    )
    return {
        "dataset": args.dataset,
        "availability": {"bounded": bounded, "as_of": args.as_of},
        "rows": len(table),
        "columns": list(table.columns),
        "records": table.to_dict(orient="records"),
    }


def _qlib_status(_: argparse.Namespace) -> Any:
    return {"required": True, "module": qlib.__name__, "version": qlib.__version__}


def _qlib_requirements(args: argparse.Namespace) -> Any:
    return execution_profile_requirements(args.target_semantics)


def _qlib_plan(args: argparse.Namespace) -> Any:
    return plan_execution_profile(Project.load(args.root), args.config)


def _strategy_requirements(args: argparse.Namespace) -> Any:
    project = Project.load(args.root)
    return load_strategy_manifest(project, args.strategy).requirements()


def _strategy_plan(args: argparse.Namespace) -> Any:
    project = Project.load(args.root)
    manifest = load_strategy_manifest(project, args.strategy)
    binding = load_strategy_binding(project, args.binding) if args.binding else None
    return plan_strategy_binding(project, manifest, binding)


def _strategy_preview(args: argparse.Namespace) -> Any:
    project = Project.load(args.root)
    manifest = load_strategy_manifest(project, args.strategy)
    binding = load_strategy_binding(project, args.binding)
    resolved = resolve_strategy_inputs(
        project,
        manifest,
        binding,
        decision_time=args.decision_time,
        tickers=tuple(args.ticker) if args.ticker else None,
    )
    return {
        "strategy": {"id": manifest.strategy_id, "version": manifest.version},
        "binding_id": binding.binding_id,
        "decision_time": resolved.decision_time,
        "effective_config_id": resolved.effective_config_id,
        "inputs": {
            name: {
                "type": type(frame).__name__,
                "shape": list(frame.shape),
                "index_names": list(frame.index.names),
                "columns": list(map(str, frame.columns)),
                "start": frame.index.get_level_values(0).min() if len(frame) else None,
                "end": frame.index.get_level_values(0).max() if len(frame) else None,
            }
            for name, frame in resolved.inputs.items()
        },
        "read_only": True,
        "mutates": [],
    }


def _alpha_operations(_: argparse.Namespace) -> Any:
    return {"schema": "alpha_operation", "operations": list_operations()}


def _alpha_operation(args: argparse.Namespace) -> Any:
    return {args.name: operation_spec(args.name).describe()}


def _alpha_plan(args: argparse.Namespace) -> Any:
    return plan_operation(args.name, provided_inputs=args.provided_input)


def _alpha_exposure_requirements(_: argparse.Namespace) -> Any:
    return exposure_requirements()


def _alpha_exposure_plan(args: argparse.Namespace) -> Any:
    return plan_exposure(
        requested_metrics=args.metric,
        available_inputs=args.provided_input,
    )


def _alpha_budgets(_: argparse.Namespace) -> Any:
    return {"schema": "budget_policy", "policies": list_budget_policies()}


def _docs(args: argparse.Namespace) -> Any:
    if args.topic is None:
        return {"version": 1, "topics": sorted(TOPICS)}
    return {args.topic: task_guide(args.topic)}


def _schema(args: argparse.Namespace) -> Any:
    return _selected(args.name, public_schema, SCHEMAS, "schemas")


def _examples(args: argparse.Namespace) -> Any:
    return _selected(args.name, public_example, EXAMPLES, "examples")


def _errors(args: argparse.Namespace) -> Any:
    if args.code is None:
        return {"error_codes": sorted(ERROR_GUIDANCE)}
    return error_guidance(args.code)


def _extension_contracts(_: argparse.Namespace) -> Any:
    return {"contracts": list_extension_contracts()}


def _extension_contract(args: argparse.Namespace) -> Any:
    return {args.name: extension_contract(args.name)}


def _agent_skill(args: argparse.Namespace) -> Any:
    plan = plan_agent_skill(args.output, target=args.target)
    if args.force and not args.apply:
        raise QlibxError(
            "ONBOARDING",
            "--force has no effect during dry-run",
            expected="Review the dry-run, then use --apply --force.",
            requires_user_confirmation=True,
        )
    skill_path = apply_agent_skill(plan, force=args.force) if args.apply else None
    return {
        "target": plan.target,
        "root": plan.root,
        "package_version": plan.package_version,
        "instruction_schema_version": plan.instruction_schema_version,
        "applied": args.apply,
        "skill": skill_path,
        "preserves_unmanaged_files": plan.preserves_unmanaged_files,
        "files": [{"path": file.path, "action": file.action} for file in plan.files],
    }


def _agent_instruction(args: argparse.Namespace) -> Any:
    project = Project.load(args.root)
    if args.detect and not args.target:
        return {"read_only": True, "targets": detect_instruction_targets(project)}
    if not args.target:
        raise QlibxError(
            "ONBOARDING",
            "No instruction target was selected",
            expected="Use --detect, then select one or more --target paths.",
            requires_user_confirmation=True,
        )
    plans = tuple(
        remove_instruction(project, target) if args.remove else plan_instruction(project, target)
        for target in args.target
    )
    if args.apply:
        for plan in plans:
            apply_instruction(plan)
    return {
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


# --------------------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------------------


def _add(
    commands: argparse._SubParsersAction,
    name: str,
    handler: Handler,
) -> argparse.ArgumentParser:
    """Add one leaf command and bind the handler that implements it."""
    item = commands.add_parser(name)
    item.set_defaults(handler=handler)
    return item


def _with_root(item: argparse.ArgumentParser) -> argparse.ArgumentParser:
    item.add_argument("--root", default=".")
    return item


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="qlibx")
    commands = root.add_subparsers(dest="command", required=True)

    project_commands = commands.add_parser("project").add_subparsers(dest="action", required=True)
    for action in ("init", "status"):
        _with_root(_add(project_commands, action, _project))

    data_commands = commands.add_parser("data").add_subparsers(dest="action", required=True)
    requirements = _add(data_commands, "requirements", _data_requirements)
    requirements.add_argument("--information-field", action="append", default=[])
    discover = _with_root(_add(data_commands, "discover", _data_discover))
    discover.add_argument("--path")
    discover.add_argument("--no-recursive", action="store_true")
    discover.add_argument("--limit", type=int, default=100)
    inspect = _with_root(_add(data_commands, "inspect", _data_inspect))
    inspect.add_argument("--path", required=True)
    inspect.add_argument("--table")
    inspect.add_argument("--sample-rows", type=int, default=5)
    for action, handler in (("plan", _data_plan), ("register", _data_register)):
        item = _with_root(_add(data_commands, action, handler))
        item.add_argument("--dataset", required=True)
    _with_root(_add(data_commands, "catalog", _data_catalog))
    preview = _with_root(_add(data_commands, "preview", _data_preview))
    preview.add_argument("--dataset", required=True)
    preview.add_argument("--start")
    preview.add_argument("--end")
    preview.add_argument("--ticker", action="append")
    preview.add_argument("--as-of")
    preview.add_argument("--limit", type=int, default=5)

    qlib_commands = commands.add_parser("qlib").add_subparsers(dest="action", required=True)
    _add(qlib_commands, "status", _qlib_status)
    qlib_requirements = _add(qlib_commands, "requirements", _qlib_requirements)
    qlib_requirements.add_argument(
        "--target-semantics",
        choices=("long_only", "signed_weight", "enhanced_index"),
        default="long_only",
    )
    qlib_plan = _with_root(_add(qlib_commands, "plan", _qlib_plan))
    qlib_plan.add_argument("--config", default="config/qlibx/execution.yaml")

    strategy_commands = commands.add_parser("strategy").add_subparsers(dest="action", required=True)
    strategy_requirements = _with_root(
        _add(strategy_commands, "requirements", _strategy_requirements)
    )
    strategy_requirements.add_argument("--strategy", required=True)
    strategy_plan = _with_root(_add(strategy_commands, "plan", _strategy_plan))
    strategy_plan.add_argument("--strategy", required=True)
    strategy_plan.add_argument("--binding")
    strategy_preview = _with_root(_add(strategy_commands, "preview", _strategy_preview))
    strategy_preview.add_argument("--strategy", required=True)
    strategy_preview.add_argument("--binding", required=True)
    strategy_preview.add_argument("--decision-time", required=True)
    strategy_preview.add_argument("--ticker", action="append")

    agent_commands = commands.add_parser("agent").add_subparsers(dest="action", required=True)
    skill = _add(agent_commands, "skill", _agent_skill)
    skill.add_argument("--output", required=True)
    skill.add_argument("--target", choices=("codex", "claude", "generic"), default="generic")
    skill.add_argument("--apply", action="store_true")
    skill.add_argument("--force", action="store_true")
    instruction = _with_root(_add(agent_commands, "instruction", _agent_instruction))
    instruction.add_argument("--target", action="append", default=[])
    instruction.add_argument("--detect", action="store_true")
    instruction.add_argument("--apply", action="store_true")
    instruction.add_argument("--remove", action="store_true")

    alpha_commands = commands.add_parser("alpha").add_subparsers(dest="action", required=True)
    _add(alpha_commands, "operations", _alpha_operations)
    _add(alpha_commands, "operation", _alpha_operation).add_argument("name")
    alpha_plan = _add(alpha_commands, "plan", _alpha_plan)
    alpha_plan.add_argument("name")
    alpha_plan.add_argument("--provided-input", action="append", default=[])
    _add(alpha_commands, "exposure-requirements", _alpha_exposure_requirements)
    exposure_plan = _add(alpha_commands, "exposure-plan", _alpha_exposure_plan)
    exposure_plan.add_argument("--metric", action="append", required=True)
    exposure_plan.add_argument("--provided-input", action="append", default=[])
    _add(alpha_commands, "budgets", _alpha_budgets)

    extension_commands = commands.add_parser("extension").add_subparsers(
        dest="action", required=True
    )
    _add(extension_commands, "contracts", _extension_contracts)
    _add(extension_commands, "contract", _extension_contract).add_argument("name")

    docs = commands.add_parser("docs")
    docs.set_defaults(handler=_docs)
    docs.add_argument("topic", nargs="?")
    schema = commands.add_parser("schema")
    schema.set_defaults(handler=_schema)
    schema.add_argument("name", nargs="?")
    examples = commands.add_parser("examples")
    examples.set_defaults(handler=_examples)
    examples.add_argument("name", nargs="?")
    errors = commands.add_parser("errors")
    errors.set_defaults(handler=_errors)
    errors.add_argument("code", nargs="?")
    return root


def dispatch(args: argparse.Namespace) -> int:
    _print(args.handler(args))
    return 0


def _declare_output_encoding() -> None:
    """Emit UTF-8 whatever codec the caller's locale happens to name.

    ``print`` encodes with the locale codec, so the same command produced different bytes
    on a cp949 machine than on a UTF-8 one, and any character outside that codepage --- a
    project path under a non-ASCII user name, for instance --- raised UnicodeEncodeError
    from inside the CLI. An agent parsing this output cannot carry a per-machine encoding
    rule, so the encoding belongs to the protocol rather than to the environment.

    stdout is strict: a byte sequence the agent cannot decode is a broken response, not
    something to paper over. stderr is diagnostic and must never fail while reporting a
    failure, so it degrades instead.
    """
    for stream, errors in ((sys.stdout, "strict"), (sys.stderr, "backslashreplace")):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors=errors)


def main() -> None:
    _declare_output_encoding()
    try:
        raise SystemExit(dispatch(parser().parse_args()))
    except QlibxError as error:
        _print(error.to_dict())
        raise SystemExit(2) from error
