# The rest of the agent-facing failures get their stage

Specifies PRD 5.6. Continues `018-portfolio-and-reporting-stages.md`; between them the
promotion work is finished except where the layering forbids it.

## Why this change exists

After 018 the stage vocabulary was complete in the two stages that had been silent, but 40
caller-facing failures elsewhere were still bare `ValueError`. An agent that mistyped a
parameter (`apply_transform("linear_decay", values, windwo=2)`) got a string; the same mistake
one call earlier got a stage and a `context["available"]`. Uneven contracts are worse than
uniformly poor ones, because the agent cannot write one handler.

## What changed

40 sites promoted, judged by the same question as before — *which stage is the caller in, and
could they have caused it?*

| Module | Sites | Stage |
|---|---|---|
| `ensemble` | 5 | `PORTFOLIO` |
| `extensions` | 11 | `ONBOARDING` / `ALPHA` / `REPORTING` |
| `alpha/registry`, `alpha/budget`, `alpha/exposure`, `alpha/operations/*` | 23 | `ALPHA` |
| `onboarding` | 1 | `ONBOARDING` |

**`extensions` splits across three stages, and that is the point.** Loading an extension is
adding capability to the project (`ONBOARDING`); running a `signal_transform` on data is `ALPHA`;
an `exposure_analyzer` or `report_renderer` is `REPORTING`. A stage names where the agent is
standing, not which file raised. Assigning one stage per module would have been faster and would
have taught the agent the wrong thing.

`context` carries what the agent has to know before it can act: `declared` and `unknown`
parameter names, `available` metrics, `insufficient_dates` with examples, the `extension_root` a
source must sit under, the names a module actually defines when the declared callable is absent.

## What was left alone, and why

- **Kernel modules cannot raise `QlibxError`.** `optimization` (22), `requirements` (5) and
  `serialization` (2) are layer 0, where `test_kernel_has_no_intra_package_dependencies` forbids
  importing `errors`. This is not an oversight: `LinearConstraint` and `OptimizerConfig` are
  re-exported publicly, so a caller does receive a stageless failure. Fixing it means deciding
  whether those modules belong in the kernel — a layering decision, not a refactor.
- **`skill.py`'s single `ValueError` is inside a generated example file**, the body of
  `examples/exponential-decay.py` that the user's own extension will contain. Promoting it would
  make installed example code import qlibx internals to validate its own parameter.
- **`TypeError` for a custom renderer returning the wrong type** stays a `TypeError`. It is a
  type contract, not a journey failure.

## Invariants

No new test file. The three existing tests that asserted the old type now assert the new
contract, which is strictly more than they checked before:

- `test_top_bottom_fails_instead_of_selecting_one_name_on_both_sides` — stage plus
  `context["insufficient_dates"]`.
- `test_unknown_operation_and_parameter_fail_explicitly` — the misspelled parameter case now
  asserts `context["declared"] == ["window"]`, so the agent is shown the correct spelling rather
  than left to guess it.
- `test_installed_example_builds_valid_project_local_exponential_decay` — an extension source
  outside the root reports `ONBOARDING` and names `extension_root` in context.

The generated skill's stage notes were updated in the same pass: `ALPHA` and `RESEARCH_RECORD`
now say which kernel checks still arrive unclassified, so the reference does not promise a
`stage` field that will not always be there.

## Validation

- `uv run pytest`: `164 passed`, unchanged from `5274fb8` — this task moved contracts rather than
  adding behavior, and the three edited tests are the ones that had to move with it.
- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- Bare `ValueError` outside `_vendor`, before and after: 40 in nine agent-facing modules → 0.
  The 29 that remain are all in layer 0.

## Still open

The kernel question is now the only thing between the package and a uniform agent-facing failure
contract. `optimization` is the one that matters — it is the only kernel module whose types a
caller constructs directly.
