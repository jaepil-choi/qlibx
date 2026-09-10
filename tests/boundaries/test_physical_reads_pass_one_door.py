"""A physical read is measured at one door, and only there (`docs/issues/095`, record `234`).

The scan's check kernels -- the queries that describe a file, prove a key, measure a span,
count non-finite values, or count non-positive prices -- are what "validating a file" costs.
Until record `234` three modules called them with three shapes, and the same execution table
was scanned at registration, at preflight and at run for facts registration had already
established. `data/validation.py` is the one module that may call them now; every later reader
asks `require_verified` for the file's identity instead.

Held by reading the source, not by mocking: a new module that opens a kernel of its own fails
here by file and line, with the door named.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "vqapr"
DOOR = SRC / "data" / "validation.py"
KERNELS = {
    "describe",
    "describe_projection",
    "key_check",
    "span_check",
    "finite_check",
    "positive_finite_when_true",
}


def _kernel_calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "vqapr.data.scan":
            imported.update(
                alias.asname or alias.name for alias in node.names if alias.name in KERNELS
            )
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Attribute) and callee.attr in KERNELS:
            if isinstance(callee.value, ast.Name) and callee.value.id == "scan":
                found.append(f"{path.relative_to(SRC.parent)}:{node.lineno} scan.{callee.attr}")
        elif isinstance(callee, ast.Name) and callee.id in imported:
            found.append(f"{path.relative_to(SRC.parent)}:{node.lineno} {callee.id}")
    return found


def test_only_the_validation_module_calls_the_scan_check_kernels() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if path == DOOR or path == SRC / "data" / "scan.py":
            continue
        offenders.extend(_kernel_calls(path))
    assert offenders == [], (
        "a physical read is measured at data/validation.py::verify_source and nowhere else; "
        "these call a check kernel directly:\n  " + "\n  ".join(offenders)
    )


def test_the_door_itself_uses_every_kernel() -> None:
    """The set above is the door's vocabulary; a kernel nobody calls would be dead code."""
    used = {call.rsplit(" ", 1)[-1].removeprefix("scan.") for call in _kernel_calls(DOOR)}
    assert used == KERNELS, sorted(KERNELS - used)
