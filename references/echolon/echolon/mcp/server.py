"""echolon-mcp — FastMCP server that wraps the Task 10/11 programmatic APIs.

Launched via the `echolon-mcp` console script. OpenAI Agents SDK consumers
attach via `MCPServerStdio(command="echolon-mcp", args=[])`.

Stdout discipline: under the MCP stdio transport, every byte written to
fd 1 must be a valid JSONRPC message. Any tool implementation that calls
``print(...)`` corrupts the channel and the client tears the server down
with ``Failed to parse JSONRPC message from server`` (e.g. the
``strategy_params_generator`` emits a ``✅ Generated: ...`` line on every
write). ``main()`` defends the channel by handing MCP a private copy of
the real stdout and rebinding ``sys.stdout`` to ``sys.stderr`` for the
duration of the run, so any straggler print lands on stderr instead of
the JSONRPC pipe.
"""
import os
import sys
from io import TextIOWrapper
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from echolon.indicators import catalog as _catalog
from echolon.native import patterns as _patterns
from echolon.native import skills as _skills
from echolon.native import templates as _templates
from echolon.native.errors import get_error_doc as _get_error_doc
from echolon.native.validation import validate_strategy as _validate_strategy
from echolon.strategy.validators.full import validate_strategy_full as _validate_strategy_full


# Generic markdown fetcher constrained to ``echolon/native/``. Resolves to
# the package directory regardless of install location (sdist checkout vs.
# pip-installed wheel).
import echolon.native as _native
_NATIVE_ROOT = Path(_native.__file__).parent


def _not_found(kind: str, name: str, available: list) -> dict:
    """Actionable not-found result for a name-lookup tool.

    Returning ``None`` for an unknown name serializes to an EMPTY MCP content
    list; a ChatCompletions client can't extract a text part and drops it for an
    opaque placeholder (logging "tool outputs cannot be empty…"). An error dict
    that names the valid options is non-empty AND lets the calling agent
    self-correct in one turn instead of guessing again.
    """
    return {
        "error": f"No {kind} named {name!r}. Available {kind}s: {available}",
    }


