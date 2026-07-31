"""CLI helpers for bundle verification."""
from __future__ import annotations

import argparse
from pathlib import Path

from .manifest import load_bundle


def main(argv: list[str] | None = None) -> int:
    from echolon._internal.structured_logging import install_structured_logging

    install_structured_logging()
    parser = argparse.ArgumentParser(prog="echolon-bundle")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("bundle_dir", type=Path)
    args = parser.parse_args(argv)

    if args.command == "verify":
        manifest = load_bundle(args.bundle_dir)
        print(f"bundle verified: {manifest.bundle_version}")
        return 0
    raise AssertionError(args.command)


def console_main() -> None:
    raise SystemExit(main())
