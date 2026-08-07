import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest


@pytest.fixture
def run_python_subprocess() -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(
        arguments: Sequence[str | Path],
        *,
        check: bool,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, *(str(argument) for argument in arguments)],
            check=check,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )

    return run