def build_server() -> FastMCP:
    """Construct and return the FastMCP server with all echolon tools registered."""
    server = FastMCP("echolon")

    @server.tool()
    def validate_strategy(path: str) -> dict:
        """Validate a strategy directory against echolon contracts.

        Args:
            path: Absolute path to the strategy directory.

        Returns a dict with keys: status ("VALID"|"INVALID"), errors (list of dicts).
        """
        result = _validate_strategy(Path(path))
        return {
            "status": result.status,
            "errors": [
                {
                    "code": e.code,
                    "what": e.what,
                    "why": e.why,
                    "fix": e.fix,
                    "docs_url": e.docs_url,
                }
                for e in result.errors
            ],
        }

    @server.tool()
    def get_error_doc(code: str) -> dict:
        """Fetch the structured error documentation for a given error code.

        ``what`` and ``why`` come from the in-memory registry
        (``echolon.errors.ERROR_CATALOG``); the long-form sections (``fix``,
        ``example``, ``common_causes``, ``related``) come from the per-code
        markdown at ``echolon/native/errors/codes/{code}.md``. The full
        markdown body is also returned as ``long_form_markdown`` so an
        agent can consume the prose verbatim if the parsed sections are
        empty (parser-resilience fallback).

        Args:
            code: Error code like 'VAL-001' or 'IND-003'.
        """
        doc = _get_error_doc(code)
        return {
            "code": doc.code,
            "what": doc.what,
            "why": doc.why,
            "fix": doc.fix,
            "common_causes": doc.common_causes,
            "related": doc.related,
            "example": doc.example,
            "long_form_markdown": doc.long_form_markdown,
        }

    @server.tool()
    def list_indicators(has_lookback: bool | None = None) -> list[str]:
        """Return all indicator names in the echolon catalog, optionally filtered by lookback semantics.

        Args:
            has_lookback: Optional filter.
                ``True`` → only indicators with a period-like parameter
                (e.g. RSI, ATR — sweepable single-dim lookback).
                ``False`` → only indicators without a period parameter
                (no-param indicators like OBV, multi-param scalar indicators
                like BBANDS, special-config indicators).
                Omit for all.
        """
        return _catalog.list_all(has_lookback=has_lookback)

    @server.tool()
    def indicator_info(name: str) -> dict | None:
        """Return structured info for one indicator, or None if unknown.

        Keys: ``name``, ``has_lookback``, ``function``, ``file``, ``params``
        (list of ``{name, default, type}`` dicts). Column names emitted at
        runtime by ``processor._build_suffix`` (handles multi-param sweeps).
        """
        info = _catalog.info(name)
        if info is None:
            return None
        return {
            "name": info.name,
            "kind": info.kind,                      # per_contract_talib | curve_carry | regime_classifier
            "compute_source": info.compute_source,  # echolon_pipeline | echolon_curve_stage
            "has_lookback": info.has_lookback,
            "function": info.function,
            "file": info.file,
            "params": info.params,
        }

    @server.tool()
    def indicator_params(name: str) -> list[dict] | None:
        """Return the tunable parameters for an indicator, or None if unknown.

        Convenience accessor — same as ``indicator_info(name)["params"]`` but
        skips the wrapper dict. Each entry is ``{"name": str, "default": any, "type": str}``.
        """
        info = _catalog.info(name)
        if info is None:
            return None
        return info.params

    @server.tool()
    def validate_indicator_list(payload_json: str) -> dict:
        """Validate a flat-dict ``strategy_indicator_list.json`` payload against the catalog.

        Args:
            payload_json: JSON string of the flat-dict
                (e.g. ``'{"rsi": {"timeperiod": [10, 20]}}'``).

        Returns a dict ``{"valid": bool, "errors": [{code, field, message, suggestion}]}``.
        Bad JSON surfaces as a structured error, not a raise.
        """
        import json as _json

        try:
            data = _json.loads(payload_json)
        except _json.JSONDecodeError as e:
            return {
                "valid": False,
                "errors": [{
                    "code": "IND-000",
                    "field": "<payload>",
                    "message": f"Failed to parse JSON: {e}",
                    "suggestion": [],
                }],
            }
        errors = _catalog.validate(data)
        return {"valid": not errors, "errors": errors}

    @server.tool()
    def suggest_similar(name: str, limit: int = 5) -> list[str]:
        """Return up to ``limit`` catalog names close to ``name`` (difflib + substring)."""
        return _catalog.suggest_similar(name, limit=limit)

    @server.tool()
    def scaffold_component(
        kind: str,
        strategy_dir: str,
        force: bool = False,
    ) -> dict:
        """Write a framework-correct scaffold for a strategy component file.

        Produces a minimal stub that matches echolon's loader contract —
        class name + method signature + return schema — but contains no
        trading logic. Coding agents refine the stub into real pathways.

        Args:
            kind: One of ``"entry"``, ``"exit"``, ``"risk"``, ``"sizer"``, ``"strategy"``.
            strategy_dir: Absolute path to the directory where the file is written.
            force: If True, overwrite an existing file. If False (default), refuse
                and return ``success=False`` with ``error="file_exists"``.

        Returns:
            {
                "success": bool,
                "output_path": str (path to the scaffolded file, if success),
                "kind": str (echoes the input),
                "error": str | None (one of: "unknown_kind", "file_exists", None),
                "message": str (human-readable summary),
            }
        """
        from echolon.strategy.generators import (
            generate_entry as _gen_entry,
            generate_exit as _gen_exit,
            generate_risk as _gen_risk,
            generate_sizer as _gen_sizer,
            generate_strategy as _gen_strategy,
        )

        _DISPATCH = {
            "entry":    _gen_entry,
            "exit":     _gen_exit,
            "risk":     _gen_risk,
            "sizer":    _gen_sizer,
            "strategy": _gen_strategy,
        }

        fn = _DISPATCH.get(kind)
        if fn is None:
            return {
                "success": False,
                "output_path": None,
                "kind": kind,
                "error": "unknown_kind",
                "message": f"Unknown kind {kind!r}. Valid: {sorted(_DISPATCH)}",
            }
        try:
            out_path = fn(strategy_dir=strategy_dir, force=force)
        except FileExistsError as e:
            return {
                "success": False,
                "output_path": None,
                "kind": kind,
                "error": "file_exists",
                "message": str(e),
            }
        return {
            "success": True,
            "output_path": str(out_path),
            "kind": kind,
            "error": None,
            "message": f"Scaffolded {kind} at {out_path}",
        }

    @server.tool()
    def validate_debug_completion(
        artifact_path: str,
        log_path: str,
        required_json_keys: list[str] | None = None,
        required_log_markers: list[str] | None = None,
    ) -> dict:
        """Validate post-run debug artifacts landed on disk with the right shape.

        Three deterministic checks:
        - STR-001: ``selected_robust_trial.json`` + log file both exist.
        - VAL-003: artifact JSON parses and carries every required top-level key.
        - BT-010: log contains each required marker substring (order irrelevant).

        Args:
            artifact_path: Absolute path to the JSON artifact (typically
                ``<workspace>/backtest/selected_robust_trial.json``).
            log_path: Absolute path to the debug log file.
            required_json_keys: Top-level keys expected on the artifact.
                Defaults to ``["trial_number", "params", "metrics"]``.
            required_log_markers: Substrings expected in the log. Defaults
                to ``["STAGE 4 COMPLETE", "STAGE 5 COMPLETE", "FINAL SUCCESS"]``.

        Returns ``{"any_errors": bool, "findings": [{"code", "message",
        "context"}, ...]}``. Never raises — parse / file-access failures
        surface as findings with the appropriate error code.
        """
        from echolon.strategy.validators.debug_completion import (
            validate_debug_completion as _impl,
        )
        kwargs = {}
        if required_json_keys is not None:
            kwargs["required_json_keys"] = required_json_keys
        if required_log_markers is not None:
            kwargs["required_log_markers"] = required_log_markers
        report = _impl(artifact_path=artifact_path, log_path=log_path, **kwargs)
        return report.to_dict()

    @server.tool()
    def validate_component_protocol_signatures(strategy_dir: str) -> dict:
        """AST-check that each required component class has the required
        method with a matching return-type annotation (if annotated at all).

        - STR-003: class is missing the required method.
        - VAL-006: method declares a return annotation but it doesn't match
          the expected BaseModel (EntrySignalOutput / ExitSignalOutput / ...).

        Missing annotations are NOT flagged (policy vs correctness — missing
        annotation is a stylistic choice, Pydantic catches runtime
        mismatches). Missing files are silently skipped (preflight STR-001
        territory).

        Returns ``{"any_errors": bool, "findings": [...]}``.
        """
        from echolon.strategy.validators.component_signatures import (
            validate_component_signatures as _impl,
        )
        return _impl(strategy_dir=strategy_dir).to_dict()

    @server.tool()
    def validate_component_integration(strategy_dir: str) -> dict:
        """Import each component module via StrategyLoader and check its
        method arity + ``strategy_params.DEFAULT_PARAMS`` top-level shape.

        - STR-002: module fails to import (= guaranteed runtime failure).
        - PRM-002: DEFAULT_PARAMS missing a required top-level key, or a
          value isn't a dict.
        - VAL-005: method's required-positional arity (after ``self``)
          doesn't match the protocol. Arg NAMES are not checked — the
          framework calls positionally, so names are the author's choice.

        Returns ``{"any_errors": bool, "findings": [...]}``.
        """
        from echolon.strategy.validators.component_integration import (
            validate_component_integration as _impl,
        )
        return _impl(strategy_dir=strategy_dir).to_dict()

    @server.tool()
    def validate_component_smoke(strategy_dir: str) -> dict:
        """Bar-0 smoke: instantiate each component against a stub engine and
        call its trading method once, flagging indicator columns the code
        reads that strategy_indicator_list.json never declared (IND-007).

        Catches the JSON↔code naming drift that the static validators
        (import / signature / DEFAULT_PARAMS shape) cannot — the engine only
        computes declared indicators, so an undeclared read KeyErrors deep in
        the WFA backtest. This surfaces it in seconds.

        Advisory + zero-false-positive by design: the stub's get_indicator
        never raises, detection is base-name based (so valid multi-param
        columns are not mis-flagged), and EVERY other exception
        (instantiation / method crash on the imperfect stub) is swallowed,
        never reported. It is therefore NOT part of validate_strategy_full —
        call it explicitly as a cheap pre-flight before the debugger stage.

        Returns ``{"any_errors": bool, "findings": [...]}``.
        """
        from echolon.strategy.validators.component_smoke import (
            validate_component_smoke as _impl,
        )
        return _impl(strategy_dir=strategy_dir).to_dict()

    @server.tool()
    def validate_component_logging(strategy_dir: str) -> dict:
        """AST-check that each component's required method calls the
        matching ``self.log_<component>_output(...)`` with a BaseModel
        instance (not a dict, not a wrong schema).

        Also flags ``self.params.get(...)`` anywhere in the file (PRM-004 —
        defensive dict-access antipattern on the params container).

        Returns ``{"any_errors": bool, "findings": [...]}``.
        """
        from echolon.strategy.validators.component_logging import (
            validate_component_logging as _impl,
        )
        return _impl(strategy_dir=strategy_dir).to_dict()

    @server.tool()
    def describe_component_api() -> dict:
        """Return the live ``BaseComponent`` + ``IMarketData`` API surface.

        Use this BEFORE writing any component code. The return value is
        produced via ``inspect.signature()`` on the actual classes, so it
        always reflects the current echolon version — there is no skill /
        doc drift. If a method appears here, it exists; if it doesn't, it
        doesn't. Pip-install or editable-install, same answer.

        Returns a dict with shape::

            {
              "BaseComponent": {
                "override_methods": [{"name": ..., "signature": ..., "doc": ...}, ...],
                "helper_methods":   [{...}, ...],
                "properties":       [{"name": ..., "doc": ...}, ...],
              },
              "IMarketData": {
                "methods": [{"name": ..., "signature": ..., "doc": ...}, ...],
              },
            }

        ``override_methods`` are the four BaseComponent stubs each component
        file must override (``generate_signal`` / ``should_exit`` /
        ``can_trade`` / ``calculate_size``). ``helper_methods`` are concrete
        helpers strategies may call (``get_current_bar``, ``get_indicator``,
        ``log_*_output``, etc.). ``properties`` are read-only attribute
        accessors (``self.market_data``, ``self.portfolio``, ``self.params``).

        ``signature`` is the formatted ``inspect.Signature`` (e.g.
        ``"(self, name: str, index: int = 0) -> float"``). ``doc`` is the
        first line of the docstring; full docstrings live on the source.
        """
        import inspect
        from echolon.strategy.component import BaseComponent
        from echolon.strategy.interfaces import IMarketData

        # Names every concrete component file must override. Hardcoded
        # because BaseComponent's stubs raise STR-003 instead of using
        # @abstractmethod, so __abstractmethods__ doesn't capture them.
        OVERRIDE_NAMES = frozenset({
            "generate_signal", "should_exit", "can_trade", "calculate_size",
        })

        def _summarize(member) -> str:
            doc = inspect.getdoc(member) or ""
            return doc.split("\n", 1)[0] if doc else ""

        def _entry(name: str, member) -> dict:
            return {
                "name": name,
                "signature": str(inspect.signature(member)),
                "doc": _summarize(member),
            }

        def _public_methods(cls):
            return [
                (name, member)
                for name, member in inspect.getmembers(cls, predicate=inspect.isfunction)
                if not name.startswith("_")
            ]

        bc_methods = _public_methods(BaseComponent)
        bc_overrides = sorted(
            (_entry(n, m) for n, m in bc_methods if n in OVERRIDE_NAMES),
            key=lambda e: e["name"],
        )
        bc_helpers = sorted(
            (_entry(n, m) for n, m in bc_methods if n not in OVERRIDE_NAMES),
            key=lambda e: e["name"],
        )

        bc_properties = sorted(
            (
                {"name": name, "doc": _summarize(member.fget)}
                for name, member in inspect.getmembers(BaseComponent)
                if not name.startswith("_") and isinstance(member, property)
            ),
            key=lambda e: e["name"],
        )

        imd_methods = sorted(
            (_entry(n, m) for n, m in _public_methods(IMarketData)),
            key=lambda e: e["name"],
        )

        return {
            "BaseComponent": {
                "override_methods": bc_overrides,
                "helper_methods": bc_helpers,
                "properties": bc_properties,
            },
            "IMarketData": {
                "methods": imd_methods,
            },
        }

    @server.tool()
    def validate_parameter_access(strategy_dir: str) -> dict:
        """AST-check for hardcoded threshold literals (PRM-003) and defensive
        ``self.params.get()`` calls (PRM-004) across the 4 component files.

        Highest FP-risk of the B1 validators — PRM-003 findings include
        ``context["severity"] = "warning"`` so callers can treat them as
        non-blocking while the allowlist is tuned. PRM-004 findings are
        always bugs (framework contract violation).

        Allowlist covers: range() args, index slicing, keyword args, default
        args, None comparisons, small integer constants ``{-1, 0, 1, -1.0, 0.0, 1.0}``,
        and string-literal comparisons (framework-defined regime / signal enums).

        Returns ``{"any_errors": bool, "findings": [...]}``.
        """
        from echolon.strategy.validators.parameter_access import (
            validate_parameter_access as _impl,
        )
        return _impl(strategy_dir=strategy_dir).to_dict()

    @server.tool()
    def generate_strategy_params(
        params_file_path: str,
        output_path: str,
        frequency: str = "interday",
    ) -> dict:
        """Generate strategy_params.py from params_to_optimize.json.

        Deterministic code generation: parses the JSON → determines parameter
        ownership across components → emits ComponentParameterTemplate classes
        + framework registration + optuna_search_space with crossover
        constraints → writes the target file. Period parameters that exceed
        the frequency-appropriate indicator cap are auto-clamped and reported.

        Args:
            params_file_path: Absolute path to ``params_to_optimize.json``.
            output_path: Absolute path to write ``strategy_params.py``.
            frequency: ``"interday"`` (caps: TEMA≤62, ADX≤93, default≤180)
                or ``"intraday"`` (caps: TEMA≤500, ADX≤750, default≤1000).

        Returns ``{"success": bool, "output_path": str, "corrections":
        [{"param", "type", "old_*", "new_*", "cap", "category", "changes"?}],
        "message": str}``. Parse / IO failures surface as
        ``success=False`` rather than raising.
        """
        from echolon.strategy.generators import (
            generate_strategy_params as _impl,
        )
        result = _impl(
            params_file_path=params_file_path,
            output_path=output_path,
            frequency=frequency,
        )
        return {
            "success": result.success,
            "output_path": result.output_path,
            "corrections": result.corrections,
            "message": result.message,
        }

    @server.tool()
    def list_patterns() -> list[str]:
        """Return all canonical pattern names."""
        return _patterns.list_patterns()

    @server.tool()
    def get_pattern(name: str) -> dict | None:
        """Return a pattern's structured content, or None if unknown."""
        p = _patterns.get_pattern(name)
        if p is None:
            return _not_found("pattern", name, _patterns.list_patterns())
        return {
            "name": p.name,
            "when_to_use": p.when_to_use,
            "key_idea": p.key_idea,
            "files_to_customize": p.files_to_customize,
            "sketch_code": p.sketch_code,
            "common_errors": p.common_errors,
        }

    @server.tool()
    def list_templates() -> list[str]:
        """Return all shipped strategy template names."""
        return _templates.list_templates()

    @server.tool()
    def load_template(name: str) -> dict | None:
        """Load a template's files. Returns {'name': ..., 'files': {filename: content}}."""
        tpl = _templates.load_template(name)
        if tpl is None:
            return _not_found("template", name, _templates.list_templates())
        return {"name": tpl.name, "files": tpl.files}

    @server.tool()
    def list_skills() -> list[dict]:
        """Return all in-package skills as ``[{name, description}]``.

        Each skill is one ``SKILL.md`` packet under
        ``echolon/native/skills/echolon_api/<name>/``. Description comes
        from the YAML frontmatter ``description:`` field. Use this as a
        directory of "what doctrine is available" before calling
        ``get_skill(name)`` for the body.
        """
        return [
            {"name": name, "description": (_skills.get_skill(name).description if _skills.get_skill(name) else "")}
            for name in _skills.list_skills()
        ]

    @server.tool()
    def get_skill(name: str) -> dict | None:
        """Return one skill's body, or None if unknown.

        Returns ``{name, description, body, body_no_frontmatter}``.
        ``body`` is the full file (including YAML frontmatter); use
        ``body_no_frontmatter`` for the prose alone.
        """
        s = _skills.get_skill(name)
        if s is None:
            return _not_found("skill", name, _skills.list_skills())
        return {
            "name": s.name,
            "description": s.description,
            "body": s.body,
            "body_no_frontmatter": s.body_no_frontmatter,
        }

    @server.tool()
    def get_doc(path: str) -> dict | None:
        """Read any markdown file under ``echolon/native/`` and return its body.

        Generic fallback for content not covered by the dedicated tools
        (``get_pattern``, ``get_skill``, ``get_error_doc``, ``load_template``).
        Useful for skill-cross-reference resolution and supplementary files
        (``echolon/native/skills/SKILLS.md``,
        ``echolon/native/errors/codes/README.md``, template READMEs).

        Args:
            path: Relative path under ``echolon/native/`` (e.g.
                ``"skills/SKILLS.md"``, ``"errors/codes/README.md"``,
                ``"templates/minimal/README.md"``). Absolute paths and
                paths escaping the package root are refused with
                ``error="path_outside_native"``.

        Returns ``{path, body}`` on success, or
        ``{error, message, path}`` on failure (path-traversal attempt,
        file not found, not a markdown file).
        """
        if Path(path).is_absolute():
            return {"error": "path_outside_native", "message": "Absolute paths are not allowed.", "path": path}
        target = (_NATIVE_ROOT / path).resolve()
        try:
            target.relative_to(_NATIVE_ROOT.resolve())
        except ValueError:
            return {"error": "path_outside_native", "message": f"{path} resolves outside echolon/native/.", "path": path}
        if not target.is_file():
            return {"error": "file_not_found", "message": f"{path} is not a file under echolon/native/.", "path": path}
        if target.suffix.lower() != ".md":
            return {"error": "not_markdown", "message": f"{path} is not a .md file.", "path": path}
        return {"path": str(target.relative_to(_NATIVE_ROOT.resolve())), "body": target.read_text()}

    @server.tool()
    def validate_strategy_full(strategy_dir: str) -> dict:
        """Run every shipped validator and return merged findings.

        Composes the individual MCP validators (``validate_strategy`` /
        ``validate_component_protocol_signatures`` /
        ``validate_component_integration`` / ``validate_component_logging``
        / ``validate_parameter_access`` / ``validate_indicator_names``) so an
        agent gets a complete validation report from a single tool call —
        including the JSON↔code indicator contract (IND-001/IND-002), so a VALID
        verdict means the regime/indicator columns the code reads are declared.

        Args:
            strategy_dir: Absolute path to the strategy directory.

        Returns:
            ``{status, any_errors, total_findings, findings: [{code, ...}],
            invocations: [{validator, count}]}``. ``status`` is ``"VALID"``
            iff no findings were reported by any validator.
        """
        return _validate_strategy_full(strategy_dir)

    return server


