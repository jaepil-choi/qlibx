from __future__ import annotations

import ast
import inspect
import json
import pathlib

import pytest

import qlibx
from qlibx import alpha, ensemble, execution, reporting
from qlibx.agent import error_guidance, public_example, public_schema, task_guide
from qlibx.cli import dispatch, parser
from qlibx.documentation import ERROR_GUIDANCE, EXAMPLES
from qlibx.errors import QlibxError


def test_agent_help_and_schema_are_public_and_machine_readable(capsys) -> None:
    assert dispatch(parser().parse_args(["docs", "data"])) == 0
    assert dispatch(parser().parse_args(["schema", "dataset_registration"])) == 0
    output = capsys.readouterr().out
    first, second = output.split("}\n{")
    guide = json.loads(first + "}")["data"]
    assert any(command.startswith("qlibx data inspect") for command in guide["read_only"])
    assert guide["version"] == 1
    assert "ticker" in json.loads("{" + second)["dataset_registration"]["required"]


def test_installed_examples_are_discoverable_from_public_cli(capsys) -> None:
    assert dispatch(parser().parse_args(["examples", "exponential_decay"])) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["exponential_decay"]["format"] == "python"
    assert "ewm" in output["exponential_decay"]["content"]


def test_project_and_logical_dataset_guidance_is_installed(capsys) -> None:
    schema = public_schema("logical_dataset")
    assert "time_field" not in schema["required"]
    assert "availability_field" not in schema["required"]
    assert schema["defaults"]["availability_field"] == "available_at"
    assert dispatch(parser().parse_args(["docs", "project"])) == 0
    assert dispatch(parser().parse_args(["schema", "logical_dataset"])) == 0
    assert dispatch(parser().parse_args(["examples", "project_api"])) == 0
    output = capsys.readouterr().out
    assert "Project.load" in output
    assert "a separate event or observation time is optional" in output
    assert "ResearchCatalog.from_project" in output


def test_unknown_documentation_topic_is_structured_for_agents() -> None:
    with pytest.raises(QlibxError) as error:
        dispatch(parser().parse_args(["docs", "not-a-topic"]))
    assert error.value.code == "QLIBX_NOT_FOUND_DOCUMENTATION_TOPIC"
    assert "project" in error.value.context["available"]


def test_installed_error_recovery_is_code_specific_and_machine_readable(capsys) -> None:
    assert dispatch(parser().parse_args(["docs", "errors"])) == 0
    assert dispatch(parser().parse_args(["errors", "QLIBX_MISSING_REGISTRATION_MAPPING"])) == 0
    output = capsys.readouterr().out
    first, second = output.split("}\n{")
    guide = json.loads(first + "}")["errors"]
    lookup = json.loads("{" + second)
    assert guide["schema"] == "error_response"
    assert lookup["code"] == "QLIBX_MISSING_REGISTRATION_MAPPING"
    assert lookup["requires_user_confirmation"] is True
    assert "never guess" in lookup["recovery"]
    assert error_guidance("QLIBX_CONFLICT_SOURCE_CHANGED")["recovery"]


def test_agent_journey_guides_link_public_executable_examples() -> None:
    expected = {
        "alpha": "alpha_pipeline",
        "research": "research_workflow",
        "ensemble": "stored_ensemble",
        "execution": "signed_execution",
        "extension": "artifact_reporting",
    }
    for topic, example in expected.items():
        assert example in task_guide(topic)["examples"]
        content = public_example(example)["content"]
        compile(content, f"<{example}>", "exec")


def _documented_calls(content: str) -> list[ast.Call]:
    return [node for node in ast.walk(ast.parse(content)) if isinstance(node, ast.Call)]


def test_documented_examples_bind_against_real_public_signatures() -> None:
    """Compiling an example is not enough: its keywords must match the real signature."""
    public = {
        "run_strategy_execution": execution.run_strategy_execution,
        "run_signed_execution": execution.run_signed_execution,
        "combine_stored_weights": ensemble.combine_stored_weights,
        "apply_pipeline": alpha.apply_pipeline,
        "apply_budget": alpha.apply_budget,
        "register_operation": alpha.register_operation,
        "analyze_stored_run": reporting.analyze_stored_run,
        "render_report": reporting.render_report,
    }
    checked = 0
    for name, example in EXAMPLES.items():
        if example["format"] != "python":
            continue
        for call in _documented_calls(example["content"]):
            target = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if target not in public:
                continue
            parameters = inspect.signature(public[target]).parameters
            variadic = any(
                item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()
            )
            for keyword in call.keywords:
                assert keyword.arg is None or variadic or keyword.arg in parameters, (
                    f"example {name!r} passes unknown keyword {keyword.arg!r} to {target}()"
                )
            required = {
                item.name
                for item in parameters.values()
                if item.default is inspect.Parameter.empty
                and item.kind is inspect.Parameter.KEYWORD_ONLY
            }
            supplied = {keyword.arg for keyword in call.keywords}
            assert not required - supplied, (
                f"example {name!r} omits required keywords "
                f"{sorted(required - supplied)} for {target}()"
            )
            checked += 1
    assert checked >= 4


