"""Planned, versioned agent skill package generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from qlibx.alpha import list_budget_policies, list_operations
from qlibx.documentation import public_example
from qlibx.errors import QlibxError
from qlibx.serialization import digest_bytes

SkillTarget = Literal["codex", "claude", "generic"]


@dataclass(frozen=True, slots=True)
class SkillFilePlan:
    path: Path
    action: str
    content: str
    existed: bool
    before_digest: str | None


@dataclass(frozen=True, slots=True)
class SkillPlan:
    root: Path
    target: SkillTarget
    package_version: str
    instruction_schema_version: int
    files: tuple[SkillFilePlan, ...]
    preserves_unmanaged_files: bool = True


def plan_agent_skill(
    output: str | Path,
    *,
    target: SkillTarget = "generic",
) -> SkillPlan:
    if target not in {"codex", "claude", "generic"}:
        raise QlibxError(
            "QLIBX_SKILL_TARGET_UNSUPPORTED",
            f"Unsupported skill target: {target}",
            action="Choose codex, claude, or generic.",
        )
    selected = Path(output).resolve()
    root = selected.parent if selected.name.lower() == "skill.md" else selected
    content = _skill_files(target)
    plans: list[SkillFilePlan] = []
    for relative, payload in content.items():
        path = root / relative
        existed = path.is_file()
        before = path.read_bytes() if existed else None
        digest = digest_bytes(before) if before is not None else None
        if not existed:
            action = "create"
        elif before == payload.encode("utf-8"):
            action = "unchanged"
        else:
            action = "replace_requires_approval"
        plans.append(SkillFilePlan(path, action, payload, existed, digest))
    return SkillPlan(root, target, "0.1.0", 1, tuple(plans))


def apply_agent_skill(plan: SkillPlan, *, force: bool = False) -> Path:
    """Apply only planned managed files; unrelated user files remain untouched."""
    for file in plan.files:
        exists = file.path.is_file()
        before = file.path.read_bytes() if exists else None
        digest = digest_bytes(before) if before is not None else None
        if exists != file.existed or digest != file.before_digest:
            raise QlibxError(
                "QLIBX_SKILL_STALE_PLAN",
                f"Skill file changed after planning: {file.path}",
                action="Create a new skill plan and review the changed user content.",
            )
        if file.action == "replace_requires_approval" and not force:
            raise QlibxError(
                "QLIBX_SKILL_USER_CONTENT",
                f"Skill file has different content: {file.path}",
                action="Review the planned replacement and apply with explicit force approval.",
            )
    for file in plan.files:
        if file.action == "unchanged":
            continue
        _atomic_write(file.path, file.content)
    return plan.root / "SKILL.md"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.{uuid4().hex}.staging")
    try:
        staging.write_text(content, encoding="utf-8")
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


def _skill_files(target: SkillTarget) -> dict[str, str]:
    return {
        "SKILL.md": _skill_markdown(target),
        "references/contracts.md": _contracts_markdown(),
        "examples/project-api.py": _project_example(),
        "examples/data-registration.yaml": _registration_example(),
        "examples/logical-dataset.yaml": _logical_dataset_example(),
        "references/alpha-operations.md": _alpha_operations_markdown(),
        "examples/alpha-pipeline.py": _public_example("alpha_pipeline"),
        "examples/custom-alpha-operation.py": _public_example("custom_alpha_operation"),
        "examples/research-workflow.py": _public_example("research_workflow"),
        "examples/stored-ensemble.py": _public_example("stored_ensemble"),
        "examples/signed-execution.py": _public_example("signed_execution"),
        "examples/artifact-reporting.py": _public_example("artifact_reporting"),
        "examples/exponential-decay.py": _extension_example(),
        "examples/local-exposure-analyzer.py": _analyzer_example(),
        "examples/local-text-renderer.py": _renderer_example(),
    }


def _skill_markdown(target: SkillTarget) -> str:
    return f"""---
name: qlibx
description: Execute qlibx point-in-time data and alpha research through public package surfaces.
metadata:
  qlibx_version: 0.1.0
  instruction_schema_version: 1
  target: {target}
---

# qlibx agent workflow

Never edit installed qlibx, Qlib, site-packages, `references/`, or user source data. Start with
`qlibx project status`, `qlibx docs`, `qlibx schema`, and the task-specific help below.

Load an existing project with `Project.load(<root>)`. Build the YAML loader with
`ConfigDrivenDataLoader.from_project(project)` and the centralized research catalog with
`ResearchCatalog.from_project(project)`. Respect the configured source, generated-data, state,
research, and extension roots.

## Register data interactively

1. Run `qlibx data requirements`.
2. Run `qlibx data discover --root <project>`; this is read-only and excludes generated data.
3. Run `qlibx data inspect --root <project> --path <candidate> --sample-rows 5`.
4. Show the exact schema and unresolved questions to the user. Do not infer availability, ticker,
   value meaning, primary key, frequency, or timezone from a similar name.
5. After confirmation, author `config/qlibx/data/registrations.yaml` using
   `examples/data-registration.yaml` as structure only.
