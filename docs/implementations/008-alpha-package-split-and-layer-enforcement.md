# Alpha package split and layer enforcement

## Why this change exists

`alpha.py` had grown to 1014 lines holding the operation registry, thirteen operations,
the budget-policy registry, and exposure analysis. Operations and weight-scaling rules
are the parts of qlibx designed to keep growing, so a single file was the wrong
container for them.

Separately, the layering described in `docs/qlibx-architecture.md` was enforced by
nothing: no ruff rule, no import-linter contract, no test. It was prose, verified once by
an ad-hoc script. A module could acquire an upward dependency and nothing would notice.

## What outcome it serves

- Adding a signal operation or a scaling rule touches one small file, not a 1000-line one.
- The layering in the architecture document becomes an executable contract rather than a
  description that can silently drift from the code.
- The public import surface that installed examples depend on stays byte-for-byte valid.

## How it works

### Module to package

`alpha` became a package. That transition is transparent to importers, so every
`from qlibx.alpha import X` in the installed examples, the generated skill, and the tests
keeps working with no shim module and no second name for anything.

```text
alpha/
├─ __init__.py        re-exports the whole public surface
├─ contracts.py       OperationContract, TransformResult (shared by registry+operations)
├─ registry.py        OperationSpec, dispatch, pipeline composition
├─ budget.py          weight-scaling policy registry
├─ exposure.py        exposure measurement
└─ operations/        built-ins, grouped by the axis they act on
   ├─ cross_sectional.py
   ├─ time_series.py
   ├─ grouping.py
   └─ selection.py
```

Each operations module owns **both** its implementations and their `OperationSpec`
declarations. There is no central registration table, so a new operation family is a new
file plus one import line in `operations/__init__.py`. Importing the `operations` package
is what registers the built-ins; `alpha/__init__.py` imports it and then derives
`OPERATION_CONTRACTS` from the populated registry.

### Layer enforcement

`tests/test_architecture.py` declares the layers and derives the real import graph from
source with `ast`, resolving each file to the top-level module or package that owns it so
the graph stays at the same granularity after a module becomes a package. It asserts:

- every module is assigned to a layer, and the declaration names no module that no longer
  exists;
- imports go strictly downward;
- kernel modules (`errors`, `serialization`, `optimization`, `orthogonality`) have no
  intra-package dependency;
- the graph is acyclic;
- only `execution` imports `_vendor`;
- `alpha` depends on nothing but `errors`;
- the public module paths still import.

## Decision recorded: what directories are for

Directories are used to **split a module that has grown**, not to express layers.

Layers are defined by the `LAYERS` declaration and import direction. A directory name
enforces nothing in Python, and layered contracts can be checked against flat names just
as well as nested ones, so directories buy communication rather than enforcement. The
public API is module-path-based (`qlibx.alpha`, `qlibx.research`) and is documented in
installed examples that agents copy, so moving public modules under layer directories
would either degrade those names or require shim modules.

Next promotion candidates on the same rule: `documentation` (835 lines, mostly catalog
data that grows as capability requirements land) and `research` (777 lines, with the event
log, blob store, and publication protocol in one class).

## Trade-offs

- `alpha/__init__.py` re-exports 40 names. That is deliberate: it is the price of keeping
  the public import path independent of the internal file layout, and
  `test_public_module_paths_stay_importable` guards it.
- The layer declaration in the test must be updated when a module is added. That is the
  intended cost — `test_every_module_is_assigned_to_a_layer` fails on an unassigned
  module so placement is a decision rather than an accident.
- Splitting registration across operation files means import order matters: the registry
  must exist before any operation module imports it. The package `__init__` enforces this
  ordering in one place.

## Validation

- `uv run ruff check .` and `uv run ruff format --check` — clean.
- `uv run pytest` — 110 passed (96 before; 14 new architecture tests).
- Behavior identity after the split: 13 operations and 2 budget policies register with the
  same names, `OPERATION_CONTRACTS` matches the registry, and every documented public
  import path resolves.
- Three layering guards were mutation-checked and each failed as intended: `alpha`
  importing `project` (`alpha (layer 1) imports project (layer 2)`), `errors` acquiring a
  dependency, and `reporting` importing `_vendor` directly.

## Unrelated observation

`tests/acceptance/test_p0_p1_agent_journey.py` fails intermittently — twice in roughly
twenty full-suite runs, including once on a documentation-only change before this work, so
it predates this refactor. Failing runs finish much faster than passing ones (19s versus
33s, where the test alone takes 23s), which points at an early subprocess failure rather
than an assertion. It could not be reproduced on demand in seventeen attempts. The helper
now reports the command, exit code, stdout, and stderr on failure, because `check=True`
raised without the child's stderr and a non-JSON stdout gave no context at all, which is
why the earlier occurrences were undiagnosable. The flake itself is not fixed.
