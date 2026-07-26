from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .ensemble import build_ensemble
from .reporting import create_report
from .runner import run_strategy_batch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qlib-extended")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Run configured strategies")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--strategy", action="append", required=True)
    run.add_argument("--workers", type=int, default=1)

    report = commands.add_parser("report", help="Render stored backtest runs")
    report.add_argument("--catalog", type=Path, required=True)
    report.add_argument("--backtest-run-id", action="append", required=True)
    report.add_argument("--output-dir", type=Path, required=True)
    report.add_argument("--png", action="store_true")

    ensemble = commands.add_parser("ensemble", help="Combine stored alpha runs")
    ensemble.add_argument("--catalog", type=Path, required=True)
    ensemble.add_argument("--strategy-id", required=True)
    ensemble.add_argument(
        "--member",
        action="append",
        required=True,
        help="Member in alpha_run_id=weight form",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        result = run_strategy_batch(
            args.config,
            strategy_ids=tuple(args.strategy),
            max_workers=args.workers,
        )
        print(json.dumps([asdict(run) for run in result.runs], indent=2))
        return 0
    if args.command == "report":
        result = create_report(
            args.catalog,
            backtest_run_ids=tuple(args.backtest_run_id),
            output_dir=args.output_dir,
            include_png=args.png,
        )
        print(json.dumps([str(path) for path in result.files], indent=2))
        return 0
    if args.command == "ensemble":
        result = build_ensemble(
            args.catalog,
            strategy_id=args.strategy_id,
            members=_parse_members(args.member),
        )
        print(json.dumps(asdict(result), indent=2))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


def _parse_members(values: list[str]) -> dict[str, float]:
    members: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid member, expected alpha_run_id=weight: {value}")
        run_id, weight = value.rsplit("=", 1)
        if run_id in members:
            raise ValueError(f"duplicate member run_id: {run_id}")
        members[run_id] = float(weight)
    return members
