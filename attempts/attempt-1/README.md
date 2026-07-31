# qlibx

qlibx is a YAML-configured, point-in-time alpha research library that uses Qlib as its required
closed-loop execution engine.

```text
config/qlibx/data/
├── base.yaml
├── registrations.yaml
├── sources.yaml
└── datasets/
    └── market.yaml
```

```python
from qlibx import Project
from qlibx.data import ConfigDrivenDataLoader

loader = ConfigDrivenDataLoader.from_project(Project.load("."))
returns = loader.load_matrix(
    "returns",
    start="2025-01-01",
    end="2025-03-31",
    as_of="2025-03-31",
)
```

User-owned upstream data is read-only. Processed Parquet is written below `data/qlibx/`, while
generated provenance is kept below `.qlibx/`, never mixed into `config/`.

Public capabilities include:

- Interactive, structured data requirements and canonical `data/qlibx/*.parquet` registration.
- Bounded `StrategyDefinition` / `DecisionContext` / `DecisionResult` contracts.
- Deterministic signed-alpha transforms, exposure diagnostics, and fixed/flexible budgets.
- Immutable research records backed by blobs, manifests, append-only events, and a rebuildable
  DuckDB projection.
- Semantic, ticker-signal, holding, and incremental-residual orthogonality comparison.
- Stored-weight ensemble, explicit long-only enhanced-index feasibility, adaptive signed
  StrategyAgent execution through Qlib, attribution, and stored-artifact reporting.
- Idempotent managed agent instructions, generated skills, public help/schema, and trusted
  project-local extensions without editing installed packages.

```text
qlibx docs
qlibx schema
qlibx examples research_workflow
qlibx errors QLIBX_REGISTRATION_MAPPING_MISSING
qlibx agent instruction --target AGENTS.md       # dry-run
qlibx agent instruction --target AGENTS.md --apply
qlibx agent skill --output .agents/skills/qlibx/SKILL.md
```

`qlibx.execution.run_strategy_execution` accepts long-only physical intent by default and signed
active intent when given `SignedExecutionConfig`. The StrategyAgent is called at each Qlib decision
step with prior confirmed active-account feedback; negative weights create Qlib sell orders.
`run_signed_execution` remains the convenience path for an already-stored signed-weight matrix.
The matched-capitalization implementation is explicitly a compatibility mechanism for Qlib's
long-only account; it is not native borrow, margin, recall, or borrow-fee modeling.

The only required canonical time field is `available_at`; it controls point-in-time visibility.
An event or observation date is optional opaque information and is retained or used as a logical
time axis only when the user explicitly maps it. qlibx never infers correction factors or financial
meaning: registration copies only user-confirmed opaque information mappings. The project manifest
selects config, source, generated-data, state, research
and extension roots; the default repository layout is an example, not package-owned state.

Reproducible end-to-end evidence is kept in
`experiments/exp_003_event_time_qlib_pnl` and
`showcases/show_001_real_user_agent_journey`.
