from qlibx.execution import SignedExecutionConfig, run_strategy_execution
result = run_strategy_execution(
    definition, strategy_program, execution_price=execution_price,
    valuation_price=valuation_price, universe=universe, observed=observed,
    tradable=tradable, volume=volume, initial_cash=5_000_000_000.0,
    signed=SignedExecutionConfig(
        observed=observed, shortable=shortable,
        active_booksize=1_000_000_000.0,
    ),
)
assert result.mode == 'matched_capitalization'
assert result.reconciliation['passed']
