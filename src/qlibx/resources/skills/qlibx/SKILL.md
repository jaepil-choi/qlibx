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
4. Ask the user to choose the economic meaning, then call qlibx registration validation.
5. Record the confirmed binding and validation result. Do not infer available_at from DATE alone.

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

- Treat requested targets, orders, prepared decisions, and acknowledgements as intent, not actual
  state.
- Treat only committed simulation fills or reconciled OMS results as execution feedback.
- Never promote failure, partial publication, intended state, or monitoring findings to success.
- Do not silently normalize, coerce, fall back to a parent product policy, or assume unsupported
  short/lifecycle behavior.

## Report the result

Return the selected operation, actual dependencies, terminal status, artifact IDs, warnings or
limitations, commit status, and the smallest safe next action.
