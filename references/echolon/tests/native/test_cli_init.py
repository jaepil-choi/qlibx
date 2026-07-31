"""Tests for `echolon init` CLI."""

from pathlib import Path

from typer.testing import CliRunner

from echolon.native.cli.main import app
from echolon.native.validation import validate_strategy_dir


runner = CliRunner()


def test_init_minimal_creates_all_files(tmp_path):
    out = tmp_path / "my_strategy"
    result = runner.invoke(app, ["init", str(out), "--template", "minimal"])
    assert result.exit_code == 0
    assert out.is_dir()
    for f in ("strategy.py", "entry.py", "exit.py", "risk.py", "sizer.py",
              "strategy_params.py", "strategy_indicator_list.json", "README.md"):
        assert (out / f).exists(), f"Missing: {f}"


def test_init_momentum(tmp_path):
    out = tmp_path / "m"
    result = runner.invoke(app, ["init", str(out), "--template", "momentum_breakout"])
    assert result.exit_code == 0
    assert (out / "entry.py").exists()


def test_init_rsi(tmp_path):
    out = tmp_path / "r"
    result = runner.invoke(app, ["init", str(out), "--template", "rsi_mean_reversion"])
    assert result.exit_code == 0


def test_init_unknown_template_fails(tmp_path):
    out = tmp_path / "bad"
    result = runner.invoke(app, ["init", str(out), "--template", "nope"])
    assert result.exit_code != 0


def test_init_existing_dir_fails(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    (out / "junk.py").write_text("", encoding="utf-8")
    result = runner.invoke(app, ["init", str(out), "--template", "minimal"])
    assert result.exit_code != 0


def test_all_templates_pass_validation(tmp_path):
    for name in ("minimal", "momentum_breakout", "rsi_mean_reversion"):
        out = tmp_path / name
        result = runner.invoke(app, ["init", str(out), "--template", name])
        assert result.exit_code == 0
        errors = validate_strategy_dir(out)
        assert errors == [], f"Template {name} failed: {errors}"
