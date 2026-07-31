"""Strategy templates shipped with Echolon.

Programmatic access: Template dataclass + list_templates() / load_template(name).
Legacy surface: TEMPLATES_DIR / AVAILABLE_TEMPLATES / template_path(name) preserved
for existing callers.
"""
from dataclasses import dataclass
from pathlib import Path


TEMPLATES_DIR = Path(__file__).parent

AVAILABLE_TEMPLATES = ("minimal", "momentum_breakout", "rsi_mean_reversion")


def template_path(name: str) -> Path:
    """Legacy: return the on-disk path for a known template. Raises on unknown."""
    if name not in AVAILABLE_TEMPLATES:
        raise KeyError(f"Unknown template: {name}. Available: {AVAILABLE_TEMPLATES}")
    path = TEMPLATES_DIR / name
    if not path.is_dir():
        raise FileNotFoundError(f"Template directory missing: {path}")
    return path


@dataclass
class Template:
    name: str
    files: dict[str, str]  # filename → content


_TEMPLATES_ROOT = TEMPLATES_DIR  # alias kept so the plan's code path is obvious


def list_templates() -> list[str]:
    """Return all template directory names that contain a strategy.py entry point."""
    return sorted(
        d.name for d in _TEMPLATES_ROOT.iterdir()
        if d.is_dir() and d.name not in {"__pycache__"} and (d / "strategy.py").exists()
    )


def load_template(name: str) -> Template | None:
    """Load a template by name. Returns None if the template dir doesn't exist."""
    tpl_dir = _TEMPLATES_ROOT / name
    if not tpl_dir.is_dir():
        return None
    files = {p.name: p.read_text() for p in tpl_dir.iterdir() if p.is_file()}
    return Template(name=name, files=files)


__all__ = [
    "TEMPLATES_DIR",
    "AVAILABLE_TEMPLATES",
    "template_path",
    "Template",
    "list_templates",
    "load_template",
]
