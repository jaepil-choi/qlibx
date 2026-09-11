"""Before a run starts: judge the declaration, and freeze it.

    facts.py     RunFacts -- what one command reads about a run, once
    checks.py    the judgments `vqapr check` reports, collected rather than raised
    freeze.py    names -> values: the refusals a freeze raises, and the freeze itself
    frozen.py    the frozen values the engine reads (FrozenRun, FrozenStrategy, ...)
    verdict.py   one door: judge, then freeze (`preflight`, RunVerdict, RunResources)
"""
