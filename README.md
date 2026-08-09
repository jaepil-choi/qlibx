# qlibx

qlibx is a PIT-safe quantitative research and daily full-fill simulation engine under active
development.

- Requires Python 3.11 or newer (below 3.13).
- The second attempt starts from the minimal package scaffold in `src/qlibx/`.
- The canonical requirements are in [`docs/qlibx-prd.md`](docs/qlibx-prd.md).
- The first implementation is preserved under [`attempts/attempt-1/`](attempts/attempt-1/).

Current support covers registered stock/ETF data, direct and stored-signal research, optional
portfolio construction, deterministic daily simulation, monitoring, analysis/reporting, and
validated project-local neutralization transforms, exact-ID validated project-local Strategy
research/daily execution, and frozen multi-source path-dependent Ensemble composition with complete
source lineage. Intraday/partial-fill execution, real short, derivatives, actual settlement, and
production OMS reconciliation are not current runtime features.

Project onboarding is preview-first. The JSON result lists the exact changes, post-apply validation,
and a `validation_argv` preview command. Removal deletes only manifest-owned generated files and the
qlibx-managed HTML-comment block; it never deletes `AGENTS.md` or `CLAUDE.md` and preserves untracked
skill extensions.

```powershell
uv run qlibx project onboard qlibx-research --target codex
uv run qlibx project onboard qlibx-research --target codex --apply
uv run qlibx project onboard qlibx-research --target codex --remove
uv run qlibx project onboard qlibx-research --target codex --remove --apply
```

To materialize the version-matched opt-in sample without changing files first:

```powershell
uv run qlibx project init qlibx-research --apply
uv run qlibx project sample qlibx-research
uv run qlibx project sample qlibx-research --apply
uv run python qlibx-research/examples/qlibx_owned/basic/run.py qlibx-research

uv run qlibx project sample qlibx-research --sample-id daily-closed-loop-v1 --apply
uv run python qlibx-research/examples/qlibx_owned/daily_closed_loop/run.py qlibx-research
uv run qlibx project sample qlibx-research --sample-id constraint-workflow-v1 --apply
uv run python qlibx-research/examples/qlibx_owned/constraint_workflow/run.py qlibx-research
uv run qlibx project sample qlibx-research --sample-id strategy-extension-v1 --apply
uv run python qlibx-research/examples/qlibx_owned/strategy_extension/run.py qlibx-research
uv run qlibx project sample qlibx-research --sample-id strategy-composition-v1 --apply
uv run python qlibx-research/examples/qlibx_owned/strategy_composition/run.py qlibx-research
uv run qlibx strategy list qlibx-research

uv run qlibx artifact list qlibx-research
```

Local Strategy modules are trusted project code, not sandboxed plugins. qlibx confines and hashes
the selected file, validates two fresh instances, and executes only the exact registration artifact
ID supplied by the caller. A source/schema change requires a new validation and explicit new ID;
there is no implicit latest-compatible selection.
