# AcademicExchange factor execution showcase

Status: current

Last verified: 2026-08-10

Verified against: qlibx 0.1.0, implementations 009, 059, and 061

This showcase makes the full academic research path inspectable on a bounded real-DW stock study:

1. a project-local 20-session reversal model materializes typed monthly signals through
   `QlibxProject.materialize()`;
2. qlibx evaluates each exact signal artifact against the following monthly return;
3. each signal is converted to a unit-gross `hypothetical_signed` portfolio artifact;
4. `QlibxProject.run_academic()` executes the stock targets at the next session close with signed
   fractional quantities and explicit zero friction;
5. an independent ledger reconciles event NAV, quantities, financing balance, and turnover.

The run uses a fixed 12-stock universe and complete-common-session filter. That introduces
survivorship and retrospective-selection bias, so the output demonstrates workflow correctness,
not factor quality or deployable alpha. Academic short positions do not model borrow, locate,
collateral, margin, dividends, market impact, or real execution.

Reproduce from the repository root:

```powershell
uv run python showcases/show_003_academic_exchange_factor_execution/run.py
```

Then open `outputs/report.html`. Machine-readable evidence is stored beside it in `summary.json`,
`periods.csv`, `fills.csv`, and `catalog.json`. Generated files remain below the showcase's ignored
`outputs/` directory.

The verified run produced 23 monthly rebalances and 276 hypothetical stock fills. Negative
positions were observed and every serialized cost term was zero. Final NAV from an initial
1,000,000 was 844,291.30 (`-15.57%`). The independent ledger reconciled event NAV within
`9.32e-10`, quantity within `5.33e-15`, and turnover within `2.23e-16`. The weak return is reported
as observed evidence rather than selected or promoted factor performance.