def test_installed_alpha_operations_are_discoverable_from_public_cli(capsys) -> None:
    assert dispatch(parser().parse_args(["alpha", "operations"])) == 0
    listed = json.loads(capsys.readouterr().out)
    names = {item["name"] for item in listed["operations"]}
    assert {"cross_sectional_rank", "linear_decay", "hump", "top_bottom"} <= names
    assert dispatch(parser().parse_args(["alpha", "operation", "linear_decay"])) == 0
    contract = json.loads(capsys.readouterr().out)["linear_decay"]
    assert contract["operation_id"] == "qlibx.alpha.linear_decay"
    assert contract["required_parameters"] == ["window"]
    assert contract["requirements"] == []
    assert dispatch(parser().parse_args(["alpha", "operation", "group_demean"])) == 0
    group_contract = json.loads(capsys.readouterr().out)["group_demean"]
    assert group_contract["requirements"][0]["requirement_id"] == "group_label"
    assert dispatch(parser().parse_args(["alpha", "plan", "group_demean"])) == 0
    group_plan = json.loads(capsys.readouterr().out)
    assert group_plan["ready"] is False
    assert group_plan["resolution"]["missing_requirements"] == ["group_label"]
    assert dispatch(parser().parse_args(["alpha", "budgets"])) == 0
    policies = {item["name"] for item in json.loads(capsys.readouterr().out)["policies"]}
    assert policies == {"fixed", "flexible"}


def test_every_registered_operation_is_documented_for_agents() -> None:
    required = set(public_schema("alpha_operation")["required"])
    for operation in alpha.list_operations():
        assert required <= set(operation), operation["name"]
        assert operation["summary"], operation["name"]


def test_public_requirement_and_plan_schemas_are_installed() -> None:
    requirement = public_schema("capability_requirement")
    plan = public_schema("capability_plan")
    assert {"requirement_id", "alternatives", "next_commands"} <= set(requirement["required"])
    assert plan["read_only"] is True
    assert "QLIBX_MISSING_CAPABILITY_REQUIREMENTS" in plan["error_equivalence"]


def _raised_error_codes() -> set[str]:
    """Collect every QlibxError code the package can raise, without importing behavior."""
    codes: set[str] = set()
    # Anchor on the package root, not a member module: a module may become a package.
    for path in pathlib.Path(qlibx.__file__).parent.rglob("*.py"):
        if "_vendor" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            is_error = isinstance(node, ast.Call) and getattr(node.func, "id", "") in {
                "QlibxError",
                "unknown_name",
            }
            if is_error and node.args and isinstance(node.args[0], ast.Constant):
                codes.add(node.args[0].value)
    return codes


def test_every_raised_error_code_has_installed_recovery_guidance() -> None:
    """`qlibx errors <code>` must answer for any code an agent can actually hit."""
    raised = _raised_error_codes()
    assert raised, "error-code scan found nothing; the AST walk is broken"
    assert not raised - set(ERROR_GUIDANCE), "raised but undocumented"
    assert not set(ERROR_GUIDANCE) - raised, "documented but unreachable"


# What the caller must do next. Codes are named for this, not for the module that noticed
# the failure -- a module-shaped prefix guarantees the same failure gets a new name in every
# module that can hit it, which is how the scheme this replaced grew to 144 codes.
ERROR_FAMILIES = (
    "NOT_FOUND",
    "MISSING",
    "INVALID",
    "BOUNDARY",
    "CONFLICT",
    "CORRUPT",
    "UNSUPPORTED",
)


def test_every_error_code_belongs_to_exactly_one_family() -> None:
    """The tree is only real if no code sits outside it, and none straddles two branches."""
    for code in sorted(ERROR_GUIDANCE):
        matched = [name for name in ERROR_FAMILIES if code.startswith(f"QLIBX_{name}_")]
        assert matched, f"{code} belongs to no family; pick the caller's next action"
        assert len(matched) == 1, f"{code} matches {matched}; families must not nest"


def test_no_two_codes_give_the_same_recovery() -> None:
    """Two codes with one recovery are one failure wearing two names.

    This is the check that would have caught the original drift: `provided_inputs` versus
    `available_inputs`, three spellings of "keep the path under its root", four of "use a
    positive limit". If a new code's recovery matches an existing one, they are the same
    code and `context` should carry whatever distinguishes them.
    """
    by_recovery: dict[str, list[str]] = {}
    for code, entry in ERROR_GUIDANCE.items():
        if "recovery" not in entry:
            continue  # inherits its family; nothing of its own to collide
        key = " ".join(str(entry["recovery"]).split()).casefold()
        by_recovery.setdefault(key, []).append(code)
    collisions = {
        recovery: sorted(codes) for recovery, codes in by_recovery.items() if len(codes) > 1
    }
    assert not collisions, f"codes sharing one recovery: {collisions}"


def test_unknown_name_lookups_share_one_structured_shape(capsys) -> None:
    """A failed named lookup answers the same way whatever registry it came from."""
    lookups = [
        (["alpha", "operation", "nope"], "QLIBX_NOT_FOUND_ALPHA_OPERATION"),
        (["extension", "contract", "nope"], "QLIBX_NOT_FOUND_EXTENSION_CONTRACT"),
        (["docs", "nope"], "QLIBX_NOT_FOUND_DOCUMENTATION_TOPIC"),
    ]
    for argv, code in lookups:
        with pytest.raises(QlibxError) as failure:
            dispatch(parser().parse_args(argv))
        assert failure.value.code == code
        assert set(failure.value.to_dict()) == {"code", "message", "action", "context"}
        assert failure.value.context["available"], code
        assert failure.value.context["requested"] == "nope"
