# Forward-label PIT materialization

## Intent

Close `GAP-MATERIALIZATION-PIT-001` for a public direct materialization profile with real
forward-return-label evidence, while preserving the existing Dataset, Strategy, Account, Memory,
artifact, and recovery boundaries.

## Observable outcome

A caller can invoke a typed `MaterializationOperation` through `QlibxProject.materialize()` at a
frozen evaluation time. A forward-label model whose explicit `label.horizon_end` requirement is
unresolved fails before producer calculation and leaves only append-only failure evidence. After a
separate immutable horizon registration, a new invocation can link that exact failure and publish a
`forward_return_label_result:v1` containing only rows available by the evaluation time.

## Responsibilities and flow

The operation declares its dataset requirements and typed output contract. `MaterializationFlow`
validates the contract, verifies any selected prior error, resolves all requirements, creates a
dataset-only `MaterializeView`, invokes the producer, validates the returned payload, and publishes
the result with exact dataset, config, and resolution-error dependencies. The built-in
`ForwardReturnLabelModel` requires exact start-value, end-value, and horizon coverage and computes
simple decimal return as `end_value / start_value - 1`.

Failure publication remains the flow's append-only diagnostic responsibility. The operation cannot
read artifacts, Account, feedback, performance, or Strategy Memory and has no state mutation port.
`ForwardReturnLabelResult` independently enforces deterministic unique keys, finite positive input
values, and `observation_time < horizon_end <= available_at <= evaluation_time`.

## Alternatives and trade-offs

Reusing `stored_signal_result` was rejected because a forward label has different semantics and
availability obligations from a tradable signal. Inferring `horizon_end` from frequency or row
order was rejected because it would silently choose economic meaning and can introduce look-ahead.
Mutating the original price registration during recovery was rejected because dataset registrations
are immutable; recovery adds a separate explicit logical dataset. A scheduler, Model registry,
training framework, and arbitrary project payload registration were deferred because direct
invocation closes the stated PIT boundary without adding unproven lifecycle policy.

## Compatibility and limitations

The change is additive. Existing Strategy, research, execution, registration, catalog, and recovery
contracts are unchanged. The public result is a label artifact, not a stored signal or fitted model.
Current support covers direct invocation and the built-in forward-return model only; scheduled
rolling/expanding materialization, local Model registration, pyqlib adapters, and Account/Memory
mutation remain out of scope. The bundled sample is deterministic contract evidence, not a claim of
predictive quality.

## Validation

Focused materialization, installed-sample, sample-registry, architecture, and real-DW acceptance
checks passed 20 tests in 7.67 seconds. After document promotion, scenario-registry, architecture,
and real-DW acceptance checks passed 7 tests in 1.02 seconds. The complete source suite passed 258
tests in 126.37 seconds. `uv run ruff check .`, the curated top-level public import smoke test, and
`git diff --check` passed.

`uv build` produced `qlibx-0.1.0-py3-none-any.whl` and `qlibx-0.1.0.tar.gz`. Archive inspection
confirmed the forward-label sample runner/manifest and updated bundled qlibx skill/recovery guide in
both artifacts. A fresh Python 3.12.13 environment installed the wheel, and the import resolved to
that environment's `site-packages`. A fresh project then materialized
`forward-label-materialization-v1`: the first invocation failed with
`REQUIREMENT_NOT_RESOLVED` for `label.horizon_end`, the linked retry produced values `0.10` and
`-0.05`, and two later-unavailable rows remained hidden at the earlier evaluation time.
