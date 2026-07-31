# One storage door, and one payload implementation behind it

## Why this change exists

A finished project keeps results in three places, and a caller had to know all three:

```python
from qlibx.artifacts import ArtifactStore  # 1
from qlibx.research import ResearchCatalog  # 2
from qlibx.run_catalog import open_run_catalog  # 3

store = ArtifactStore.from_project(project)
catalog = ResearchCatalog.from_project(project)
runs = open_run_catalog(some_path)  # ...and this one wants a path
```

Three names, three import paths, three construction idioms — one of which takes a file path
while the other two take the project. "Where did my result go" is one question.

## What the review asked for, and what was actually there

The review filed this as "3 stores to 1 store + 3 views", sized large. Reading the code
first changed the shape of the work, and that is worth recording:

- **`RunCatalog` cannot be merged.** It is 13 lines re-exporting *vendored*
  `_vendor.qlib_engine.store.RunCatalog`. It is one of only two entries in
  `VENDOR_GATEWAYS`, and `test_reporting_does_not_depend_on_the_execution_engine` exists so
  that `reporting` does not reach stored runs through the execution runtime. Merging it
  would rebuild that coupling, around third-party code this package only reads.
- **The other two share almost nothing.** `ArtifactStore` is run-local content-addressing
  with export bundles; `ResearchCatalog` is a staged publication protocol with an
  append-only event log, two-phase commit, file locking and a DuckDB projection. Neither is
  a view of the other. The only real overlap was the payload vocabulary.

So this is a front door plus one small extraction, not one storage engine. The user chose
that scope after the finding was reported.

## What changed

**A. `qlibx/storage.py` (new, layer 5) — `ProjectStorage`.**

```python
storage = ProjectStorage.from_project(project)
storage.artifacts.load(artifact_id, run_id=run_id)
storage.research.list_results()
storage.runs(catalog_path).load_table(run_id, "orders")
```

Purely additive: every original import still works. `runs` stays a method taking an explicit
path, because a run catalog is written by an execution that chooses where it lives, unlike
artifacts and research whose roots the project declares.

`Project` itself could not host this. `project` is layer 2 and the stores are layers 3–4, so
`project.storage` would be an upward import — and a function-level import would not hide it,
because `test_architecture.py` walks every AST node. A module above them is the only correct
home, which the layering test confirmed by staying green.

**B. `serialization.write_payload` / `read_payload` / `PayloadFormat`.**

Both stores wrote and read the same two formats under different names — `"parquet"`/`"json"`
in artifacts, `"application/x-parquet"`/`"application/json"` in research — each with its own
dispatch. One implementation now serves both. Records on disk keep their media type, mapped
at the research boundary by `_MEDIA_TYPE_FORMATS`, so already-published records stay
readable and `QLIBX_UNSUPPORTED_MEDIA_TYPE` stays reachable.

The primitive is in `serialization` (layer 0) because both stores can reach it there. It
raises `ValueError` for an unknown format rather than a `QlibxError`; the kernel cannot
import `errors`, so callers that store their own spelling map it at their boundary and raise
their own code.

After the move `artifacts.py` no longer imports pandas at all — a decent sign the extraction
was real rather than cosmetic.

## Two things the tests caught in my own work

- **A false claim in a docstring.** I wrote that deferring the `run_catalog` import keeps
  `ProjectStorage` from paying for DuckDB. It does not: `research.py:16` imports duckdb at
  module scope, so the door costs it either way. What the deferral actually buys is that
  `_vendor.qlib_engine.store` stays unloaded until a caller asks for a run. The test now
  asserts that, which is the claim that is true.
- **Parquet does not preserve `DatetimeIndex.freq`.** Pre-existing — the old
  `_write_payload` behaved identically — but previously unrecorded. The round-trip test pins
  it explicitly rather than working around it with `check_freq=False` and moving on, because
  code assuming a stored frame is still a regular series would be wrong.

## Trade-offs

- `ProjectStorage` is a pointer object, not an abstraction. It deliberately exposes the three
  stores by their own types rather than wrapping them: a wrapper would have to re-export
  three quite different APIs and would go stale every time one of them grew a method.
- `analyze_stored_run(catalog_path, run_id)` in `reporting` still takes a path and was left
  alone. Routing it through `ProjectStorage` would make `reporting` (layer 5) import
  `storage` (layer 5) — a sideways import the layering forbids. The door offers `runs`
  alongside it rather than replacing it.
- `qlibx.__all__` grows to 16, which is the ceiling `test_root_api_is_small_and_responsibility_based`
  asserts. The next public module has to displace one or move the ceiling deliberately.

## Validation

- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- `uv run pytest` — `138 passed, 1 failed`, up from the 134-test baseline by the four new
  serialization tests. The failure is the pre-existing Windows `cp949` console-codec error in
  `tests/acceptance/test_p0_p1_agent_journey.py`.
- Two tests were edited, both deliberately: `test_architecture.py` gains `storage` in layer 5
  and `test_public_contracts.py` gains it in `__all__`. Both exist so that adding a public
  module is an explicit act — editing them is the intended way to add one, not a workaround.
- The agent-facing `artifact_reporting` example in `documentation.py` now uses the door. A
  front door nobody is told about is not a front door.
