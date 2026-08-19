"""`vqapr register <kind>` — validate, then persist.

`check` 를 따로 두지 않는다. 등록 함수가 이미 load/construct까지 하므로 검증 없는 등록 경로가
존재하지 않고, 따라서 "등록은 됐는데 쓸 수 없는 것"이 워크스페이스에 남지 않는다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from vqapr.cli.envelope import success
from vqapr.extension.registration import register_data_model, register_strategy_model

AUTHORED_KINDS = ("datamodel", "strategy")
"""User가 직접 작성하는 component. exchange/constraint는 shipped profile만 허용한다."""


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("kind", choices=AUTHORED_KINDS)
    parser.add_argument("component_id")
    parser.add_argument("path", type=Path)
    parser.add_argument("object_name")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="JSON object passed to the component constructor",
    )


def run(args: argparse.Namespace, *, project_root: Path) -> dict[str, Any]:
    config = json.loads(args.config) if args.config else None
    if config is not None and not isinstance(config, dict):
        raise ValueError("--config must be a JSON object")
    register = register_data_model if args.kind == "datamodel" else register_strategy_model
    ref = register(
        project_root,
        args.component_id,
        args.path,
        args.object_name,
        config=config,
    )
    return success(
        "component.register",
        kind=str(ref.kind),
        id=str(ref.component_id),
        fingerprint=ref.fingerprint,
        path=str(ref.path),
    )
