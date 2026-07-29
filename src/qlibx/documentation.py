"""Version-matched agent-facing help and machine-readable contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qlibx.errors import QlibxError, unknown_name

TOPICS: Mapping[str, str] = {
    "project": (
        "Initialize or load a project, inspect selected roots and compatibility, and preview "
        "every mutation before applying it."
    ),
    "data": (
        "Inspect read-only, confirm available_at/ticker/opaque information mappings, author YAML, "
        "plan, register, then bounded-preview."
    ),
    "strategy": (
        "Declare Strategy requirements in project YAML, bind registered fields after user "
        "approval, and invoke plain pandas Strategy callables with fixed bounded lookbacks."
    ),
    "alpha": (
        "Use qlibx.alpha deterministic transforms; fixed budgets rescale, flexible budgets never "
        "scale upward."
    ),
    "research": (
        "Stage in a session, then publish immutable blobs/manifests with append-only events "
        "through ResearchCatalog."
    ),
    "ensemble": (
        "Combine verified stored signed weights by ticker; preserve member exposure and record "
        "contribution/netting."
    ),
    "execution": (
        "Use qlibx.execution and Qlib 0.9.7. Matched capitalization is a long-only compatibility "
        "mode, not native borrowing."
    ),
    "extension": (
        "Load trusted project-local callable source with contract/version/digest; validation is "
        "not a security sandbox."
    ),
    "errors": (
        "Look up stable qlibx error codes, the failed contract, and a recovery action before "
        "editing config or retrying a mutation."
    ),
}

ERROR_GUIDANCE: Mapping[str, Mapping[str, Any]] = {
    "QLIBX_PROJECT_SCHEMA_UNSUPPORTED": {
        "recovery": "Use a project manifest schema supported by the installed qlibx version.",
    },
    "QLIBX_PROJECT_PATH_ESCAPE": {
        "recovery": "Select a project-owned path below the project root.",
    },
    "QLIBX_PATH_ESCAPE": {
        "recovery": "Select a project-owned path below the project root.",
    },
    "QLIBX_CONFIG_MISSING": {
        "recovery": "Create the requested YAML only after reviewing the installed schema/example.",
    },
    "QLIBX_CONFIG_INVALID": {
        "recovery": "Correct the YAML value named in context; do not silently substitute it.",
    },
    "QLIBX_CONFIG_MAPPING_REQUIRED": {
        "recovery": "Replace the value with an explicit YAML mapping.",
    },
    "QLIBX_CONFIG_LIST_REQUIRED": {
        "recovery": "Replace the value with an explicit YAML list.",
    },
    "QLIBX_CONFIG_STRING_REQUIRED": {
        "recovery": "Replace the value with an explicit non-empty string.",
    },
    "QLIBX_YAML_DUPLICATE_KEY": {
        "recovery": "Remove the duplicate YAML key and review which value the user intended.",
    },
    "QLIBX_DISCOVERY_LIMIT_INVALID": {
        "recovery": "Use a positive bounded discovery limit.",
    },
    "QLIBX_DISCOVERY_PATH_MISSING": {
        "recovery": "Confirm the user-owned source path before discovery.",
    },
    "QLIBX_SOURCE_PATH_OUTSIDE_ROOT": {
        "recovery": "Use a source below the configured read-only source-data root.",
    },
    "QLIBX_INSPECTION_SOURCE_MISSING": {
        "recovery": "Confirm the candidate path and inspect again without creating or changing it.",
    },
    "QLIBX_INSPECTION_FORMAT_UNSUPPORTED": {
        "recovery": (
            "Use a supported Parquet or DuckDB source, or convert it outside qlibx with approval."
        ),
    },
    "QLIBX_INSPECTION_SAMPLE_INVALID": {
        "recovery": "Use a positive bounded sample size.",
    },
    "QLIBX_DUCKDB_TABLE_UNKNOWN": {
        "recovery": "Choose an inspected table explicitly; never guess a similar table name.",
    },
    "QLIBX_REGISTRATION_UNKNOWN": {
        "recovery": "Choose a registration ID declared in the selected project YAML.",
    },
    "QLIBX_REGISTRATION_SOURCE_MISSING": {
        "recovery": (
            "Confirm the source path with the user; do not create or replace upstream data."
        ),
    },
    "QLIBX_REGISTRATION_MAPPING_MISSING": {
        "recovery": "Discuss the exact available_at, ticker, and information mapping; never guess.",
        "requires_user_confirmation": True,
    },
    "QLIBX_INFORMATION_MAPPING_REQUIRED": {
        "recovery": "Map at least one user-confirmed opaque information field.",
        "requires_user_confirmation": True,
    },
    "QLIBX_INFORMATION_AXIS_COLLISION": {
        "recovery": "Choose information output names distinct from available_at and ticker.",
    },
    "QLIBX_AVAILABILITY_OFFSET_REQUIRED": {
        "recovery": "Ask the user for the availability convention and record an explicit offset.",
        "requires_user_confirmation": True,
    },
    "QLIBX_AVAILABILITY_SOURCE_NOT_DATETIME": {
        "recovery": (
            "Resolve the source timestamp quality outside qlibx, then re-plan registration."
        ),
    },
    "QLIBX_PRIMARY_KEY_NULL": {
        "recovery": "Resolve null key rows outside qlibx; qlibx will not invent key values.",
    },
    "QLIBX_PRIMARY_KEY_DUPLICATE": {
        "recovery": (
            "Agree on a duplicate policy outside qlibx, repair the source or mapping, then re-plan."
        ),
        "requires_user_confirmation": True,
    },
    "QLIBX_OUTPUT_OUTSIDE_GENERATED_DATA": {
        "recovery": "Write derived Parquet only below the configured generated-data root.",
    },
    "QLIBX_SOURCE_CHANGED_DURING_REGISTRATION": {
        "recovery": (
            "Discard the stale plan, inspect the changed source, and request confirmation again."
        ),
    },
    "QLIBX_CATALOG_SCHEMA_UNSUPPORTED": {
        "recovery": "Use a logical-dataset schema supported by the installed qlibx version.",
    },
    "QLIBX_CONFIG_PATH_ESCAPE": {
        "recovery": "Keep every logical-dataset config path below the selected config root.",
    },
    "QLIBX_SOURCE_ROOT_UNKNOWN": {
        "recovery": "Choose a source root declared in the project catalog.",
    },
    "QLIBX_SOURCE_MISSING": {
        "recovery": "Register or restore the declared generated source before loading it.",
    },
    "QLIBX_DATASET_UNKNOWN": {
        "recovery": "Choose a logical dataset returned by the public catalog command.",
    },
    "QLIBX_DATASET_KIND_INVALID": {
        "recovery": "Use a documented table or matrix dataset kind.",
    },
    "QLIBX_DATASET_SOURCE_UNKNOWN": {
        "recovery": "Declare every query source in the selected logical-dataset YAML.",
    },
    "QLIBX_DATASET_DUPLICATE": {
        "recovery": "Rename or remove the duplicate logical dataset definition explicitly.",
    },
    "QLIBX_IDENTIFIER_INVALID": {
        "recovery": "Use a documented safe identifier without SQL or path syntax.",
    },
    "QLIBX_QUERY_FAILED": {
        "recovery": "Review the declared query and source schema; do not add a silent fallback.",
    },
    "QLIBX_LIMIT_INVALID": {
        "recovery": "Use a positive bounded preview limit.",
    },
    "QLIBX_TICKER_FILTER_EMPTY": {
        "recovery": "Provide at least one explicit ticker or omit the filter.",
    },
    "QLIBX_DATASET_NOT_MATRIX": {
        "recovery": "Use load_table, or select a dataset declared as a matrix.",
    },
    "QLIBX_MATRIX_COLUMNS_MISSING": {
        "recovery": "Declare index, columns, and values fields for the matrix contract.",
    },
    "QLIBX_MATRIX_KEY_DUPLICATE": {
        "recovery": (
            "Resolve duplicate matrix-index/ticker rows before pivoting; qlibx will not aggregate "
            "silently."
        ),
    },
    "QLIBX_EXECUTION_CONFIG_OUTSIDE_ROOT": {
        "recovery": "Select an execution YAML below the configured project config root.",
    },
    "QLIBX_EXECUTION_PROFILE_SCHEMA_UNSUPPORTED": {
        "recovery": "Use an execution-profile schema supported by the installed qlibx version.",
    },
    "QLIBX_TARGET_SEMANTICS_UNSUPPORTED": {
        "recovery": "Choose one of the target semantics listed by qlibx qlib requirements.",
    },
    "QLIBX_INSTRUCTION_TARGET_REQUIRED": {
        "recovery": (
            "Run detection, let the user select one or more instruction files, then dry-run."
        ),
        "requires_user_confirmation": True,
    },
    "QLIBX_INSTRUCTION_STALE_PLAN": {
        "recovery": "Create a new dry-run and re-review user-authored content before applying.",
    },
    "QLIBX_SKILL_TARGET_UNSUPPORTED": {
        "recovery": "Choose codex, claude, or generic.",
    },
    "QLIBX_SKILL_FORCE_WITHOUT_APPLY": {
        "recovery": "Review the dry-run, then use --apply --force only with explicit approval.",
        "requires_user_confirmation": True,
    },
    "QLIBX_SKILL_STALE_PLAN": {
        "recovery": "Regenerate the skill plan and review the changed file.",
    },
    "QLIBX_SKILL_USER_CONTENT": {
        "recovery": "Preserve or review user edits; replace only after explicit approval.",
        "requires_user_confirmation": True,
    },
    "QLIBX_DOCUMENTATION_TOPIC_UNKNOWN": {
        "recovery": (
            "Choose a topic, schema, example, or error code from the returned available list."
        ),
    },
    "QLIBX_ALPHA_OPERATION_UNKNOWN": {
        "recovery": (
            "Run qlibx alpha operations and choose an installed name, or register your own "
            "OperationSpec instead of editing the package."
        ),
    },
    "QLIBX_CAPABILITY_REQUIREMENT_GAP": {
        "recovery": (
            "Read context.missing_requirements and each alternative, explain them to the user, "
            "inspect the named source data, register or configure the user-selected alternative, "
            "then rerun the same capability. Never choose a proxy silently."
        ),
        "requires_user_confirmation": True,
    },
    "QLIBX_BUDGET_POLICY_UNKNOWN": {
        "recovery": (
            "Run qlibx alpha budgets and choose an installed policy, or register your own "
            "BudgetPolicySpec."
        ),
    },
    "QLIBX_EXTENSION_CONTRACT_UNKNOWN": {
        "recovery": (
            "Run qlibx extension contracts and choose a contract the installed version offers."
        ),
    },
    **{
        code: {
            "recovery": (
                "Read the Strategy error action, inspect the installed manifest/binding schema "
                "and registered field inventory, then create a new read-only Strategy plan."
            )
        }
        for code in (
            "QLIBX_STRATEGY_BOUND_FIELDS_MISSING",
            "QLIBX_STRATEGY_CALLABLE_MISSING",
            "QLIBX_STRATEGY_CONFIG_KEYS_INVALID",
            "QLIBX_STRATEGY_CONFIG_OUTSIDE_ROOT",
            "QLIBX_STRATEGY_CONFIG_SCHEMA_UNSUPPORTED",
            "QLIBX_STRATEGY_CONTRACT_UNSUPPORTED",
            "QLIBX_STRATEGY_EXECUTION_OUTPUT_INVALID",
            "QLIBX_STRATEGY_EXECUTION_UNIVERSE_MISMATCH",
            "QLIBX_STRATEGY_FIELD_NULLABLE_INVALID",
            "QLIBX_STRATEGY_FIELDS_EMPTY",
            "QLIBX_STRATEGY_INDEX_INVALID",
            "QLIBX_STRATEGY_INPUT_DTYPE_INVALID",
            "QLIBX_STRATEGY_INPUT_MUTATED",
            "QLIBX_STRATEGY_INPUT_NULL_INVALID",
            "QLIBX_STRATEGY_INPUTS_EMPTY",
            "QLIBX_STRATEGY_LOOKBACK_INVALID",
            "QLIBX_STRATEGY_LOOKBACK_UNSUPPORTED",
            "QLIBX_STRATEGY_OUTPUT_INVALID",
            "QLIBX_STRATEGY_OUTPUT_NOT_PANDAS",
            "QLIBX_STRATEGY_PANDAS_KIND_INVALID",
            "QLIBX_STRATEGY_PARAMETER_COLLISION",
            "QLIBX_STRATEGY_RESOLUTION_MISMATCH",
            "QLIBX_STRATEGY_SIGNATURE_MISMATCH",
            "QLIBX_STRATEGY_SOURCE_INVALID",
            "QLIBX_STRATEGY_SOURCE_MISSING",
            "QLIBX_STRATEGY_SOURCE_OUTSIDE_EXTENSIONS",
            "QLIBX_STRATEGY_UNIVERSE_MISMATCH",
            "QLIBX_STRATEGY_UNIVERSE_DUPLICATE",
            "QLIBX_STRATEGY_UNIVERSE_NULL",
            "QLIBX_STRATEGY_UNIVERSE_REDECLARED",
        )
    },
}

SCHEMAS: Mapping[str, Mapping[str, Any]] = {
    "project_manifest": {
        "required": ["schema_version", "paths"],
        "paths": [
            "config",
            "source_data",
            "generated_data",
            "state",
            "research",
            "extensions",
        ],
        "containment": "every configured path must remain below the selected project root",
    },
    "logical_dataset": {
        "required": ["kind", "sources", "query"],
        "optional": ["time_field", "availability_field", "ticker_field"],
        "defaults": {
            "availability_field": "available_at",
            "time_field": "the resolved availability_field",
            "ticker_field": "ticker",
        },
        "matrix_required": ["index", "columns", "values"],
        "time_contract": (
            "available_at controls point-in-time visibility; a separate event or observation "
            "time is optional and must be explicitly user-declared"
        ),
    },
    "data_inspection": {
        "required_output": [
            "path",
            "format",
            "tables",
            "unresolved_requirements",
            "required_user_questions",
            "read_only",
            "mutates",
        ],
        "semantic_inference": "forbidden",
    },
    "dataset_registration": {
        "required": ["source", "output", "available_at", "ticker", "information"],
        "available_at": {"required": ["source", "offset_days"]},
        "ownership": {"source": "user_read_only", "output": "generated_data"},
    },
    "strategy_definition": {
        "required": ["strategy_id", "name", "parameters", "data_requirements", "output_kind"],
        "output_kind": ["signal", "weight", "order", "payload"],
        "status": "compatibility_api",
    },
    "strategy_manifest": {
        "required": ["schema_version", "contract", "strategy"],
        "contract": "qlibx.pandas_strategy",
        "strategy_required": [
            "id",
            "version",
            "name",
            "implementation",
            "parameters",
            "lookback",
            "inputs",
            "output",
        ],
        "lookback": {"kind": "rows", "value": "positive_integer"},
        "inherited_inputs": ["universe"],
        "source_field_names": "forbidden",
    },
    "strategy_binding": {
        "required": ["schema_version", "binding"],
        "binding_required": ["id", "strategy", "inputs"],
        "input_required": ["registered_dataset"],
        "input_optional": ["fields"],
        "field_direction": "canonical_name_to_registered_field",
        "raw_paths": "forbidden",
        "question_or_confirmation_text": "forbidden",
        "duplicated_pandas_contract": "forbidden",
    },
    "research_publication": {
        "statuses": ["successful", "failed", "invalid", "abandoned"],
        "authority": ["immutable_manifest", "append_only_event"],
        "projection": "rebuildable_duckdb",
    },
    "extension": {
        "required": ["extension_id", "contract", "contract_version", "source", "callable_name"],
        "trust": "trusted_project_code_not_sandboxed",
    },
    "artifact_envelope": {
        "required": [
            "artifact_type",
            "schema_version",
            "artifact_id",
            "run_id",
            "producer_id",
            "producer_version",
            "implementation_digest",
            "parent_artifact_ids",
            "input_artifact_ids",
            "time_range",
            "data_semantics",
            "payload_format",
            "payload_digest",
            "coverage",
            "warnings",
            "diagnostics",
            "status",
        ],
        "portable_formats": ["json", "parquet"],
        "complete_only_export": True,
    },
    "analysis_section": {
        "required": ["section_id", "version", "input_artifact_ids", "data", "warnings"],
        "producer_independent": True,
    },
    "report_document": {
        "required": ["report_id", "schema_version", "sections"],
        "analysis_in_renderer": "forbidden",
        "canonical_research_artifact": False,
    },
    "execution_profile": {
        "required_clock": ["signal_cutoff", "decision_time", "execution_time", "valuation_time"],
        "mapping": "explicit_logical_dataset_roles",
        "derived_financial_fields": "none",
        "public_plan": "capability_plan",
    },
    "capability_requirement": {
        "required": [
            "requirement_id",
            "role",
            "meaning",
            "axis",
            "unit",
            "currency",
            "purpose",
            "satisfaction_rule",
            "availability",
            "mandatory",
            "unavailable_effect",
            "alternatives",
            "next_commands",
        ],
        "alternative_required": [
            "alternative_id",
            "description",
            "required_inputs",
            "derivation",
        ],
    },
    "capability_plan": {
        "required": [
            "declaration",
            "resolution",
            "parameters",
            "warnings",
            "unsupported_features",
            "ready",
            "read_only",
            "mutates",
        ],
        "read_only": True,
        "error_equivalence": (
            "resolution is serialized unchanged into QLIBX_CAPABILITY_REQUIREMENT_GAP context"
        ),
    },
    "alpha_operation": {
        "required": [
            "name",
            "operation_id",
            "version",
            "summary",
            "axis",
            "tie_behavior",
            "nan_behavior",
            "minimum_observations",
            "group_missing_behavior",
            "selection_behavior",
            "dtype",
            "parameters",
            "required_parameters",
            "requirements",
            "implementation",
        ],
        "lookup": "qlibx alpha operations | qlibx alpha operation <name>",
        "lineage": (
            "operation_id and version are recorded in TransformResult.lineage for every "
            "applied step, including project-local and extension-backed operations"
        ),
        "registration": (
            "qlibx.alpha.register_operation(OperationSpec(...)); a validated signal_transform "
            "extension becomes an OperationSpec through "
            "qlibx.extensions.signal_transform_operation"
        ),
        "composition": "qlibx.alpha.apply_pipeline composes any registered operations in order",
    },
    "budget_policy": {
        "required": ["name", "policy_id", "version", "summary", "unused_budget_behavior"],
        "lookup": "qlibx alpha budgets",
        "builtin": ["fixed", "flexible"],
        "registration": "qlibx.alpha.register_budget_policy(BudgetPolicySpec(...))",
        "result": (
            "qlibx.alpha.apply_budget returns rescaled weights plus per-date used and "
            "leftover side budget; a flexible side is never scaled upward"
        ),
    },
    "error_response": {
        "required": ["code", "message", "action", "context"],
        "lookup": "qlibx errors <code>",
        "agent_behavior": "report the code/action/context; never guess through a failed contract",
    },
}

TASK_GUIDES: Mapping[str, Mapping[str, Any]] = {
    "project": {
        "version": 1,
        "purpose": TOPICS["project"],
        "read_only": ["qlibx project status --root <project>"],
        "writes": ["qlibx project init --root <project>"],
        "python_api": [
            "project = Project.load(<root>)",
            "loader = ConfigDrivenDataLoader.from_project(project)",
            "catalog = ResearchCatalog.from_project(project)",
        ],
        "steps": [
            "Run project status before changing files.",
            "Confirm selected config, source, generated-data, state, research and extension roots.",
            "Use Project.initialize only for a user-approved new project root.",
            "Keep source data read-only and generated state in its configured roots.",
        ],
        "schemas": ["project_manifest"],
        "examples": ["project_api"],
    },
    "data": {
        "version": 1,
        "purpose": TOPICS["data"],
        "read_only": [
            "qlibx data requirements",
            "qlibx data discover --root <project>",
            "qlibx data inspect --root <project> --path <candidate>",
            "qlibx data plan --root <project> --dataset <id>",
        ],
        "writes": [
            "user-confirmed config/qlibx/data/*.yaml",
            "qlibx data register -> data/qlibx/*.parquet and .qlibx/registrations/*.json",
        ],
        "steps": [
            "Discover candidates read-only and exclude generated data.",
            "Inspect bounded schema/sample; return every unresolved semantic question to the user.",
            (
                "Author YAML only from confirmed availability/ticker/information/key/"
                "frequency/timezone."
            ),
            "Plan and explain assumptions before registration.",
            "Register, verify upstream hash, declare logical datasets, and bounded-preview.",
        ],
        "recovery": {
            "QLIBX_REGISTRATION_MAPPING_MISSING": "Discuss exact mapping; never guess or fallback.",
            "QLIBX_PRIMARY_KEY_DUPLICATE": "Resolve duplicate policy outside qlibx, then re-plan.",
            "QLIBX_SOURCE_CHANGED_DURING_REGISTRATION": "Discard plan and inspect the new source.",
        },
        "python_api": [
            "project = Project.load(<root>)",
            "loader = ConfigDrivenDataLoader.from_project(project)",
            (
                "matrix = loader.load_matrix(<dataset>, start=<time-field-start>, "
                "end=<time-field-end>, as_of=<decision-time>)"
            ),
        ],
        "schemas": [
            "data_inspection",
            "dataset_registration",
            "logical_dataset",
            "execution_profile",
        ],
        "examples": ["data_registration", "logical_dataset", "project_api"],
    },
    "strategy": {
        "version": 1,
        "purpose": TOPICS["strategy"],
        "read_only": [
            "qlibx strategy requirements --strategy <id> --root <project>",
            "qlibx strategy plan --strategy <id> [--binding <id>] --root <project>",
            (
                "qlibx strategy preview --strategy <id> --binding <id> "
                "--decision-time <time> --root <project>"
            ),
        ],
        "writes": [
            "user-approved config/qlibx/strategies/*.yaml",
            "user-approved config/qlibx/bindings/*.yaml",
            "trusted qlibx-custom Strategy source",
        ],
        "steps": [
            "Write a plain pandas callable; do not import project, catalog, binding or agent APIs.",
            "Declare canonical inputs and fields in a Strategy manifest; universe is inherited.",
            "Run an unbound plan and inspect its registered field inventory.",
            (
                "Propose exact canonical-to-registered field mappings to the user; write the "
                "binding only after approval."
            ),
            "Validate and preview fixed bounded pandas inputs, then invoke the Strategy.",
            "A parent may call child pandas Strategies with equal or narrower bounded inputs.",
        ],
        "schemas": ["strategy_manifest", "strategy_binding", "capability_plan"],
        "examples": ["strategy_manifest", "strategy_binding", "pandas_strategy"],
    },
    "alpha": {
        "version": 1,
        "purpose": TOPICS["alpha"],
        "read_only": [
            "qlibx alpha operations",
            "qlibx alpha operation <name>",
            "qlibx alpha budgets",
        ],
        "steps": [
            "Start from a signed ticker-level signal; neutrality is optional.",
            (
                "List installed operations before writing a helper; apply them with "
                "apply_transform or compose them with apply_pipeline."
            ),
            (
                "Read each operation requirement and run the read-only plan before execution; "
                "resolve a structured gap with the user instead of substituting data."
            ),
            "Apply deterministic versioned operations with explicit NaN/tie/window semantics.",
            "Record long/short/gross/net, coverage, missingness, turnover and availability audit.",
            (
                "Choose a registered budget policy; flexible preserves unused side budget "
                "and reports it as leftover."
            ),
            (
                "If no built-in matches, register an OperationSpec or promote a "
                "signal_transform extension instead of rewriting the operation."
            ),
        ],
        "schemas": [
            "alpha_operation",
            "budget_policy",
            "capability_requirement",
            "capability_plan",
        ],
        "examples": ["alpha_pipeline", "custom_alpha_operation"],
    },
    "research": {
        "version": 1,
        "purpose": TOPICS["research"],
        "steps": [
            "Query prior success/failure/invalid trials, searched ranges and nearest neighbors.",
            "Create a bounded proposal and isolated session; freeze config/data/component/seed.",
            (
                "Worker stages only; publisher verifies, appends intent, installs blobs, commits "
                "event, updates projection."
            ),
            "Publish decision with evidence and expected current version; stale CAS fails.",
        ],
        "schemas": ["research_publication"],
        "python_api": [
            "catalog = ResearchCatalog.from_project(Project.load(<root>))",
            "context = catalog.query_context(candidate=<descriptor>)",
            (
                "proposal = catalog.create_proposal(ResearchProposal(...), "
                "session_id=..., agent_id=...)"
            ),
            "published = catalog.publish(attempt, status=..., metadata=..., parents=...)",
        ],
        "examples": ["research_workflow"],
    },
    "ensemble": {
        "version": 1,
        "purpose": TOPICS["ensemble"],
        "steps": [
            "Load verified stored member weights without strategy import.",
            "Preserve actual member side exposure, align tickers and net only same-ticker intent.",
            "Publish contribution, netting, exposure, similarity and parent lineage.",
            (
                "Construct benchmark-relative physical stock/ETF/cash target with explicit "
                "solver outcome."
            ),
        ],
        "python_api": [
            "combined = combine_stored_weights(catalog, members={<record-id>: coefficient})",
            "portfolio = construct_enhanced_index(benchmark_weight=..., active_weight=..., ...)",
        ],
        "examples": ["stored_ensemble"],
    },
    "execution": {
        "version": 1,
        "purpose": TOPICS["execution"],
        "steps": [
            (
                "Validate registered execution profile and freeze Qlib adapter/version in "
                "result identity."
            ),
            "Submit physical orders through Qlib; dealt quantity is authoritative.",
            (
                "For matched mode reconcile composite, baseline journal and active A=C-B at "
                "one checkpoint."
            ),
            "Report reserve, active denominator and unsupported borrow/margin/recall/fee features.",
        ],
        "python_api": [
            "result = run_strategy_execution(definition, program, datasets=..., ...)",
            "result = run_signed_execution(signed_weights=..., execution_price=..., ...)",
        ],
        "examples": ["signed_execution"],
    },
    "extension": {
        "version": 1,
        "purpose": TOPICS["extension"],
        "steps": [
            "Run qlibx extension contracts, then read the exact versioned contract and example.",
            "Create source below project extension root; never edit installed package.",
            "Validate bounded input/output/time/side-effect contract and record source digest.",
            "Freeze extension source/contract version in invocation identity.",
            (
                "Record portable intermediate artifacts and keep analysis, composition and "
                "rendering separate."
            ),
        ],
        "schemas": ["extension", "artifact_envelope", "analysis_section", "report_document"],
        "examples": [
            "exponential_decay",
            "local_exposure_analyzer",
            "local_text_renderer",
            "artifact_reporting",
        ],
    },
    "errors": {
        "version": 1,
        "purpose": TOPICS["errors"],
        "read_only": ["qlibx errors", "qlibx errors <code>"],
        "steps": [
            "Capture the structured code, message, action, and context.",
            "Look up the exact code before editing config or retrying.",
            "If requires_user_confirmation is true, explain the ambiguity and ask the user.",
            "After correction, create a new plan; never reuse a stale mutation plan.",
        ],
        "schema": "error_response",
        "guidance": ERROR_GUIDANCE,
        "examples": ["error_response"],
    },
}

EXAMPLES: Mapping[str, Mapping[str, str]] = {
    "project_api": {
        "format": "python",
        "content": (
            "from qlibx import Project\n"
            "from qlibx.data import ConfigDrivenDataLoader\n"
            "from qlibx.research import ResearchCatalog\n"
            "project = Project.load('.')\n"
            "loader = ConfigDrivenDataLoader.from_project(project)\n"
            "research = ResearchCatalog.from_project(project)\n"
        ),
    },
    "logical_dataset": {
        "format": "yaml",
        "content": (
            "datasets:\n"
            "  confirmed_values:\n"
            "    kind: matrix\n"
            "    sources: [confirmed]\n"
            "    query: select available_at, ticker, value from confirmed\n"
            "    index: available_at\n"
            "    columns: ticker\n"
            "    values: value\n"
        ),
    },
    "data_registration": {
        "format": "yaml",
        "content": (
            "registrations:\n"
            "  confirmed_id:\n"
            "    source: data/confirmed.parquet\n"
            "    output: data/qlibx/confirmed_id.parquet\n"
            "    available_at: {source: confirmed_time, offset_days: 0}\n"
            "    ticker: confirmed_ticker\n"
            "    information: {info_1: confirmed_value}\n"
            "    primary_key: [confirmed_time, confirmed_ticker]\n"
            "    frequency: confirmed_frequency\n"
            "    timezone: confirmed_timezone\n"
        ),
    },
    "strategy_definition": {
        "format": "python",
        "content": (
            "StrategyDefinition('reversal.v1', 'reversal', {'window': 5}, ('returns',), "
            "'weight', version='1')"
        ),
    },
    "strategy_manifest": {
        "format": "yaml",
        "content": (
            "schema_version: 1\n"
            "contract: qlibx.pandas_strategy\n"
            "strategy:\n"
            "  id: open_close_rebound\n"
            "  version: '1'\n"
            "  name: Open Close Rebound\n"
            "  implementation: {source: strategies/open_close_rebound.py, callable: decide}\n"
            "  parameters: {rebound_threshold: 0.02}\n"
            "  lookback: {kind: rows, value: 20}\n"
            "  inputs:\n"
            "    market_data:\n"
            "      meaning: Daily market prices.\n"
            "      pandas: {kind: table, index: [date, ticker]}\n"
            "      fields:\n"
            "        open_price: {meaning: Session open, dtype: float64, "
            "unit: price, nullable: false}\n"
            "        close_price: {meaning: Session close, dtype: float64, "
            "unit: price, nullable: false}\n"
            "  output: {kind: signal}\n"
        ),
    },
    "strategy_binding": {
        "format": "yaml",
        "content": (
            "schema_version: 1\n"
            "binding:\n"
            "  id: open_close_rebound.krx\n"
            "  strategy: {id: open_close_rebound, version: '1'}\n"
            "  inputs:\n"
            "    universe: {registered_dataset: krx_daily_universe}\n"
            "    market_data:\n"
            "      registered_dataset: krx_daily_ohlcv\n"
            "      fields: {open_price: 시가, close_price: 종가}\n"
        ),
    },
    "pandas_strategy": {
        "format": "python",
        "content": (
            "def child_rebound(*, market_data):\n"
            "    return market_data['close_price'] - market_data['open_price']\n\n"
            "def decide(*, universe, market_data, rebound_threshold):\n"
            "    signal = child_rebound(market_data=market_data).unstack('ticker')\n"
            "    return signal.where(universe.reindex_like(signal), 0.0) * rebound_threshold\n"
        ),
    },
    "research_workflow": {
        "format": "python",
        "content": (
            "from qlibx import Project\n"
            "from qlibx.research import ResearchCatalog, ResearchProposal\n"
            "project = Project.load('.')\n"
            "catalog = ResearchCatalog.from_project(project)\n"
            "context = catalog.query_context(candidate={'mechanism': 'reversal'})\n"
            "proposal = ResearchProposal(\n"
            "    hypothesis='short-horizon reversal', mechanism='reversal',\n"
            "    logical_datasets=('returns',), observation_clock='t-1 close',\n"
            "    holding_horizon='5d', strategy='rolling_reversal', transforms=('rank',),\n"
            "    parameter_range={'window': [3, 5, 10]},\n"
            "    evaluation_segment={'start': '2025-01-01', 'end': '2025-03-31'},\n"
            "    comparison_set=('baseline',), cost_assumptions={'bps': 10},\n"
            "    capacity_assumptions={'participation': 0.1},\n"
            "    stopping_condition='three failures', search_limit=3,\n"
            ")\n"
            "proposal_record = catalog.create_proposal(\n"
            "    proposal, session_id='session-1', agent_id='agent-1'\n"
            ")\n"
        ),
    },
    "stored_ensemble": {
        "format": "python",
        "content": (
            "from qlibx import Project\n"
            "from qlibx.ensemble import combine_stored_weights\n"
            "from qlibx.research import ResearchCatalog\n"
            "catalog = ResearchCatalog.from_project(Project.load('.'))\n"
            "result = combine_stored_weights(\n"
            "    catalog, members={'verified-record-id-a': 0.5, 'verified-record-id-b': 0.5}\n"
            ")\n"
            "# result.combined is ticker-level net intent; member strategies were not loaded.\n"
        ),
    },
    "signed_execution": {
        "format": "python",
        "content": (
            "from qlibx.execution import SignedExecutionConfig, run_strategy_execution\n"
            "result = run_strategy_execution(\n"
            "    definition, strategy_program,\n"
            "    datasets={'returns': returns},\n"
            "    execution_price=execution_price, valuation_price=valuation_price,\n"
            "    universe=universe, volume=volume, tradable=tradable,\n"
            "    initial_cash=5_000_000_000.0,\n"
            "    signed=SignedExecutionConfig(\n"
            "        observed=observed, shortable=shortable,\n"
            "        active_booksize=1_000_000_000.0,\n"
            "    ),\n"
            ")\n"
            "assert result.mode == 'matched_capitalization'\n"
            "assert result.signed.reconciliation['passed']\n"
        ),
    },
    "alpha_pipeline": {
        "format": "python",
        "content": (
            "from qlibx.alpha import apply_budget, apply_pipeline, list_operations\n"
            "# Every installed operation and its contract is discoverable before use.\n"
            "available = {item['name'] for item in list_operations()}\n"
            "assert {'cross_sectional_rank', 'linear_decay', 'hump'} <= available\n"
            "transformed = apply_pipeline(\n"
            "    signal,\n"
            "    [('linear_decay', {'window': 5}), 'cross_sectional_rank'],\n"
            ")\n"
            "# lineage records one versioned contract per applied step.\n"
            "assert [item.operation_id for item in transformed.lineage] == [\n"
            "    'qlibx.alpha.linear_decay', 'qlibx.alpha.cross_sectional_rank'\n"
            "]\n"
            "budgeted = apply_budget(transformed.values, policy='flexible')\n"
            "# flexible budget never scales a side up; leftover stays observable.\n"
            "assert (budgeted.long_leftover >= 0).all()\n"
        ),
    },
    "custom_alpha_operation": {
        "format": "python",
        "content": (
            "from qlibx.alpha import OperationSpec, apply_pipeline, register_operation\n"
            "from qlibx.extensions import load_extension, signal_transform_operation\n"
            "\n"
            "# Option A: register a plain project-local callable.\n"
            "def zero_mean_by_row(values, *, minimum_count=1):\n"
            "    return values.sub(values.mean(axis=1), axis=0).where(\n"
            "        values.count(axis=1).ge(minimum_count)\n"
            "    )\n"
            "register_operation(\n"
            "    OperationSpec(\n"
            "        name='zero_mean_by_row',\n"
            "        operation_id='project.zero_mean_by_row',\n"
            "        version='1',\n"
            "        axis='date_by_ticker',\n"
            "        tie_behavior='not_applicable',\n"
            "        nan_behavior='preserve',\n"
            "        minimum_observations=1,\n"
            "        group_missing_behavior='not_applicable',\n"
            "        dtype='float64',\n"
            "        summary='Project-local cross-sectional demean.',\n"
            "        apply=zero_mean_by_row,\n"
            "        parameters={'minimum_count': 'minimum valid observations per date'},\n"
            "    )\n"
            ")\n"
            "\n"
            "# Option B: promote a validated signal_transform extension to an operation.\n"
            "reference, implementation = load_extension(\n"
            "    project, extension_id='exponential_decay', contract='signal_transform',\n"
            "    contract_version='1', source='qlibx-custom/decay.py', callable_name='apply',\n"
            ")\n"
            "register_operation(\n"
            "    signal_transform_operation(\n"
            "        reference, implementation, parameters={'span': 'positive decay span'}\n"
            "    )\n"
            ")\n"
            "result = apply_pipeline(\n"
            "    signal, ['zero_mean_by_row', ('exponential_decay', {'span': 5})]\n"
            ")\n"
        ),
    },
    "artifact_reporting": {
        "format": "python",
        "content": (
            "from qlibx import Project\n"
            "from qlibx.artifacts import ArtifactStore\n"
            "from qlibx.reporting import analyze_stored_run, render_report\n"
            "project = Project.load('.')\n"
            "store = ArtifactStore.from_project(project)\n"
            "envelope = store.load('artifact-id', run_id='run-id')\n"
            "payload = store.load_payload(envelope.artifact_id, run_id='run-id')\n"
            "document = analyze_stored_run('runs.duckdb', 'backtest-run-id')\n"
            "rendered = render_report(document, 'report.html', renderer='html')\n"
        ),
    },
    "error_response": {
        "format": "json",
        "content": (
            '{"code":"QLIBX_REGISTRATION_MAPPING_MISSING",'
            '"message":"required mapping is unresolved",'
            '"action":"Ask the user to confirm the exact mapping.",'
            '"context":{"missing":["available_at"]}}'
        ),
    },
    "exponential_decay": {
        "format": "python",
        "content": (
            "def apply(values, *, span=5):\n"
            "    return values.ewm(span=span, adjust=False).mean().where(values.notna())"
        ),
    },
    "local_exposure_analyzer": {
        "format": "python",
        "content": (
            "from qlibx.reporting import AnalysisSection\n"
            "def analyze(envelope, payload):\n"
            "    gross = float(payload.abs().sum().sum())\n"
            "    return AnalysisSection('local_exposure', '1', "
            "(envelope.artifact_id,), {'gross': gross})"
        ),
    },
    "local_text_renderer": {
        "format": "python",
        "content": (
            "def render(document):\n"
            "    return '\\n'.join(section.section_id for section in document.sections)"
        ),
    },
}


def help_topic(topic: str) -> str:
    if topic not in TOPICS:
        raise _unknown("help topic", topic, TOPICS)
    return TOPICS[topic]


def public_schema(name: str) -> Mapping[str, Any]:
    if name not in SCHEMAS:
        raise _unknown("schema", name, SCHEMAS)
    return SCHEMAS[name]


def task_guide(topic: str) -> Mapping[str, Any]:
    if topic not in TASK_GUIDES:
        raise _unknown("task guide", topic, TASK_GUIDES)
    return TASK_GUIDES[topic]


def public_example(name: str) -> Mapping[str, str]:
    if name not in EXAMPLES:
        raise _unknown("example", name, EXAMPLES)
    return EXAMPLES[name]


def error_guidance(code: str) -> Mapping[str, Any]:
    if code not in ERROR_GUIDANCE:
        raise _unknown("error code", code, ERROR_GUIDANCE)
    return {"code": code, **ERROR_GUIDANCE[code]}


def _unknown(kind: str, name: str, available: Mapping[str, Any]) -> QlibxError:
    return unknown_name("QLIBX_DOCUMENTATION_TOPIC_UNKNOWN", kind, name, available)
