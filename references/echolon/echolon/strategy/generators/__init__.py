"""Echolon strategy code generators.

Currently ships five generators:

- :func:`generate_strategy_params` — deterministic Python-code generation of
 ``strategy_params.py`` from a ``params_to_optimize.json`` input. Exposed
 as the ``generate_strategy_params`` tool on the echolon-mcp server.

- :func:`generate_entry` — scaffolding generator for ``entry.py`` component
 stub. Produces a framework-correct minimal entry rule that returns HOLD by
 default — coding agents refine into real pathways.

- :func:`generate_exit` — scaffolding generator for ``exit.py`` component
 stub. Produces a framework-correct minimal exit rule that returns no_exit by
 default — coding agents refine into real pathways.

- :func:`generate_risk` — scaffolding generator for ``risk.py`` component
 stub. Produces a framework-correct minimal risk manager that returns trading
 allowed by default — coding agents refine into real risk checks.

- :func:`generate_sizer` — scaffolding generator for ``sizer.py`` component
 stub. Produces a framework-correct minimal position sizer that returns fixed
 1-unit size by default — coding agents refine into real sizing logic.

- :func:`generate_strategy` — scaffolding generator for ``strategy.py``
 coordinator stub. Produces a framework-correct minimal strategy coordinator
 that subclasses BaseStrategy and dispatches across the 4 components in
 canonical order — coding agents refine with strategy-specific gates or filters.
"""
from echolon.strategy.generators.entry_generator import generate_entry
from echolon.strategy.generators.exit_generator import generate_exit
from echolon.strategy.generators.risk_generator import generate_risk
from echolon.strategy.generators.sizer_generator import generate_sizer
from echolon.strategy.generators.strategy_generator import generate_strategy
from echolon.strategy.generators.strategy_params_generator import (
 GenerationResult,
 StrategyParamsGenerator,
 generate_strategy_params,
)

__all__ = [
 "GenerationResult",
 "StrategyParamsGenerator",
 "generate_strategy_params",
 "generate_entry",
 "generate_exit",
 "generate_risk",
 "generate_sizer",
 "generate_strategy",
]
