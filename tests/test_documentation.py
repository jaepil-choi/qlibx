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
from qlibx.errors import QlibxError, QlibxInternalError


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
    assert error.value.code == "NOT_FOUND"
    assert "project" in error.value.context["available"]


def test_installed_error_recovery_is_code_specific_and_machine_readable(capsys) -> None:
    assert dispatch(parser().parse_args(["docs", "errors"])) == 0
    assert dispatch(parser().parse_args(["errors", "MISSING"])) == 0
    output = capsys.readouterr().out
    first, second = output.split("}\n{")
    guide = json.loads(first + "}")["errors"]
    lookup = json.loads("{" + second)
    assert guide["schema"] == "error_response"
    # The code alone answers with what its kind means. What to do about *this* failure
    # rides on the raised error, where the check that found it wrote it.
    assert lookup["code"] == "MISSING"
    assert "Declare, register, or bind it" in lookup["recovery"]
    assert error_guidance("CONFLICT")["recovery"]
    assert set(ERROR_GUIDANCE) == {
        "NOT_FOUND",
        "MISSING",
        "INVALID",
        "BOUNDARY",
        "CONFLICT",
        "CORRUPT",
        "UNSUPPORTED",
    }


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
    assert "MISSING" in plan["error_equivalence"]


def _public_raises() -> list[tuple[str, int, str]]:
    """Every `QlibxError(...)` the package can raise, as (file, line, code).

    Read from source rather than by importing behavior, so a raise on a path no test
    exercises is still held to the contract.
    """
    found: list[tuple[str, int, str]] = []
    # Anchor on the package root, not a member module: a module may become a package.
    for path in pathlib.Path(qlibx.__file__).parent.rglob("*.py"):
        if "_vendor" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "QlibxError"):
                continue
            code = (
                node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
            )
            found.append((path.name, node.lineno, code))
    return found


def test_the_public_vocabulary_is_the_seven_codes_and_nothing_else() -> None:
    """A raise may only use a declared code, and every declared code must be reachable.

    The codes are coarse on purpose. Nothing in qlibx branches on one, so a finer set would
    only restate, in this table, the guidance each raise site already writes -- which is how
    the scheme this replaced reached 144 names for 126 failures.
    """
    raises = _public_raises()
    assert raises, "error scan found nothing; the AST walk is broken"
    unknown = sorted({(f, n, c) for f, n, c in raises if c not in ERROR_GUIDANCE})
    assert not unknown, f"raises using a code outside the vocabulary: {unknown}"
    reached = {code for _, _, code in raises}
    assert not set(ERROR_GUIDANCE) - reached, "documented but unreachable"


def test_every_public_failure_says_what_to_do_next() -> None:
    """`action` is what makes a failure public. A raise without one is an internal defect.

    Enforced at the call site rather than trusted to the constructor's signature, because a
    positional `action` would satisfy the type checker while leaving this contract to habit.
    """
    missing: list[str] = []
    for path in pathlib.Path(qlibx.__file__).parent.rglob("*.py"):
        if "_vendor" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "QlibxError"):
                continue
            if not any(keyword.arg == "action" for keyword in node.keywords):
                missing.append(f"{path.name}:{node.lineno}")
    assert not missing, f"QlibxError raised without an action: {missing}"


def test_internal_failures_stay_out_of_the_agent_vocabulary() -> None:
    """An internal defect carries no code and no action, because there is no action.

    `run_signed_execution` reconciling its own composite/baseline/active books is the case
    that motivated the split: the caller neither caused a book disagreement nor can repair
    one, so handing them a stable code and a recovery would be a lie.
    """
    assert not issubclass(QlibxInternalError, QlibxError)
    failure = QlibxInternalError("books disagree", context={"tolerance": 1e-8})
    assert not hasattr(failure, "code")
    assert not hasattr(failure, "action")
    assert failure.to_dict() == {
        "internal": True,
        "message": "books disagree",
        "context": {"tolerance": 1e-8},
    }

    source = (pathlib.Path(qlibx.__file__).parent / "execution.py").read_text(encoding="utf-8")
    assert source.count("raise QlibxInternalError(") == 2, (
        "the two signed-execution reconciliation identities are internal, not agent-facing"
    )


def test_unknown_name_lookups_share_one_structured_shape() -> None:
    """A failed named lookup answers the same way whatever registry it came from."""
    lookups = (
        ["alpha", "operation", "nope"],
        ["extension", "contract", "nope"],
        ["docs", "nope"],
    )
    for argv in lookups:
        with pytest.raises(QlibxError) as failure:
            dispatch(parser().parse_args(argv))
        assert failure.value.code == "NOT_FOUND"
        assert set(failure.value.to_dict()) == {
            "code",
            "message",
            "action",
            "context",
            "requires_user_confirmation",
        }
        assert failure.value.context["available"], argv
        assert failure.value.context["requested"] == "nope"
