---
name: qlibx
description: Guide PIT-safe qlibx project onboarding, dataset registration, requirement-gap recovery, research execution, artifact inspection, and extension validation. Use when an agent works in a qlibx user project or receives a qlibx OperationError.
---

# qlibx workflow

Use documented public commands and schemas. Do not inspect package internals or reference engines to
invent missing behavior.

## Start an operation

1. Read project status, registered capabilities, reusable artifacts, and the requested outcome.
2. Select only the operations needed for that outcome. Do not force model, ensemble, portfolio,
   execution, monitoring, or reporting stages that the user did not request.
3. Freeze the selected config and run package validation before interpreting a result as complete.

## Register data

1. Inventory the source and inspect a bounded sample.
2. Identify instrument, logical-key, and availability candidates without binding from field names
   alone.
3. Explain look-ahead risk. If availability is ambiguous, compare an actual release timestamp,
   a source-supported delay rule, and source enrichment.
4. Ask the user to choose the economic meaning and the IANA `source_timezone` of any naive
   timestamp. Never assume that a naive source is UTC or local time.
5. Call qlibx registration validation with the confirmed availability and timezone declarations.
6. Record the confirmed binding and validation result. Do not infer available_at from DATE alone.

## Materialize research data

1. Use direct materialization only when a reusable typed research result is actually required. A
   direct Strategy does not require this stage.
2. Inspect the selected operation's declared requirements before invoking it. Forward-return labels
   require explicit `label_start_value`, `label_end_value`, and `horizon_end` bindings.
3. Never infer a horizon or availability delay. If `label.horizon_end` is unresolved, explain the
   compatible choices: bind a source-supported field, register a separate immutable logical dataset,
   derive and validate a dataset, or select a model with different requirements.
4. Retry with a new `MaterializationInvocation`, preserve the prior failure artifact through
   `resolves_error_artifact_id`, and confirm every emitted row has `available_at <= evaluation_time`.
5. Treat `forward_return_label_result:v1` as a label artifact, not a stored signal, Account update,
   or Strategy-state update.

The bundled `forward-label-materialization-v1` sample demonstrates pre-compute requirement failure,
an explicit immutable horizon registration, linked retry, and future-hidden labels through installed
public APIs.

## Compare frozen execution conventions

1. Select exact `decision_intent:v1` artifact IDs. Do not rerun the Strategy or choose a latest
   compatible parent.
2. Use `FrozenDailyExecutionSpec` and `QlibxProject.execute_frozen_daily()` with a distinct Account
   ID for every child.
3. Select `next_session_close` or `next_session_open` explicitly. Next-open requires a non-empty
   `session_opens` calendar; `session_closes` remains required for mark and monitor events.
4. Bind the execution price to an observation actually available at the selected event. Never use a
   close-available row at the open event or silently fall back from open to close.
5. Compare profile/convention IDs, event times, prices, fills, Account before/after, exact parent
   dependency, dataset lineage, limitations, and terminal status.

The bundled `execution-convention-comparison-v1` sample reuses one immutable parent for isolated
next-close and next-open children and demonstrates failure when a close-available price is requested
at the open event.

## Validate a project-local Strategy

1. Treat a local Python module as trusted project code. qlibx path/hash validation is not a hostile-code
   sandbox and does not install dependencies.
2. Keep the module under the configured extension directory. Import documented types from the curated
   top-level `qlibx` surface and expose fixed `STRATEGY_SPEC` plus zero-argument `create_strategy()`.
3. Declare dataset requirements and optional artifact requirements by consumer role. Bind each artifact
   role to an exact artifact ID; never ask qlibx to choose the latest compatible result.
4. Run `qlibx strategy validate <project-root> <request.yaml>`. Compatibility exists only when the
   package returns a successful `strategy_extension_registration:v1` artifact.
5. Inspect registrations with `qlibx strategy list <project-root>`, then pass the selected exact
   registration artifact ID to `QlibxProject.invoke_registered_strategy(...)` or
   `run_daily_registered_strategy(...)`.
6. If source or schema changes, validate again and use the new registration ID. Do not reuse the old
   compatibility claim or overwrite modified sample/user source.

The bundled `strategy-extension-v1` sample demonstrates typed stored-signal input, validation,
registration lineage, exact execution, and safe overwrite refusal through installed public APIs.
The bundled `strategy-composition-v1` sample runs two path-dependent producers with distinct
Account and Strategy-state origins, composes their exact frozen `strategy_result:v4` artifacts without
rerunning them, and executes an exact registered artifact-only consumer on a separate current
Account. Treat inherited source lineage as historical provenance, not as recomputation from the
downstream Account. Strategy state is an explicit JSON input/output value, not a package-selected
latest value or a package-owned durable store.

## Recover an OperationError

1. Report the observed operation, stage path, error code, requirement ID, commit status, and bounded
   diagnostic.
2. Read references/error-recovery.md for the matching error family.
3. Offer only compatible choices: enrich a binding, register another logical dataset, derive a
   dataset, select a less demanding profile, or implement a validated local extension.
4. Ask the user before changing economic meaning, data availability, portfolio constraints,
   execution policy, or production authority.
5. Retry with a new frozen invocation and preserve the failure-to-resolution lineage.

## Protect authority

- In current support, treat requested targets and orders as intent, not actual state.
- Treat only committed MVP simulation fills as current execution feedback.
- Prepared decisions, OMS acknowledgements, and reconciled OMS results describe a future
  production boundary. Do not present them as an available qlibx workflow.
- Never promote failure, partial publication, intended state, or monitoring findings to success.
- Do not silently normalize, coerce, fall back to a parent product policy, or assume unsupported
  short/lifecycle behavior.

## Report the result

Return the selected operation, actual dependencies, terminal status, artifact IDs, warnings or
limitations, commit status, and the smallest safe next action.
