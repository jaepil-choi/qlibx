"""Validate indicator names match between JSON declaration and code usage."""

import json
import re
from pathlib import Path

from echolon.errors import EchelonError, ERROR_CATALOG

_GET_INDICATOR_PATTERN = re.compile(
    r"""get_indicator\(\s*['"]([^'"]+)['"]\s*\)""",
)

# Vintage-suffixed regime column ({base}__fit{YYYYMMDD}) — declaring the
# suffixed name also declares its base, so the dedicated regime accessors
# (IND-002 scan below) accept it. Mirrors catalog._RE_FIT_SUFFIX.
_FIT_BASE = re.compile(r"^(.+)__fit[0-9]{8}$")

# Regime/session classifier columns are read through DEDICATED accessors
# (``self.get_market_regime()`` / ``self.get_session_phase()``), NOT through
# ``get_indicator('...')`` — so the IND-001 scan above never sees them. The
# trailing ``\(`` anchors the method name so ``get_session_phase_agg(`` does not
# partial-match. Literal ``column='...'`` kwargs are validated when present;
# dynamic column variables are outside this static regex's scope.
_REGIME_ACCESSOR_PATTERN = re.compile(
    r"""\.get_(market_regime|session_phase)\s*\((?P<args>[^)]*)\)""",
    re.DOTALL,
)
_COLUMN_KWARG_PATTERN = re.compile(
    r"""(?:^|,)\s*column\s*=\s*['"]([^'"]+)['"]""",
    re.DOTALL,
)

_PY_FILES_TO_SCAN = ("entry.py", "exit.py", "risk.py", "sizer.py", "strategy.py")


def _make_error(code: str, **context_vars):
    entry = ERROR_CATALOG[code]
    try:
        fix = entry["fix_template"].format(**context_vars)
    except KeyError:
        fix = entry["fix_template"]
    return entry["class"](
        code=code, what=entry["what"], why=entry["why"], fix=fix,
        context=dict(context_vars),
        docs_url=f"https://github.com/dolphinquant/echolon/blob/master/echolon/native/errors/codes/{code}.md",
    )


def _get_declared_indicator_names(strategy_dir: Path) -> set[str]:
    """Return the set of indicator column names declared by the strategy's JSON.

    Reads the flat-dict format (``{name: {param: value_or_list}}``). For lookback
    indicators, the ``timeperiod`` param expands to one entry per period
    (``rsi_10``, ``rsi_11``, …). Non-lookback indicators contribute their bare name.
    """
    from echolon.indicators.schema import expand_param

    json_path = strategy_dir / "strategy_indicator_list.json"
    if not json_path.exists():
        return set()
    try:
        data = json.loads(json_path.read_text())
    except json.JSONDecodeError:
        return set()
    if not isinstance(data, dict):
        return set()

    declared: set[str] = set()
    for name, params in data.items():
        name_lower = str(name).lower()
        # A vintage-suffixed name ({base}__fitYYYYMMDD) also declares its base,
        # so the dedicated regime accessors pass IND-002 — regardless of which
        # param-shape branch the entry takes below.
        m = _FIT_BASE.match(name_lower)
        if m:
            declared.add(m.group(1))
        if not isinstance(params, dict) or not params:
            declared.add(name_lower)
            continue
        timeperiod = params.get("timeperiod")
        if timeperiod is None:
            declared.add(name_lower)
            continue
        for period in expand_param(timeperiod):
            if isinstance(period, (int, float)):
                declared.add(f"{name_lower}_{int(period)}")
            else:
                declared.add(name_lower)
    return declared


def _declares_column_or_fit_base(column: str, declared: set[str]) -> bool:
    column_lower = column.lower()
    if column_lower in declared:
        return True
    fit_base = _FIT_BASE.match(column_lower)
    return bool(fit_base and fit_base.group(1) in declared)


def validate_indicator_names(strategy_dir: Path) -> list[EchelonError]:
    """Check that all indicator names used in code are lowercase.

    Requires strategy_indicator_list.json to exist (otherwise returns []);
    the JSON is the contract that declares indicator availability.
    """
    strategy_dir = Path(strategy_dir)
    errors: list[EchelonError] = []
    json_path = strategy_dir / "strategy_indicator_list.json"
    if not json_path.exists():
        return errors
    # `declared` is only needed for the regime-accessor check below; IND-001
    # (casing) is detectable purely from the code (uppercase chars in the
    # get_indicator argument).
    declared = _get_declared_indicator_names(strategy_dir)
    # One missing declaration == one fix: flag each undeclared regime column
    # once (at its first call site) rather than per-call, so a single fix isn't
    # buried under N near-identical findings.
    regime_flagged: set[str] = set()
    for filename in _PY_FILES_TO_SCAN:
        file_path = strategy_dir / filename
        if not file_path.exists():
            continue
        content = file_path.read_text()
        for match in _GET_INDICATOR_PATTERN.finditer(content):
            name = match.group(1)
            if name != name.lower():
                errors.append(_make_error(
                    "IND-001", code_name=name, json_name=name.lower(), file=filename,
                ))
        # IND-002: a dedicated regime/session accessor requires its column to be
        # declared. This fires at preflight instead of as a Stage-2 backtest
        # KeyError minutes into the run.
        for match in _REGIME_ACCESSOR_PATTERN.finditer(content):
            accessor_column = match.group(1)
            column_kwarg = _COLUMN_KWARG_PATTERN.search(match.group("args"))
            column = (
                column_kwarg.group(1).lower()
                if column_kwarg is not None
                else accessor_column
            )
            if (
                not _declares_column_or_fit_base(column, declared)
                and column not in regime_flagged
            ):
                regime_flagged.add(column)
                line = content[: match.start()].count("\n") + 1
                errors.append(_make_error(
                    "IND-002", indicator=column, file=filename, line=line,
                ))
    return errors
