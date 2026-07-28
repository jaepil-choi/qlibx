from __future__ import annotations

import ast
import inspect
import json

import pytest

from qlibx import alpha, ensemble, execution, reporting
from qlibx.agent import error_guidance, public_example, public_schema, task_guide
from qlibx.cli import dispatch, parser
from qlibx.documentation import EXAMPLES
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
    assert error.value.code == "QLIBX_DOCUMENTATION_TOPIC_UNKNOWN"
    assert "project" in error.value.context["available"]


def test_installed_error_recovery_is_code_specific_and_machine_readable(capsys) -> None:
    assert dispatch(parser().parse_args(["docs", "errors"])) == 0
    assert dispatch(parser().parse_args(["errors", "QLIBX_REGISTRATION_MAPPING_MISSING"])) == 0
    output = capsys.readouterr().out
    first, second = output.split("}\n{")
    guide = json.loads(first + "}")["errors"]
    lookup = json.loads("{" + second)
    assert guide["schema"] == "error_response"
    assert lookup["code"] == "QLIBX_REGISTRATION_MAPPING_MISSING"
    assert lookup["requires_user_confirmation"] is True
    assert "never guess" in lookup["recovery"]
    assert error_guidance("QLIBX_SOURCE_CHANGED_DURING_REGISTRATION")["recovery"]


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
    assert dispatch(parser().parse_args(["alpha", "budgets"])) == 0
    policies = {item["name"] for item in json.loads(capsys.readouterr().out)["policies"]}
    assert policies == {"fixed", "flexible"}


def test_every_registered_operation_is_documented_for_agents() -> None:
    required = set(public_schema("alpha_operation")["required"])
    for operation in alpha.list_operations():
        assert required <= set(operation), operation["name"]
        assert operation["summary"], operation["name"]
