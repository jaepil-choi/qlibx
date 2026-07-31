"""Trial-parameter resolution — flat optuna params → nested component dicts.

The optimizer evaluates trials FRAMEWORK-NATIVELY: the generated
``optuna_search_space(trial)`` (shipped in every strategy dir's
strategy_params.py) writes sampled values directly onto canonical
component-dict keys and returns the complete nested
``{entry_params, exit_params, risk_params, sizer_params}`` dict. That nested
dict is transient — only the FLAT optuna-name dict survives into artifacts
(optimization_trials.csv → selected_robust_trial.json), and the historical
strip-once prefix mappers provably mangle it: single-prefixed canonical names
land on orphan keys nothing reads, bare names are dropped, and in-function
shared copies (e.g. sizer's mirror of exit stop mults) go stale.

``resolve_via_replay`` is the one and only resolver: replaying the generated
search space with ``optuna.trial.FixedTrial(flat_params)`` reproduces the
optimizer's exact nested dict — FIXED params, crossover constraints, and
shared-parameter copies included. There is deliberately NO name-based merge
fallback: a flat-name mapping cannot recover in-function shared copies, so a
caller that cannot replay must fail loudly (PRM-005) rather than guess.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def resolve_via_replay(
    search_space_fn: Callable[..., Dict[str, Any]],
    flat_params: Dict[str, Any],
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Reproduce the optimizer's nested component dict for a recorded trial.

    Replays the generated ``optuna_search_space`` with a FixedTrial seeded from
    the flat params. Extra keys in ``flat_params`` (e.g. the exporter's legacy
    default-fill family) are simply never consumed — FixedTrial only looks up
    suggested names.

    Returns None (logged) when the replay cannot run: a suggested name missing
    from ``flat_params`` (ValueError), a crossover constraint pruning the trial
    (optuna.TrialPruned), or any other failure. Callers must fall back to the
    legacy path — never guess.
    """
    try:
        import optuna

        class _CastingFixedTrial(optuna.trial.FixedTrial):
            """FixedTrial that coerces CSV/JSON round-tripped values back to the
            distribution's type (pandas delivers 18.0 for an int suggestion)."""

            def suggest_int(self, name: str, *args: Any, **kwargs: Any) -> int:
                if name in self._params and self._params[name] is not None:
                    self._params[name] = int(round(float(self._params[name])))
                return super().suggest_int(name, *args, **kwargs)

            def suggest_float(self, name: str, *args: Any, **kwargs: Any) -> float:
                if name in self._params and self._params[name] is not None:
                    self._params[name] = float(self._params[name])
                return super().suggest_float(name, *args, **kwargs)

            def suggest_categorical(self, name: str, choices: Any) -> Any:
                # Canonicalize on ANY match (not only `value not in choices`):
                # cross-type equality means 10.0 passes a [10, 20] membership
                # test and FixedTrial would return the raw float — restore the
                # canonical choice object/type instead.
                if name in self._params:
                    value = self._params[name]
                    for choice in choices:
                        if choice == value or str(choice) == str(value):
                            self._params[name] = choice
                            break
                return super().suggest_categorical(name, choices)

        nested = search_space_fn(_CastingFixedTrial(dict(flat_params)))
    except Exception as exc:  # TrialPruned, ValueError(missing name), anything
        logger.warning(
            "[PARAM_RESOLUTION] replay failed (%s: %s) — caller must fall back",
            type(exc).__name__,
            exc,
        )
        return None

    if not isinstance(nested, dict) or not any(
        key.endswith("_params") for key in nested
    ):
        logger.warning(
            "[PARAM_RESOLUTION] replay returned unexpected shape %r — caller must fall back",
            type(nested).__name__,
        )
        return None
    return nested
