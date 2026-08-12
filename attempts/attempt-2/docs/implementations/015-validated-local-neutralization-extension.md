# 015 Validated local neutralization extension

## Intent

Implement UC-EXTENSION-001 without introducing a general plugin framework. A project-local
neutralization transform must declare its semantic inputs, receive only PIT-materialized values,
produce a typed deterministic result, and become discoverable only after package validation
succeeds.

## Implementation

- The public extension contract consists of a versioned `NeutralizationExtensionSpec`, typed input
  rows, typed output values, and `ExtensionValidationRequest`.
- The bundled `group_demean` function is the deterministic built-in example. Project-local modules
  expose `EXTENSION_SPEC` and `transform(request)` using the same models.
- `ExtensionFlow` resolves only the two declared `ComponentRequirement` objects and materializes
  their latest common instrument axis through `ViewGate` at the request's frozen evaluation time.
  Local code never receives the registry, raw observation store, Account, or Strategy Memory.
- Validation rejects empty PIT-visible input, axis mismatch, non-finite output, extension identity
  mismatch, nondeterministic repeated output, and non-zero within-group residuals.
- Successful validation publishes one immutable `extension_registration` artifact containing the
  source hash, spec, access lineage, validation hashes, and typed validation output. The public
  project facade discovers only successful registration artifacts. Failures remain immutable
  `operation_error` artifacts and are not registry entries.
- Module paths are restricted to relative Python files below the configured project extension
  directory. The source content hash participates in both module isolation and logical identity.
- The architecture import guard treats `extensions` as an operation-level package: it may depend on
  context/data contracts, while orchestration remains in `flow`.

## Real-data evidence

The acceptance scenario uses 2024-01-31 close-to-base returns for A000660 and A005930 from
`data/DW/fng_stock_daily_prices.csv`. Both stocks' sector 450000 classification is taken from
`data/preprocessed/sector_classification.parquet` and `industry_mapping.parquet`, whose source is
`data/DW/DW_FNG_FGSC종목_20200101-20260430.csv`.

The sector observation is unavailable at 08:59 KST and becomes visible at the user-confirmed next
trading session, 2024-02-01 09:00 KST. Validation before that cutoff fails without registration.
At the cutoff, an output that merely returns raw values fails the group-neutrality contract and is
also absent from the registry. The corrected local group-demean transform produces the exact
centered real returns, publishes one registration artifact, and exposes access lineage whose
maximum availability does not exceed the evaluation time.

## Trade-offs

This slice intentionally validates one local neutralization contract. It does not provide arbitrary
entry-point discovery, dependency installation, external-process execution, sandboxing of trusted
project code, or a mutable plugin database. New extension kinds should add their own typed contract
and deterministic fixture rather than weaken this boundary.

Registration proves the source content against the recorded validation fixture. A later invocation
facility must verify the current source hash against the registration before execution; this slice
does not silently execute changed code.

## Validation

- Architecture, UC-EXTENSION-001 real-data acceptance, and scenario registry -> 5 passed.
- Full pytest -> 75 tests passed in 54.18s.
- Ruff, Git diff check, and public import smoke -> passed.
- uv build -> built qlibx 0.1.0 sdist and wheel.
