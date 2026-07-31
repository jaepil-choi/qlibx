"""Render aggregated optimization failures for humans and LLM agents.

Two surfaces for the same aggregated data:

* ``render_terminal(...)`` — boxed ASCII block for stderr. Top-N groups with
  count, exemplar traceback, context, docs URL. Designed for a human who
  just ran ``python main.py`` and needs to know "why did nothing work?"
  without scrolling through hundreds of stack traces.

* ``write_json_artifact(...)`` — structured JSON dropped next to the study's
  ``optimization_trials.csv``. Designed for downstream LLM agents
  (debugger, validator) to parse without re-extracting fields from the
  terminal stream.

The ``FailureGroup`` dataclass lives here rather than with
``OptimizationFailure`` because it's a controller-side concept: each
``FailureGroup`` collapses many ``OptimizationFailure`` records that share a
:meth:`OptimizationFailure.group_key` into a single dedup entry with a
count + one exemplar.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from ..engine.failure import OptimizationFailure


@dataclass
class FailureGroup:
    """Dedup bucket for ``OptimizationFailure`` records sharing a group key.

    Keeps one exemplar (the first seen) so the controller can show a full
    traceback per distinct error without paying 1000× memory for 1000
    identical ones. The count + first/last trial number span is enough to
    answer "how pervasive was this?".
    """

    key: Tuple[Any, ...]
    count: int = 0
    first_trial: int = -1
    last_trial: int = -1
    exemplar: Optional[OptimizationFailure] = None


def aggregate(
    groups: Dict[Tuple[Any, ...], FailureGroup],
    failure: OptimizationFailure,
    trial_number: int,
) -> None:
    """Fold ``failure`` into ``groups`` (in-place)."""
    key = failure.group_key()
    g = groups.setdefault(key, FailureGroup(key=key))
    g.count += 1
    if g.first_trial == -1:
        g.first_trial = trial_number
    g.last_trial = trial_number
    if g.exemplar is None:
        # Keep exactly ONE full traceback per group — memory-bounded even
        # when thousands of trials share the same underlying bug.
        g.exemplar = failure


def render_terminal(
    n_trials: int,
    n_failed: int,
    groups: Iterable[FailureGroup],
    window_id: Optional[int] = None,
    top_n: int = 3,
) -> str:
    """Return a boxed ASCII summary suitable for stderr.

    Parameters
    ----------
    n_trials : int
        Total trials attempted in the study/window.
    n_failed : int
        How many of them failed. When zero the caller should not invoke
        this function at all; we still handle the edge case by returning
        an empty string.
    groups : Iterable[FailureGroup]
        Aggregated failures (order irrelevant; function re-sorts by count).
    window_id : int, optional
        WFA window identifier when called per-window. Omitted in
        full-study context.
    top_n : int
        Number of groups to print with exemplar traceback. Any remainder
        is summarized with a "... N additional groups" footer.
    """
    if n_failed == 0:
        return ""

    ordered = sorted(groups, key=lambda g: g.count, reverse=True)
    window_label = f" (window {window_id})" if window_id is not None else ""
    lines = [
        "=" * 80,
        f"⚠  OPTIMIZATION FAILED — {n_failed} of {n_trials} trials failed{window_label}",
        "=" * 80,
    ]
    for i, g in enumerate(ordered[:top_n], 1):
        pct = 100.0 * g.count / n_trials if n_trials else 0.0
        exemplar = g.exemplar
        if exemplar is None:
            lines.append(f"GROUP {i} — {g.count} trials ({pct:.0f}%)  <no exemplar>")
            continue
        code = f"[{exemplar.error_code}]" if exemplar.error_code else ""
        first_line = (exemplar.message.splitlines() or [""])[0]
        lines += [
            f"GROUP {i} — {g.count} trials ({pct:.0f}%)  {code}".rstrip(),
            f"  Error:   {exemplar.error_type}",
            f"  Message: {first_line}",
            f"  Trials:  first={g.first_trial}, last={g.last_trial}",
        ]
        if exemplar.context:
            ctx_items = list(exemplar.context.items())[:4]
            ctx_str = ", ".join(f"{k}={v}" for k, v in ctx_items)
            lines.append(f"  Context: {ctx_str}")
        if exemplar.docs_url:
            lines.append(f"  Docs:    {exemplar.docs_url}")
        if exemplar.traceback:
            tb_tail = exemplar.traceback[-800:].rstrip()
            lines += [
                "  Exemplar traceback:",
                "    " + tb_tail.replace("\n", "\n    "),
            ]
        lines.append("")
    remainder = len(ordered) - top_n
    if remainder > 0:
        lines.append(
            f"  … {remainder} additional group(s) suppressed — see JSON artifact."
        )
    lines.append("=" * 80)
    return "\n".join(lines)


def write_json_artifact(
    out_path: Path,
    n_trials: int,
    n_failed: int,
    n_complete: int,
    groups: Iterable[FailureGroup],
    window_id: Optional[int] = None,
) -> None:
    """Serialize aggregated failures to JSON for downstream agents.

    Output path convention: ``<study_dir>/trial_failure_summary.json`` in
    the full-study case, or ``<wfa_dir>/window_<N>/trial_failure_summary.json``
    per-window. The file survives as the canonical AI-readable breadcrumb;
    LLM debugger prompts read this, not the terminal stream.
    """
    ordered = sorted(groups, key=lambda g: g.count, reverse=True)
    payload: Dict[str, Any] = {
        "window_id": window_id,
        "n_trials": n_trials,
        "n_failed": n_failed,
        "n_complete": n_complete,
        "failure_rate": n_failed / n_trials if n_trials else 0.0,
        "groups": [
            {
                "count": g.count,
                "first_trial": g.first_trial,
                "last_trial": g.last_trial,
                "error": g.exemplar.to_dict() if g.exemplar else None,
            }
            for g in ordered
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=str))
