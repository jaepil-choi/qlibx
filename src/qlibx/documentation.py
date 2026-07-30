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

# The first branch of every error code, and what it tells the caller to do. A code is named
# for the action it demands, never for the module that noticed the failure: a module-shaped
# prefix guarantees the same failure earns a new name in every module that can raise it,
# which is how this scheme previously grew to 144 codes for 126 distinct failures.
FAMILY_RECOVERY: Mapping[str, str] = {
    "NOT_FOUND": (
        "The name is not registered. Read context['available'] and choose from it, or "
        "restore the thing it names. Never substitute something that looks similar."
    ),
    "MISSING": (
        "A declaration the operation needs was never made. Declare, register, or bind it "
        "and run the same command again. qlibx does not supply a default for it."
    ),
    "INVALID": (
        "The value breaks a rule the contract declares. Read the action and context, then "
        "correct the value at its source rather than working around the check."
    ),
    "BOUNDARY": (
        "Something reached outside a boundary qlibx enforces -- a configured root, the "
        "decision time, or a child's inherited scope. Bring the operation back inside it; "
        "widening the boundary to admit the data is never the fix."
    ),
    "CONFLICT": (
        "Stored state already holds this identity, or moved while you worked. Re-read the "
        "current state and derive a new identity; do not overwrite what is committed."
    ),
    "CORRUPT": (
        "Stored bytes do not match the digest recorded for them. Do not consume the "
        "content. Reproduce it from its declared inputs, then investigate the store."
    ),
    "UNSUPPORTED": (
        "The installed build does not implement this version or format. Use one it "
        "supports, or convert the input outside qlibx with the user's approval."
    ),
}

