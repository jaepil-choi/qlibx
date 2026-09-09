"""A declaration document registers without `vqapr.cli` being imported at all.

This is the audit's own stated criterion for Step 8, and it is the assertion that proves the move
rather than describing it: **can the same conclusion be reached without importing `vqapr.cli`?**

`cli/register.py` was 1,093 lines. It read the YAML, validated key sets, resolved relative paths,
parsed agendas and sessions, walked a `.py` with `ast` to find the sole authored subclass, and
registered the result. `docs/vqapr-architecture.md` §10.2 defines the CLI as a product surface
rather than a layer, and a surface that owns rules costs twice: the rules cannot be tested without
driving argparse, and they cannot be reached from another entry point — so a second entry point
grows its own copy and the two diverge.

`docs/issues/archive/012` is that divergence, already paid for: `check` refused a spec that `run` completed,
because each verb decided for itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from vqapr.project.registration import apply
from vqapr.project.store import Workspace


def _clear_cli_modules() -> None:
    """Drop every `vqapr.cli*` module so an accidental import is visible rather than cached."""
    for name in [m for m in sys.modules if m == "vqapr.cli" or m.startswith("vqapr.cli.")]:
        del sys.modules[name]


def test_a_document_registers_with_the_cli_never_imported(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """The criterion, asserted directly.

    `apply` is the whole of what `vqapr register <file>.yaml` does once argparse has produced a
    path. If this passes with `vqapr.cli` absent from `sys.modules`, the rules are in a layer.
    """
    _clear_cli_modules()

    declaration = tmp_path / "declare.yaml"
    declaration.write_text(
        yaml.safe_dump(
            {
                "datasets": {
                    "price_daily": {
                        # A dataset and its source register together: a projection without the
                        # file it projects is not usable, so one declaration covers both.
                        "source_id": "prices",
                        "path": str(model_price_parquet),
                        "instrument_field": "instrument",
                        "available_at": "available_at",
                        "key_fields": ["available_at", "instrument"],
                        "grain": "instrument_instant",
                        "fields": {"close": "close"},
                        "field_types": {"close": "DOUBLE"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    document = yaml.safe_load(declaration.read_text(encoding="utf-8"))

    registered = apply(document, tmp_path, base=declaration.parent, declaration=declaration)

    assert "datasets" in registered
    assert "price_daily" in registered["datasets"]

    workspace = Workspace.open(tmp_path)
    assert workspace.dataset("price_daily") is not None
    assert workspace.source("prices") is not None

    leaked = sorted(m for m in sys.modules if m == "vqapr.cli" or m.startswith("vqapr.cli."))
    assert not leaked, (
        "registering a declaration imported the CLI: "
        + ", ".join(leaked)
        + ". The rules are supposed to live in `vqapr/project/registration.py`; if the layer reaches back "
        "into the surface, the split moved the code without moving the dependency."
    )


def test_the_declaration_layer_does_not_import_the_surface() -> None:
    """The same property read off the source, so it fails at the import rather than at a call.

    A runtime check only catches what the exercised path touches. This catches a module-level
    import on a path no test happens to drive.
    """
    import ast

    source = Path("src/vqapr/project/registration.py").read_text(encoding="utf-8")
    reached = sorted(
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith(("vqapr.cli", "vqapr.public"))
    )

    assert not reached, (
        "`vqapr/project/registration.py` imports "
        + ", ".join(reached)
        + ". It is below both: the CLI renders its result and the facade re-exports its functions. "
        "Reaching up for either is the fan-in record 111 and 112 exist to remove."
    )


def test_the_surface_still_registers_the_same_document(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """The CLI must keep working, which is the other half of a move being safe.

    Driven through `cli.register.run` with a namespace argparse would have produced.
    """
    import argparse

    from vqapr.cli.register import run as register_command

    declaration = tmp_path / "declare.yaml"
    declaration.write_text(
        yaml.safe_dump(
            {
                "datasets": {
                    "price_daily": {
                        "source_id": "prices",
                        "path": str(model_price_parquet),
                        "instrument_field": "instrument",
                        "available_at": "available_at",
                        "key_fields": ["available_at", "instrument"],
                        "grain": "instrument_instant",
                        "fields": {"close": "close"},
                        "field_types": {"close": "DOUBLE"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    envelope = register_command(
        argparse.Namespace(declaration=str(declaration)), project_root=tmp_path
    )

    assert envelope["ok"] is True
    assert envelope["registered"]["datasets"] == ["price_daily"]
