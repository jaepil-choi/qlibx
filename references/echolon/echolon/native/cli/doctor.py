"""`echolon doctor` — pre-flight check for runtime dependencies.

Validates that the dependencies echolon's pipelines actually need at
runtime are importable. Catches the well-known ta-lib install pain
(C library not on PATH) and the optional-dep gaps (akshare missing
for `echolon init --market SHFE`).
"""
from __future__ import annotations
import platform
import sys

import typer


def doctor_command(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON for agents/CI"),
) -> None:
    """Pre-flight check: confirm critical runtime deps are importable."""
    checks = [
        _check_talib(),
        _check_akshare(),
        _check_backtrader(),
        _check_optuna(),
    ]
    if json_output:
        import json as _json
        _json.dump({
            "ok": all(c["ok"] for c in checks),
            "platform": f"{platform.system()} {platform.machine()} python={sys.version_info[:2]}",
            "checks": checks,
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for c in checks:
            mark = "✓" if c["ok"] else "✗"
            typer.echo(f"  {mark} {c['name']:<20} {c['detail']}")
            if not c["ok"] and c.get("hint"):
                for line in c["hint"].splitlines():
                    typer.echo(f"      {line}")

    raise typer.Exit(0 if all(c["ok"] for c in checks) else 1)


def _check_talib() -> dict:
    """ta-lib is the worst install offender historically. Modern TA-Lib
    on PyPI ships prebuilt wheels for cp310-cp312 on linux-x86_64, macOS
    (x86_64+arm64), and windows-x86_64. Edge platforms (Linux ARM64,
    Alpine, FreeBSD, py3.13+) need to build the C library by hand."""
    try:
        import talib
        return {
            "name": "ta-lib", "ok": True,
            "detail": f"talib import works (version {getattr(talib, '__version__', '?')})",
        }
    except ImportError as e:
        sys_info = f"{platform.system()}/{platform.machine()} python{sys.version_info.major}.{sys.version_info.minor}"
        return {
            "name": "ta-lib", "ok": False,
            "detail": f"import talib failed ({e}); platform={sys_info}",
            "hint": (
                "TA-Lib needs the underlying C library. Try:\n"
                "  Linux (Debian/Ubuntu): apt install ta-lib0 ta-lib-dev && pip install --force-reinstall TA-Lib\n"
                "  macOS:                  brew install ta-lib && pip install --force-reinstall TA-Lib\n"
                "  Windows:                pip install TA-Lib  (wheels ship for cp310-312 x86_64)\n"
                "If you're on a platform without prebuilt wheels (Linux ARM64, Alpine, py3.13+),\n"
                "build from source: https://ta-lib.org/install.html"
            ),
        }


def _check_akshare() -> dict:
    try:
        import akshare  # noqa: F401
        return {
            "name": "akshare",
            "ok": True,
            "detail": "available (needed for `echolon init --market SHFE`)",
        }
    except ImportError:
        return {
            "name": "akshare",
            "ok": True,  # not a hard failure — only needed for `init`
            "detail": "not installed (optional — only needed for `echolon init` data download)",
            "hint": "Install with: pip install echolon[shfe]",
        }


def _check_backtrader() -> dict:
    try:
        import backtrader  # noqa: F401
        return {"name": "backtrader", "ok": True, "detail": "available"}
    except ImportError as e:
        return {
            "name": "backtrader", "ok": False,
            "detail": f"import backtrader failed ({e})",
            "hint": "pip install --upgrade echolon",
        }


def _check_optuna() -> dict:
    try:
        import optuna  # noqa: F401
        return {"name": "optuna", "ok": True, "detail": "available"}
    except ImportError as e:
        return {
            "name": "optuna", "ok": False,
            "detail": f"import optuna failed ({e})",
            "hint": "pip install --upgrade echolon",
        }