6. Run `qlibx data plan`, explain every assumption/warning, then `qlibx data register`.
7. Add source/dataset YAML and run catalog plus bounded preview. Upstream must hash identically.
   `available_at` is the only required time axis and controls point-in-time visibility. A matrix
   may index it directly. Declare a separate `time_field` only when the user explicitly chose to
   preserve and use an optional event/observation field; use `examples/logical-dataset.yaml`.

## Signal operations and weight scaling

Before writing any transform helper, run `qlibx alpha operations` and read
`references/alpha-operations.md`. Apply one built-in with `apply_transform` or compose several
with `apply_pipeline`; each step records its own operation ID, version and parameters in the
result lineage. Scale weights with a registered budget policy through `apply_budget`: `fixed`
scales each side to its full budget, `flexible` treats the budget as a maximum and reports the
unused side budget as leftover. If nothing matches, register your own `OperationSpec` or
`BudgetPolicySpec`, or promote a `signal_transform` extension with `signal_transform_operation` --
never edit the installed package. Start from `examples/alpha-pipeline.py` and
`examples/custom-alpha-operation.py`.

## Research and execution

Before proposing a trial, query prior proposals, successful/failed/invalid attempts, searched
ranges, and nearest semantic/empirical neighbors. Freeze resolved config, dataset snapshot,
component source and seed before execution. Publish durable success/failure/invalid evidence; do
not promote scratch output. Start from `examples/research-workflow.py`.

Load verified members with `combine_stored_weights`; do not import or rerun their strategies.
Use the combined signed weight in `construct_enhanced_index` or the stored-matrix convenience
`run_signed_execution`. For an adaptive signed StrategyAgent, use `run_strategy_execution` with
`SignedExecutionConfig`; the agent is called at each Qlib decision step with prior confirmed active
account state. Start from `examples/stored-ensemble.py` and `examples/signed-execution.py`.

Matched capitalization is a Qlib long-only compatibility mode, not native borrow, margin, recall,
forced buy-in, or borrow-fee support. Treat Qlib dealt quantity and account state as authoritative.

## Error recovery

Every `QlibxError` returns `code`, `message`, `action`, and `context`. Run
`qlibx errors <code>` before editing config or retrying. If guidance requires user confirmation,
explain the unresolved meaning and ask the user; never guess or silently fall back.

## Capability requirement gaps

Before running a data-dependent capability, read its installed requirement declaration and run its
read-only plan. If `ready` is false or execution raises `QLIBX_CAPABILITY_REQUIREMENT_GAP`:

1. Read `missing_requirements`, each alternative and its reason from the shared resolution.
2. Explain what the capability needs and why; show every acceptable derivation alternative.
3. Ask the listed `user_questions` and inspect only user-selected source data.
4. Run the data-registration interview; never choose a similar dataset or proxy silently.
5. Complete the selected registration/config, then rerun the exact same capability request.
6. Record the selected alternative, assumptions and remaining limitations in the research record.

The plan resolution and runtime error context are the same object shape. Optional outputs marked
`not_requested` are not failures; requested outputs marked `unsatisfied` must not be reported as a
complete result.

## Project-local extension

Run `qlibx extension contracts`, then read `references/contracts.md`. Put trusted code below the
configured extension root and load it with `qlibx.extensions.load_extension`; never patch the
package. Record
its source digest and contract version, then invoke the matching public validator. Store named
intermediate values through `ArtifactStore`; only complete JSON/Parquet artifacts are portable.
Keep analysis sections, report composition and rendering separate. Reporting must not publish a
canonical research result or invoke the original strategy. Start from
`examples/artifact-reporting.py`.
"""


def _alpha_operations_markdown() -> str:
    """Render the installed operation and budget registries into the skill package."""
    lines = [
        "# qlibx built-in signal operations",
        "",
        "Generated from the installed registries. Run `qlibx alpha operations`,",
        "`qlibx alpha operation <name>`, and `qlibx alpha budgets` for the live contract.",
        "",
        "Check this list before writing a helper. Apply one operation with",
        "`qlibx.alpha.apply_transform`, or compose several with `qlibx.alpha.apply_pipeline`;",
        "each step contributes its own versioned `OperationContract` to the result lineage.",
        "",
        "## Operations",
        "",
    ]
    for operation in list_operations():
        required = ", ".join(operation["required_parameters"]) or "none"
        declared = ", ".join(sorted(operation["parameters"])) or "none"
        requirements = operation["requirements"]
        lines.extend(
            [
                f"### {operation['name']} (`{operation['operation_id']}` v{operation['version']})",
                "",
                f"- {operation['summary']}",
                f"- Axis: {operation['axis']}; dtype: {operation['dtype']}",
                f"- NaN behavior: {operation['nan_behavior']}",
                f"- Tie behavior: {operation['tie_behavior']}",
                f"- Group-missing behavior: {operation['group_missing_behavior']}",
                f"- Selection behavior: {operation['selection_behavior']}",
                f"- Minimum observations: {operation['minimum_observations']}",
                f"- Parameters: {declared}; required: {required}",
                f"- Data requirements: {len(requirements)}",
                "",
            ]
        )
        for requirement in requirements:
            alternatives = ", ".join(item["alternative_id"] for item in requirement["alternatives"])
            lines.extend(
                [
                    f"  - `{requirement['requirement_id']}` role `{requirement['role']}`; "
                    f"mandatory={requirement['mandatory']}",
                    f"    alternatives: {alternatives}; availability: "
                    f"{requirement['availability']}",
                ]
            )
        if requirements:
            lines.append("")
    lines.extend(["## Budget policies", ""])
    for policy in list_budget_policies():
        lines.extend(
            [
                f"### {policy['name']} (`{policy['policy_id']}` v{policy['version']})",
                "",
                f"- {policy['summary']}",
                f"- Unused budget: {policy['unused_budget_behavior']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Adding an operation",
            "",
            "Register a `qlibx.alpha.OperationSpec` with `qlibx.alpha.register_operation`, or",
            "promote a validated `signal_transform` extension with",
            "`qlibx.extensions.signal_transform_operation`. Register a weight-scaling rule with",
            "`qlibx.alpha.register_budget_policy`. Never edit the installed package to add one.",
            "See `examples/custom-alpha-operation.py`.",
            "",
        ]
    )
    return "\n".join(lines)


def _contracts_markdown() -> str:
    return """# qlibx public extension contracts

