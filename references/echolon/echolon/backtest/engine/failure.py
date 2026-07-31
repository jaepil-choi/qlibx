"""Structured failure record for optimization trials.

Carries the error code, context dict, and truncated traceback across the
worker→controller process boundary, so the controller (running in the
parent process) can dedup, surface, and serialize failures for downstream
agents.
"""
from __future__ import annotations

import traceback as _tb
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


_TB_MAX_CHARS = 4096   # keep per-failure traceback bounded
_MSG_MAX_CHARS = 1024  # keep message bounded (error messages with multi-line
                       # Pydantic ValidationErrors can be long)


@dataclass
class OptimizationFailure:
    """One trial's failure in machine-readable form.

    Fields map 1:1 to what an LLM agent (debugger, validator) needs to act:
    - ``error_type`` / ``error_code``: route to a specific fix pattern.
    - ``message``: human-readable summary (bounded length).
    - ``traceback``: full-ish stack for root-cause identification.
    - ``context``: structured key/value metadata from EchelonError
      (bar_index, trading_date, contract, component, method, …).
    - ``trial_params``: the parameter set being tested when the failure
      occurred — needed to reproduce the single trial in-process.
    - ``docs_url``: pointer to the catalog entry; the agent can WebFetch it.
    """

    error_type: str
    error_code: Optional[str] = None
    message: str = ""
    traceback: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    trial_params: Dict[str, Any] = field(default_factory=dict)
    docs_url: Optional[str] = None

    @classmethod
    def from_exception(
        cls,
        exc: BaseException,
        trial_params: Optional[Dict[str, Any]] = None,
    ) -> "OptimizationFailure":
        """Build a structured failure from a live exception.

        Extracts EchelonError's structured fields (``code``, ``context``,
        ``docs_url``) when present; otherwise falls back to the generic
        exception attributes. The traceback is tail-truncated so a group
        with ``count=1000`` still fits in a bounded JSON artifact.
        """
        code = getattr(exc, "code", None)
        ctx = dict(getattr(exc, "context", {}) or {})
        docs = getattr(exc, "docs_url", None)

        # Strip leading whitespace so the Message line in the terminal
        # summary isn't empty. EchelonError.__str__ starts with "\n" by
        # design (the CLI rendering wants the block to begin on its own
        # line), which meant ``message.splitlines()[0]`` was "" for every
        # EchelonError — the group header printed ``Message:`` with
        # nothing after it. Stripping preserves the downstream rendering
        # while making the first line informative.
        message = (str(exc) or exc.__class__.__name__).lstrip()
        if len(message) > _MSG_MAX_CHARS:
            message = message[:_MSG_MAX_CHARS] + "…"

        # Stack frames only — NOT ``format_exception`` which appends the
        # exception's own ``__str__`` at the tail. For EchelonError that's
        # another ~500 chars of what/why/fix/context decoration that we
        # already capture in ``message`` + ``context`` + ``docs_url``, and
        # it crowds out the actual stack frames when the 4KB tail-slice
        # fires. ``format_tb`` gives the raw "File … line …, in …" frames.
        frames = _tb.format_tb(exc.__traceback__)
        tb = "Traceback (most recent call last):\n" + "".join(frames)
        # Append a short terminator so consumers can distinguish end-of-tb
        # from EchelonError's own formatting.
        tb += f"{type(exc).__name__}: {message.splitlines()[0] if message else ''}\n"
        if len(tb) > _TB_MAX_CHARS:
            # Tail-truncate: the innermost frame (where the error actually
            # happened) is at the end, so we keep that.
            tb = "…(traceback truncated)…\n" + tb[-_TB_MAX_CHARS:]

        return cls(
            error_type=type(exc).__name__,
            error_code=code,
            message=message,
            traceback=tb,
            context=ctx,
            trial_params=dict(trial_params or {}),
            docs_url=docs,
        )

    def group_key(self) -> tuple:
        """Dedup key used by the controller to aggregate identical failures.

        Two failures collapse into one group iff they share:
        - exception type
        - echolon error code (or both None)
        - first 120 chars of the first line of the message

        This keeps "1000 identical Pydantic ValidationErrors" as a single
        group with ``count=1000`` rather than 1000 duplicate tracebacks.
        """
        first_line = (self.message or "").splitlines()[0][:120] if self.message else ""
        return (self.error_type, self.error_code, first_line)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serializable representation for ``trial_failure_summary.json``."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OptimizationFailure":
        """Reconstruct after IPC / JSON round-trip."""
        return cls(
            error_type=data.get("error_type", "UnknownError"),
            error_code=data.get("error_code"),
            message=data.get("message", ""),
            traceback=data.get("traceback", ""),
            context=data.get("context") or {},
            trial_params=data.get("trial_params") or {},
            docs_url=data.get("docs_url"),
        )


__all__ = ["OptimizationFailure"]
