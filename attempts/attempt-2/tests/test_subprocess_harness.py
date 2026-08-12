import subprocess
from collections.abc import Callable
from pathlib import Path


def test_python_subprocess_runner_tolerates_non_utf8_stderr(
    run_python_subprocess: Callable[..., subprocess.CompletedProcess[str]],
    tmp_path: Path,
) -> None:
    completed = run_python_subprocess(
        (
            "-c",
            (
                "import sys; "
                "sys.stderr.buffer.write(bytes((0xC7, 0xD1, 0xB1, 0xDB))); "
                "raise SystemExit(3)"
            ),
        ),
        check=False,
        cwd=tmp_path,
    )

    assert completed.returncode == 3
    assert completed.stderr is not None
    assert completed.stderr