Package version: 0.1.0. Instruction schema: 1.

## signal_transform v1

- Workflow location: after a signed signal is computed and before selection/budget/ensemble.
- Input: one bounded `pandas.DataFrame` indexed by its configured datetime, ticker columns.
- Output: a DataFrame with exactly the same axes; missing input remains missing.
- Time boundary: availability was already bounded by the parent decision context; the extension
  cannot load additional data or expand the configured index/availability axes.
- Side effects: none; it cannot mutate a Qlib account or publish directly.
- Validation: deterministic repeat, axes/missingness equality, finite values where input is finite.
- Minimal implementation: `examples/exponential-decay.py`.

## exposure_analyzer v1

- Workflow location: stored-artifact analysis before report composition.
- Input: verified `ArtifactEnvelope` plus its loaded JSON/Parquet payload.
- Output: public `AnalysisSection` with input artifact lineage and serializable data.
- Side effects: none; it does not rerun or publish the artifact producer.
- Minimal implementation: `examples/local-exposure-analyzer.py`.

## report_renderer v1

- Workflow location: after analysis sections have been selected and ordered.
- Input: public `ReportDocument`; calculations are already complete.
- Output: `bytes` or `str`; qlibx owns the final output and manifest write.
- Side effects: none; a report output is not a canonical research artifact.
- Minimal implementation: `examples/local-text-renderer.py`.

Project extensions are trusted code. Contract validation is not a filesystem/network/process
security sandbox. Source digest and contract version are part of frozen invocation identity.
"""


def _project_example() -> str:
    return '''"""Load only public project surfaces."""

from qlibx import Project
from qlibx.data import ConfigDrivenDataLoader
from qlibx.research import ResearchCatalog

project = Project.load(".")
loader = ConfigDrivenDataLoader.from_project(project)
research = ResearchCatalog.from_project(project)
'''


def _public_example(name: str) -> str:
    return str(public_example(name)["content"])


def _registration_example() -> str:
    return """# Structure only. Replace every placeholder after explicit user confirmation.
registrations:
  confirmed_dataset_id:
    source: data/confirmed-source.parquet
    output: data/qlibx/confirmed_dataset_id.parquet
    available_at:
      source: confirmed_time_column
      offset_days: 0
    ticker: confirmed_ticker_column
    information:
      info_1: confirmed_information_column
    primary_key: [confirmed_time_column, confirmed_ticker_column]
    frequency: confirmed_frequency
    timezone: confirmed_timezone
"""


def _logical_dataset_example() -> str:
    return """datasets:
  confirmed_values:
    kind: matrix
    sources: [confirmed]
    query: |
      select available_at, ticker, value
      from confirmed
    index: available_at
    columns: ticker
    values: value
"""


def _extension_example() -> str:
    return '''"""Project-local signal_transform v1 example."""

from __future__ import annotations

import pandas as pd


def apply(values: pd.DataFrame, *, span: int = 5) -> pd.DataFrame:
    if span < 1:
        raise ValueError("span must be positive")
    result = values.ewm(span=span, adjust=False, min_periods=1).mean()
    return result.where(values.notna())
'''


def _analyzer_example() -> str:
    return '''"""Project-local exposure_analyzer v1 example."""

from qlibx.reporting import AnalysisSection


def analyze(envelope, payload):
    gross = float(payload.abs().sum().sum())
    return AnalysisSection(
        "local_exposure",
        "1",
        (envelope.artifact_id,),
        {"gross": gross},
    )
'''


def _renderer_example() -> str:
    return '''"""Project-local report_renderer v1 example."""


def render(document):
    return "\\n".join(section.section_id for section in document.sections)
'''
