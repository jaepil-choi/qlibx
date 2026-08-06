# qlibx

qlibx is a PIT-safe quantitative research and daily full-fill simulation engine under active
development.

- The second attempt starts from the minimal package scaffold in `src/qlibx/`.
- The canonical requirements are in [`docs/qlibx-prd.md`](docs/qlibx-prd.md).
- The first implementation is preserved under [`attempts/attempt-1/`](attempts/attempt-1/).

Current support covers registered stock/ETF data, direct and stored-signal research, optional
portfolio construction, deterministic daily simulation, monitoring, analysis/reporting, and
validated project-local neutralization transforms. Intraday/partial-fill execution, real short,
derivatives, actual settlement, and production OMS reconciliation are not current runtime features.

To materialize the version-matched opt-in sample without changing files first:

```powershell
uv run qlibx project init qlibx-research --apply
uv run qlibx project sample qlibx-research
uv run qlibx project sample qlibx-research --apply
uv run python qlibx-research/examples/qlibx_owned/basic/run.py qlibx-research
uv run qlibx artifact list qlibx-research
```
