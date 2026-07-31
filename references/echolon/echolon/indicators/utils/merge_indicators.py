"""Merge + load flat-dict indicator configs.

Used by PortfolioTradingRunner when multiple strategies on the same instrument
need different indicators calculated on the same data, and by callers that
load ``strategy_indicator_list.json`` from disk.

Flat-dict format (per echolon/indicators/schema.py::IndicatorList):

    {"<indicator_name>": {"<param>": scalar | list}, ...}
"""
from __future__ import annotations

import json
from typing import Any, Dict, List


def _union_param_values(a: Any, b: Any) -> Any:
    """Union two param values (scalars or lists) into a single value.

    - scalar + scalar (same value) → scalar
    - scalar + scalar (different) → sorted [min, max] (2-element list = inclusive range
      per schema semantics when both are ints)
    - scalar + list / list + scalar → a list whose min/max span both
    - list + list → [min(all), max(all)] when both look like [min, max] int ranges;
      otherwise sorted set union (preserves explicit-values semantics)
    """
    a_list = a if isinstance(a, list) else [a]
    b_list = b if isinstance(b, list) else [b]

    all_ints = all(
        isinstance(v, int) and not isinstance(v, bool)
        for v in (*a_list, *b_list)
    )
    is_2int_range_a = (
        isinstance(a, list) and len(a) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in a)
    )
    is_2int_range_b = (
        isinstance(b, list) and len(b) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in b)
    )

    if all_ints and (is_2int_range_a or is_2int_range_b or not (isinstance(a, list) or isinstance(b, list))):
        lo = min(*a_list, *b_list)
        hi = max(*a_list, *b_list)
        return [lo, hi] if lo != hi else lo

    # explicit-values union (preserves float semantics + multi-element lists)
    seen: list = []
    for v in (*a_list, *b_list):
        if v not in seen:
            seen.append(v)
    if len(seen) == 1:
        return seen[0]
    # sort when the values are all comparable; otherwise keep insertion order
    try:
        return sorted(seen)
    except TypeError:
        return seen


def merge_indicator_lists(configs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Union N flat-dict indicator configs, merging per-param ranges.

    For each indicator name present in any config, merge its param dicts.
    For each param present in multiple configs, widen the range / union the
    explicit values via :func:`_union_param_values`.

    Args:
        configs: List of flat-dict configs. Each config may be empty.

    Returns:
        One flat-dict config union.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for cfg in configs:
        if not cfg:
            continue
        for name, params in cfg.items():
            name_lower = name.lower() if isinstance(name, str) else name
            if name_lower not in merged:
                merged[name_lower] = dict(params) if params else {}
                continue
            existing = merged[name_lower]
            for param_key, param_val in (params or {}).items():
                if param_key not in existing:
                    existing[param_key] = param_val
                else:
                    existing[param_key] = _union_param_values(existing[param_key], param_val)
    return merged


def load_indicator_list(path: str) -> Dict[str, Any]:
    """Load a ``strategy_indicator_list.json`` file as flat-dict.

    Validates against the catalog via
    :class:`echolon.indicators.schema.IndicatorList` — unknown names or shapes
    fail fast before the caller touches the result.
    """
    from echolon.indicators.schema import IndicatorList

    with open(path, "r") as f:
        data = json.load(f)
    IndicatorList.model_validate(data)
    return data
