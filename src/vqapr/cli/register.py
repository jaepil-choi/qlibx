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
from vqapr.extension.registration import (
    register_constraint,
    register_data_model,
    register_exchange,
    register_strategy_model,
)

_REGISTRARS = {
    "datamodel": register_data_model,
    "strategy": register_strategy_model,
    "constraint": register_constraint,
    "exchange": register_exchange,
}

AUTHORED_KINDS = tuple(_REGISTRARS)
"""확장점 넷 전부. canon §10.2가 닫아두지 말라고 한 목록이다.

이전에는 datamodel·strategy 둘뿐이었고 *"exchange/constraint는 shipped profile만 허용한다"*고
적혀 있었다. 그건 canon과 어긋난다 — §10.2는 `Constraint`의 *"metric의 경제적 의미와 bound는 user
project가 소유하므로 패키지가 목록을 닫아둘 근거가 없다"*고 하고, Exchange도 shipped profile을
**상속해** listing과 비용을 더하는 것이 정상 경로다(`loading.py`). 라이브러리에는 넷 다 등록
함수가 있었고 CLI만 둘을 막고 있었다.

무엇이 실제로 좁은 문인지는 `load_exchange`가 정한다 — shipped profile을 상속하지 않거나
`execute()`를 갈아치운 것은 거기서 거부된다. CLI가 kind 목록으로 막을 일이 아니다.
"""


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
    register = _REGISTRARS[args.kind]
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