# A leaf carries `recovery` only when it has something to say beyond its family. Repeating
# the family text on every leaf is what let one recovery spread across 25 codes.
ERROR_GUIDANCE: Mapping[str, Mapping[str, Any]] = {
    # -- NOT_FOUND: A named thing is not there. Choose from what is, or restore it.
    "QLIBX_NOT_FOUND_ALPHA_OPERATION": {
        "recovery": (
            "Run qlibx alpha operations and choose an installed name, or register your own "
            "OperationSpec instead of editing the package."
        ),
    },
    "QLIBX_NOT_FOUND_ARTIFACT": {
        "recovery": "Pass run_id to disambiguate, or list the run's stored artifacts.",
    },
    "QLIBX_NOT_FOUND_BUDGET_POLICY": {
        "recovery": (
            "Run qlibx alpha budgets and choose an installed policy, or register your own "
            "BudgetPolicySpec."
        ),
    },
    "QLIBX_NOT_FOUND_CAPITALIZATION_EVENT": {
        "recovery": (
            "Use one of the registered capitalization event types in context['available']."
        ),
    },
    "QLIBX_NOT_FOUND_CONFIG": {
        "recovery": "Create the requested YAML only after reviewing the installed schema/example.",
    },
    "QLIBX_NOT_FOUND_DATASET": {
        "recovery": "Choose a logical dataset returned by the public catalog command.",
    },
    "QLIBX_NOT_FOUND_DATASET_SOURCE": {
        "recovery": "Declare every query source in the selected logical-dataset YAML.",
    },
    "QLIBX_NOT_FOUND_DOCUMENTATION_TOPIC": {
        "recovery": (
            "Choose a topic, schema, example, or error code from the returned available list."
        ),
    },
    "QLIBX_NOT_FOUND_DUCKDB_TABLE": {
        "recovery": "Choose an inspected table explicitly; never guess a similar table name.",
    },
    "QLIBX_NOT_FOUND_EXTENSION_CONTRACT": {
        "recovery": (
            "Run qlibx extension contracts and choose a contract the installed version offers."
        ),
    },
    "QLIBX_NOT_FOUND_FROZEN_RUN": {
        "recovery": (
            "Freeze the run before loading it, or list the frozen bundles the catalog holds."
        ),
    },
    "QLIBX_NOT_FOUND_GENERATED_SOURCE": {
        "recovery": "Register or restore the declared generated source before loading it.",
    },
    "QLIBX_NOT_FOUND_REGISTRATION": {
        "recovery": "Choose a registration ID declared in the selected project YAML.",
    },
    "QLIBX_NOT_FOUND_RESEARCH_ARTIFACT": {
        "recovery": "Choose one of the record's stored artifact names from context['available'].",
    },
    "QLIBX_NOT_FOUND_SOURCE_PATH": {
        "recovery": (
            "Confirm the path with the user and read it as it is. qlibx never creates, moves, or "
            "replaces a source on your behalf."
        ),
    },
    "QLIBX_NOT_FOUND_SOURCE_ROOT": {
        "recovery": "Choose a source root declared in the project catalog.",
    },
    "QLIBX_NOT_FOUND_STRATEGY_CALLABLE": {},
    "QLIBX_NOT_FOUND_STRATEGY_SOURCE": {},
    "QLIBX_NOT_FOUND_WEIGHT_INSTRUMENT": {
        "recovery": "Restrict the weights to instruments the execution scenario declares.",
    },
    # -- MISSING: A required declaration was never given. Declare, register, or bind it.
    "QLIBX_MISSING_AVAILABILITY": {
        "recovery": (
            "Declare when each observation became knowable: register available_at, pass an "
            "availability matrix, or index the frame by a DatetimeIndex. qlibx refuses to guess "
            "visibility, because guessing it is what produces look-ahead."
        ),
    },
    "QLIBX_MISSING_AVAILABILITY_OFFSET": {
        "recovery": "Ask the user for the availability convention and record an explicit offset.",
        "requires_user_confirmation": True,
    },
    "QLIBX_MISSING_BOUND_FIELDS": {},
    "QLIBX_MISSING_CAPABILITY_REQUIREMENTS": {
        "recovery": (
            "Read context.missing_requirements and each alternative, explain them to the user, "
            "inspect the named source data, register or configure the user-selected alternative, "
            "then rerun the same capability. Never choose a proxy silently."
        ),
        "requires_user_confirmation": True,
    },
    "QLIBX_MISSING_DECISION_DATASETS": {
        "recovery": (
            "Compare context.declared with context.supplied, then add the missing datasets or "
            "narrow data_requirements on the Strategy."
        ),
    },
    "QLIBX_MISSING_FULL_HISTORY_REASON": {
        "recovery": (
            "Pass a reason to load_full_history, or call load_table with as_of when the read "
            "happens at a decision time."
        ),
    },
    "QLIBX_MISSING_INFORMATION_MAPPING": {
        "recovery": "Map at least one user-confirmed opaque information field.",
        "requires_user_confirmation": True,
    },
    "QLIBX_MISSING_INSTRUCTION_TARGET": {
        "recovery": (
            "Run detection, let the user select one or more instruction files, then dry-run."
        ),
        "requires_user_confirmation": True,
    },
    "QLIBX_MISSING_MATRIX_AXES": {
        "recovery": (
            "Declare index, columns, and values on the matrix dataset. qlibx will not infer a "
            "matrix axis from the shape of a query result."
        ),
    },
    "QLIBX_MISSING_PUBLICATION_ARTIFACTS": {
        "recovery": (
            "Stage at least one artifact before publishing a successful result, or publish with "
            "the status that reflects what happened."
        ),
    },
    "QLIBX_MISSING_REGISTRATION_MAPPING": {
        "recovery": (
            "Discuss the exact available_at, ticker, and information mapping; never guess."
        ),
        "requires_user_confirmation": True,
    },
    "QLIBX_MISSING_STRATEGY_FIELDS": {},
    "QLIBX_MISSING_STRATEGY_INPUTS": {},
    "QLIBX_MISSING_TICKER_FILTER": {
        "recovery": "Provide at least one explicit ticker or omit the filter.",
    },
    # -- INVALID: A supplied value breaks a declared rule. Correct the value.
    "QLIBX_INVALID_ARTIFACT_STATUS": {
        "recovery": "Record one of the registered artifact statuses in context['available'].",
    },
    "QLIBX_INVALID_AVAILABILITY_AXES": {
        "recovery": (
            "Build available_at on exactly the dataset's index and columns, in the same order, "
            "so each visibility timestamp describes the cell beside it."
        ),
    },
    "QLIBX_INVALID_AVAILABILITY_DTYPE": {
        "recovery": (
            "Resolve the source timestamp quality outside qlibx, then re-plan registration."
        ),
    },
    "QLIBX_INVALID_CALLABLE_SIGNATURE": {},
    "QLIBX_INVALID_CONFIG_KEYS": {},
    "QLIBX_INVALID_CONFIG_LIST": {
        "recovery": "Replace the value with an explicit YAML list.",
    },
    "QLIBX_INVALID_CONFIG_MAPPING": {
        "recovery": "Replace the value with an explicit YAML mapping.",
    },
    "QLIBX_INVALID_CONFIG_STRING": {
        "recovery": "Replace the value with an explicit non-empty string.",
    },
    "QLIBX_INVALID_CONFIG_VALUE": {
        "recovery": "Correct the YAML value named in context; do not silently substitute it.",
    },
    "QLIBX_INVALID_DATASET_DUPLICATE": {
        "recovery": "Rename or remove the duplicate logical dataset definition explicitly.",
    },
    "QLIBX_INVALID_DATASET_KIND": {
        "recovery": "Use a documented table or matrix dataset kind.",
    },
    "QLIBX_INVALID_DATASET_NOT_MATRIX": {
        "recovery": "Use load_table, or select a dataset declared as a matrix.",
    },
    "QLIBX_INVALID_DECISION_OUTPUT_KIND": {
        "recovery": (
            "Return context.declared, or change output_kind on the StrategyDefinition to the "
            "kind the program actually produces."
        ),
    },
    "QLIBX_INVALID_EXECUTION_OUTPUT_KIND": {
        "recovery": (
            "Qlib execution submits weights. Declare output_kind 'weight', or put an explicit "
            "signal-to-weight step in front of execution."
        ),
    },
    "QLIBX_INVALID_EXPORT_ARTIFACT_STATUS": {
        "recovery": (
            "Export complete artifacts only; an incomplete result must not travel as finished."
        ),
    },
    "QLIBX_INVALID_EXPORT_DESTINATION": {
        "recovery": "Export into an empty directory so the bundle stays unambiguous.",
    },
    "QLIBX_INVALID_FEEDBACK_ORDER": {
        "recovery": "Sort feedback_history by confirmed_at before building the DecisionContext.",
    },
    "QLIBX_INVALID_FIELD_NULLABLE": {},
    "QLIBX_INVALID_IDENTIFIER": {
        "recovery": "Use a documented safe identifier without SQL or path syntax.",
    },
    "QLIBX_INVALID_INFORMATION_AXIS": {
        "recovery": "Choose information output names distinct from available_at and ticker.",
    },
    "QLIBX_INVALID_INPUT_DTYPE": {},
    "QLIBX_INVALID_INPUT_NULL": {},
    "QLIBX_INVALID_LIMIT": {
        "recovery": (
            "Pass a positive bounded limit. Every listing, preview, sample, and search stops "
            "where you say it stops."
        ),
    },
    "QLIBX_INVALID_LONG_ONLY_WEIGHT": {
        "recovery": (
            "Long-only targets must be finite, non-negative, and sum to at most 1. Clip or "
            "renormalize before returning them."
        ),
    },
    "QLIBX_INVALID_LOOKBACK": {
        "recovery": "Declare a positive number of rows the Strategy may read at each decision.",
    },
    "QLIBX_INVALID_LOOKBACK_KIND": {},
    "QLIBX_INVALID_MATRIX_KEY_DUPLICATE": {
        "recovery": (
            "Resolve duplicate matrix-index/ticker rows before pivoting; qlibx will not "
            "aggregate silently."
        ),
    },
    "QLIBX_INVALID_OUTPUT_KIND_DECLARATION": {},
    "QLIBX_INVALID_OUTPUT_TYPE": {},
    "QLIBX_INVALID_PANDAS_INDEX": {},
    "QLIBX_INVALID_PANDAS_KIND": {},
    "QLIBX_INVALID_PARAMETER_COLLISION": {},
    "QLIBX_INVALID_PRIMARY_KEY_DUPLICATE": {
        "recovery": (
            "Agree on a duplicate policy outside qlibx, repair the source or mapping, then re- "
            "plan."
        ),
        "requires_user_confirmation": True,
    },
    "QLIBX_INVALID_PRIMARY_KEY_NULL": {
        "recovery": "Resolve null key rows outside qlibx; qlibx will not invent key values.",
    },
    "QLIBX_INVALID_QUERY": {
        "recovery": "Review the declared query and source schema; do not add a silent fallback.",
    },
    "QLIBX_INVALID_RESEARCH_DECISION_KIND": {
        "recovery": "Use one of the registered decision kinds listed in context['available'].",
    },
    "QLIBX_INVALID_RESOLVED_INPUTS": {},
    "QLIBX_INVALID_RUN_STATUS": {
        "recovery": (
            "Publish with one of the registered run statuses listed in context['available']."
        ),
    },
    "QLIBX_INVALID_SEQUENCE_BOUNDARY": {
        "recovery": (
            "Resume from the checkpoint's next_position and keep end_position inside the "
            "contexts you passed."
        ),
    },
    "QLIBX_INVALID_SEQUENCE_ORDER": {
        "recovery": (
            "Sort the contexts by decision_time and remove duplicates; memory flows forward "
            "through the sequence, so the order defines the result."
        ),
    },
    "QLIBX_INVALID_SIDE_EXPOSURE": {
        "recovery": "Scale signed weights with a budget policy so neither side exceeds 1.",
    },
    "QLIBX_INVALID_SKILL_FORCE_FLAG": {
        "recovery": "Review the dry-run, then use --apply --force only with explicit approval.",
        "requires_user_confirmation": True,
    },
    "QLIBX_INVALID_SKILL_TARGET": {
        "recovery": "Choose codex, claude, or generic.",
    },
    "QLIBX_INVALID_STRATEGY_SOURCE": {},
    "QLIBX_INVALID_TARGET_SEMANTICS": {
        "recovery": "Choose one of the target semantics listed by qlibx qlib requirements.",
    },
    "QLIBX_INVALID_UNIVERSE_DUPLICATE": {},
    "QLIBX_INVALID_UNIVERSE_NULL": {},
    "QLIBX_INVALID_UNIVERSE_REDECLARED": {
        "recovery": (
            "Remove 'universe'. Every Strategy inherits it from the execution scenario or from "
            "all_data_requirements; passing it again would let a Strategy widen its own "
            "universe."
        ),
    },
    "QLIBX_INVALID_WEIGHT_PAYLOAD": {
        "recovery": "Return pandas weights keyed by instrument, as a Series or one-row DataFrame.",
    },
    "QLIBX_INVALID_WEIGHT_ROW": {
        "recovery": "Return only the row for the current decision time.",
    },
    "QLIBX_INVALID_YAML_DUPLICATE_KEY": {
        "recovery": "Remove the duplicate YAML key and review which value the user intended.",
    },
    # -- BOUNDARY: Something escaped a declared boundary. Stay inside it.
    "QLIBX_BOUNDARY_CHILD_AVAILABILITY": {
        "recovery": (
            "Omit availability for this dataset. A child inherits its parent's, and may neither "
            "add nor change it."
        ),
    },
    "QLIBX_BOUNDARY_CHILD_AXIS": {},
    "QLIBX_BOUNDARY_CHILD_DATASET": {},
    "QLIBX_BOUNDARY_CHILD_LOOKBACK": {},
    "QLIBX_BOUNDARY_CHILD_OBSERVATIONS": {},
    "QLIBX_BOUNDARY_CONFIG_PATH": {
        "recovery": "Keep user-authored YAML below the configured project config root.",
    },
    "QLIBX_BOUNDARY_EXECUTION_UNIVERSE": {},
    "QLIBX_BOUNDARY_EXTENSION_PATH": {},
    "QLIBX_BOUNDARY_FEEDBACK_UNCONFIRMED": {
        "recovery": (
            "Drop the events in context.violations. A decision may only see fills Qlib had "
            "already confirmed when it was made."
        ),
    },
    "QLIBX_BOUNDARY_INPUT_MUTATED": {
        "recovery": (
            "Return a new pandas object. What a Strategy is handed is on loan, and mutating it "
            "breaks the digest that reproduces the run."
        ),
    },
    "QLIBX_BOUNDARY_LOOK_AHEAD": {
        "recovery": (
            "Read context.violations: each entry names an observation the decision could not "
            "have known. Trim the dataset to context.decision_time, or register available_at "
            "when the observation timestamp is not when the observation became knowable. Never "
            "move decision_time forward to admit the data -- that silently converts a caught "
            "leak into a backtest that cannot be traded."
        ),
    },
    "QLIBX_BOUNDARY_OUTPUT_PATH": {
        "recovery": "Write derived Parquet only below the configured generated-data root.",
    },
    "QLIBX_BOUNDARY_PARENT_ACCOUNT_MUTATED": {
        "recovery": (
            "Remove the account write from the child program. Nested research explores what-ifs "
            "and holds no authority over the account it branched from."
        ),
    },
    "QLIBX_BOUNDARY_PROJECT_PATH": {
        "recovery": "Select a project-owned path below the project root.",
    },
    "QLIBX_BOUNDARY_SOURCE_PATH": {
        "recovery": "Use a source below the configured read-only source-data root.",
    },
    "QLIBX_BOUNDARY_UNIVERSE_MISMATCH": {},
    "QLIBX_BOUNDARY_USER_CONTENT": {
        "recovery": "Preserve or review user edits; replace only after explicit approval.",
        "requires_user_confirmation": True,
    },
    # -- CONFLICT: This collides with immutable or committed state. Do not overwrite.
    "QLIBX_CONFLICT_ARTIFACT_IDENTITY": {
        "recovery": (
            "Artifact identity is derived from its declared inputs. Change the producer identity "
            "or inputs rather than overwriting the stored envelope."
        ),
    },
    "QLIBX_CONFLICT_IMMUTABLE_CONTENT": {
        "recovery": (
            "The path is write-once. Publish the differing content under its own identity."
        ),
    },
    "QLIBX_CONFLICT_NAV_RECONCILIATION": {
        "recovery": (
            "Do not use the result; the capitalization journal disagrees with the Qlib account."
        ),
    },
    "QLIBX_CONFLICT_PUBLICATION_INCOMPLETE": {
        "recovery": (
            "Run install_publication or recover_publications first; an existing directory is not "
            "evidence of a complete result."
        ),
    },
    "QLIBX_CONFLICT_QUANTITY_RECONCILIATION": {
        "recovery": (
            "Do not use the result. The composite, baseline, and active books disagree, so the "
            "signed projection is not a realized position."
        ),
    },
    "QLIBX_CONFLICT_RECORD_NOT_COMMITTED": {
        "recovery": "Only committed records are readable. Recover interrupted publications first.",
    },
    "QLIBX_CONFLICT_RESULT_IDENTITY": {
        "recovery": (
            "Different content already claims this result key. Compare both records and publish "
            "under a distinct identity instead of replacing the stored one."
        ),
    },
    "QLIBX_CONFLICT_SOURCE_CHANGED": {
        "recovery": (
            "Discard the stale plan, inspect the changed source, and request confirmation again."
        ),
    },
    "QLIBX_CONFLICT_STAGED_ARTIFACT": {
        "recovery": (
            "Prepare the publication again from the current staged files; the plan was built "
            "against different content."
        ),
    },
    "QLIBX_CONFLICT_STALE_DECISION": {
        "recovery": (
            "Another agent decided first. Re-read the target's current decision version and "
            "retry with it; do not overwrite the newer decision."
        ),
    },
    "QLIBX_CONFLICT_STALE_PLAN": {
        "recovery": (
            "The file moved under the plan. Regenerate it and re-review the user-authored "
            "content before applying."
        ),
    },
    # -- CORRUPT: Stored bytes fail their digest. Do not consume them.
    "QLIBX_CORRUPT_ARTIFACT_ENVELOPE": {
        "recovery": "Re-export the bundle; do not import unverified provenance.",
    },
    "QLIBX_CORRUPT_ARTIFACT_PAYLOAD": {
        "recovery": "Do not consume the artifact; reproduce it from its declared inputs.",
    },
    "QLIBX_CORRUPT_EVENT_LOG": {
        "recovery": (
            "Repair or truncate the damaged tail of events/events.jsonl deliberately; qlibx will "
            "not silently skip an unreadable event."
        ),
    },
    "QLIBX_CORRUPT_FROZEN_RUN": {
        "recovery": "Do not reuse the bundle; freeze the run again from its declared inputs.",
    },
    "QLIBX_CORRUPT_RESEARCH_BLOB": {
        "recovery": (
            "Investigate the blob store before republishing; qlibx will not overwrite a blob "
            "whose content no longer matches its address."
        ),
    },
    "QLIBX_CORRUPT_RESEARCH_RECORD": {
        "recovery": "Do not cite this record as evidence; republish the result from its inputs.",
    },
    # -- UNSUPPORTED: This build does not implement that version or format.
    "QLIBX_UNSUPPORTED_BUNDLE_SCHEMA": {
        "recovery": "Export the bundle with a qlibx version that writes schema version 1.",
    },
    "QLIBX_UNSUPPORTED_CATALOG_SCHEMA": {
        "recovery": "Use a logical-dataset schema supported by the installed qlibx version.",
    },
    "QLIBX_UNSUPPORTED_EXECUTION_SCHEMA": {
        "recovery": "Use an execution-profile schema supported by the installed qlibx version.",
    },
    "QLIBX_UNSUPPORTED_MEDIA_TYPE": {
        "recovery": "Stage research artifacts as JSON or parquet; see context['available'].",
    },
    "QLIBX_UNSUPPORTED_PROJECT_SCHEMA": {
        "recovery": "Use a project manifest schema supported by the installed qlibx version.",
    },
    "QLIBX_UNSUPPORTED_SOURCE_FORMAT": {
        "recovery": (
            "Use a supported Parquet or DuckDB source, or convert it outside qlibx with approval."
        ),
    },
    "QLIBX_UNSUPPORTED_STRATEGY_CONTRACT": {},
    "QLIBX_UNSUPPORTED_STRATEGY_SCHEMA": {},
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
            "resolution is serialized unchanged into QLIBX_MISSING_CAPABILITY_REQUIREMENTS context"
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
            "QLIBX_MISSING_REGISTRATION_MAPPING": "Discuss exact mapping; never guess or fallback.",
            "QLIBX_INVALID_PRIMARY_KEY_DUPLICATE": (
                "Resolve duplicate policy outside qlibx, then re-plan."
            ),
            "QLIBX_CONFLICT_SOURCE_CHANGED": "Discard plan and inspect the new source.",
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
            "from qlibx.reporting import analyze_stored_run, render_report\n"
            "from qlibx.storage import ProjectStorage\n"
            "project = Project.load('.')\n"
            "storage = ProjectStorage.from_project(project)\n"
            "envelope = storage.artifacts.load('artifact-id', run_id='run-id')\n"
            "payload = storage.artifacts.load_payload(envelope.artifact_id, run_id='run-id')\n"
            "orders = storage.runs('runs.duckdb').load_table('backtest-run-id', 'orders')\n"
            "document = analyze_stored_run('runs.duckdb', 'backtest-run-id')\n"
            "rendered = render_report(document, 'report.html', renderer='html')\n"
        ),
    },
    "error_response": {
        "format": "json",
        "content": (
            '{"code":"QLIBX_MISSING_REGISTRATION_MAPPING",'
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


def error_family(code: str) -> str:
    """Return the branch of the code tree a code sits on."""
    for family in FAMILY_RECOVERY:
        if code.startswith(f"QLIBX_{family}_"):
            return family
    raise _unknown("error family", code, FAMILY_RECOVERY)


def error_guidance(code: str) -> Mapping[str, Any]:
    """Resolve one code against the tree: its family's guidance, then its own.

    A leaf without a `recovery` is not undocumented -- it is a failure whose family already
    says everything useful, and repeating that text per leaf is what makes two codes look
    distinct when they are not.
    """
    if code not in ERROR_GUIDANCE:
        raise _unknown("error code", code, ERROR_GUIDANCE)
    family = error_family(code)
    return {
        "code": code,
        "family": family,
        "family_recovery": FAMILY_RECOVERY[family],
        **ERROR_GUIDANCE[code],
    }


def _unknown(kind: str, name: str, available: Mapping[str, Any]) -> QlibxError:
    return unknown_name("QLIBX_NOT_FOUND_DOCUMENTATION_TOPIC", kind, name, available)
