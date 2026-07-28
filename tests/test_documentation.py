from __future__ import annotations

import json

import pytest

from qlibx.agent import error_guidance, public_example, public_schema, task_guide
from qlibx.cli import dispatch, parser
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
        "research": "research_workflow",
        "ensemble": "stored_ensemble",
        "execution": "signed_execution",
        "extension": "artifact_reporting",
    }
    for topic, example in expected.items():
        assert example in task_guide(topic)["examples"]
        content = public_example(example)["content"]
        compile(content, f"<{example}>", "exec")
