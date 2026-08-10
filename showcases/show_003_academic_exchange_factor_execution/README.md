# AcademicExchange factor execution showcase

Status: current

Last verified: 2026-08-10T20:16:23+09:00

Verified against: qlibx 0.1.0, implementations 009, 038, 059, and 061

This showcase makes the full academic research path inspectable on a bounded real-DW stock study:

1. a project-local 20-session reversal model materializes typed monthly signals through
   `QlibxProject.materialize()`;
2. qlibx evaluates each exact signal artifact against the following monthly return;
3. a showcase-local Strategy declares and consumes each exact stored-signal artifact, then
   `QlibxProject.invoke()` publishes unit-gross demeaned weights as `strategy_result:v3`;
4. `QlibxProject.construct_portfolio()` converts each exact Strategy result to a
   `hypothetical_signed` portfolio artifact without changing its weights;
5. `QlibxProject.run_academic()` executes the stock targets at the next session close with signed
   fractional quantities and explicit zero friction;
6. independent oracles reconcile Strategy weights, event NAV, quantities, financing balance, and
   turnover.

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
`9.32e-10`, quantity within `5.33e-15`, and turnover within `2.23e-16`; all 23 Strategy weight
vectors exactly matched the independent demeaned-unit-gross oracle. The catalog contains 23 valid
signal→Strategy→portfolio→execution dependency chains. The weak return is reported as observed
evidence rather than selected or promoted factor performance.
