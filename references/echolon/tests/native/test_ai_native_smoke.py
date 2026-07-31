"""AI-Native smoke test — the launch readiness criterion.

Simulates a fresh Claude session using echolon end-to-end:
1. echolon init my_test --template minimal
2. echolon validate my_test/          -> passes
3. Break it on purpose
4. echolon validate my_test/ --json   -> fails with PRM-001 + docs link
5. Fix it
6. echolon validate my_test/          -> passes again
"""

import json
import textwrap
from pathlib import Path

from typer.testing import CliRunner

from echolon.native.cli.main import app


runner = CliRunner()


def test_full_agent_loop(tmp_path):
    target = tmp_path / "my_test"

    # Step 1: scaffold from template
    r = runner.invoke(app, ["init", str(target), "--template", "minimal"])
    assert r.exit_code == 0, r.stdout

    # Step 2: validate — should pass
    r = runner.invoke(app, ["validate", str(target)])
    assert r.exit_code == 0, r.stdout

    # Step 3: break strategy_params.py (missing printlog in entry_params)
    (target / "strategy_params.py").write_text(textwrap.dedent("""\
        DEFAULT_PARAMS = {
            "entry_params": {},
            "exit_params": {"printlog": False},
            "risk_params": {"printlog": False},
            "sizer_params": {"printlog": False},
        }
        def optuna_search_space(trial):
            return DEFAULT_PARAMS
        def apply_shared_params(p):
            return p
        framework = None
    """))

    # Step 4: validate with --json — should fail with PRM-001
    r = runner.invoke(app, ["validate", str(target), "--json"])
    assert r.exit_code == 1
    payload = json.loads(r.stdout)
    assert payload["status"] == "failed"
    codes = [e["code"] for e in payload["errors"]]
    assert "PRM-001" in codes

    # Verify the error carries a docs_url
    prm_err = next(e for e in payload["errors"] if e["code"] == "PRM-001")
    assert "errors/codes/PRM-001.md" in prm_err["docs_url"]
    # Verify each error field is populated (agents need these)
    for required_field in ("code", "what", "why", "fix", "context", "docs_url"):
        assert required_field in prm_err, f"Missing field: {required_field}"

    # Step 5: apply the fix (add 'printlog': False to entry_params)
    (target / "strategy_params.py").write_text(textwrap.dedent("""\
        DEFAULT_PARAMS = {
            "entry_params": {"printlog": False},
            "exit_params": {"printlog": False},
            "risk_params": {"printlog": False},
            "sizer_params": {"printlog": False},
        }
        def optuna_search_space(trial):
            return DEFAULT_PARAMS
        def apply_shared_params(p):
            return p
        framework = None
    """))

    # Step 6: validate again — should pass
    r = runner.invoke(app, ["validate", str(target)])
    assert r.exit_code == 0, r.stdout


def test_every_template_passes_validation(tmp_path):
    """All bundled templates must scaffold into valid strategies."""
    for tmpl in ("minimal", "momentum_breakout", "rsi_mean_reversion"):
        target = tmp_path / tmpl
        r = runner.invoke(app, ["init", str(target), "--template", tmpl])
        assert r.exit_code == 0, r.stdout
        r = runner.invoke(app, ["validate", str(target)])
        assert r.exit_code == 0, f"Template {tmpl} failed validation:\n{r.stdout}"


def test_every_example_passes_validation():
    """All 3 repo-root examples must pass `echolon validate`.

    Guards against examples rotting as the API changes.
    """
    from echolon.native.examples_registry import AVAILABLE_EXAMPLES, example_path

    for name in AVAILABLE_EXAMPLES:
        src = example_path(name)
        r = runner.invoke(app, ["validate", str(src)])
        assert r.exit_code == 0, f"Example {name} failed validation:\n{r.stdout}"