def _build_isolated_stdout():
    """Return an anyio-wrapped TextIOWrapper that writes to the original fd 1.

    Captured BEFORE we rebind ``sys.stdout`` to stderr, so MCP's JSONRPC
    output keeps flowing to the parent process while user-code prints land
    on stderr.
    """
    import anyio
    real_stdout_fd = os.dup(sys.stdout.fileno())
    real_stdout = TextIOWrapper(
        os.fdopen(real_stdout_fd, "wb", buffering=0),
        encoding="utf-8",
        write_through=True,
    )
    return anyio.wrap_file(real_stdout)


async def _run_with_isolated_stdout(server: FastMCP) -> None:
    """Run FastMCP on stdio with stdout protected from user-code prints."""
    from mcp.server.stdio import stdio_server
    isolated_stdout = _build_isolated_stdout()
    sys.stdout = sys.stderr  # any print() now writes to stderr, not fd 1
    async with stdio_server(stdout=isolated_stdout) as (read_stream, write_stream):
        await server._mcp_server.run(
            read_stream,
            write_stream,
            server._mcp_server.create_initialization_options(),
        )


def _silence_mcp_noise() -> None:
    """Clamp the MCP framework's per-RPC INFO chatter to WARNING+.

    Without this the child process emits ``Processing request of type
    ListToolsRequest`` / ``CallToolRequest`` lines on stderr for every
    handshake; under MCP stdio that lands in the parent terminal and
    interleaves with the agent UI. The lines carry no failure info — only
    request types — so suppressing them is purely cosmetic and safe.
    """
    import logging
    for name in ("mcp", "mcp.server", "mcp.server.lowlevel.server",
                 "mcp.client", "anyio"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)
        logger.propagate = False
        for handler in logger.handlers:
            handler.setLevel(logging.WARNING)


def main():  # pragma: no cover — invoked by `echolon-mcp` console script
    import anyio
    from echolon._internal.structured_logging import install_structured_logging
    install_structured_logging()
    _silence_mcp_noise()
    server = build_server()
    anyio.run(_run_with_isolated_stdout, server)


if __name__ == "__main__":
    main()
