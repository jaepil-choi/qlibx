"""Record `257`: a `--jobs` worker starts with one BLAS thread unless the user chose otherwise.

numpy's OpenBLAS commits a working buffer per core it may use when it loads -- about 0.8 GB of
private memory on the 32-core machine the 2026-09-11 memory report was measured on, of which
27 MB was ever touched. Every worker of a batch is its own process and made its own. The owner
chose (2026-09-11) to start batch workers single-threaded: N workers already use the cores, and
N x 32 BLAS threads only fight over them. A value the user set is theirs and is left alone, and
the parent's environment is what it was once the batch returns.
"""

from __future__ import annotations

import os

import pytest

from vqapr.flow.orchestration import BLAS_THREAD_VARIABLES, one_blas_thread_for_workers


def test_workers_are_started_with_one_blas_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in BLAS_THREAD_VARIABLES:
        monkeypatch.delenv(variable, raising=False)

    with one_blas_thread_for_workers():
        assert {variable: os.environ[variable] for variable in BLAS_THREAD_VARIABLES} == {
            variable: "1" for variable in BLAS_THREAD_VARIABLES
        }

    assert not any(variable in os.environ for variable in BLAS_THREAD_VARIABLES), (
        "the parent's environment is what it was before the batch"
    )


def test_a_thread_count_the_user_set_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "8")

    with one_blas_thread_for_workers():
        assert os.environ["OPENBLAS_NUM_THREADS"] == "8"

    assert os.environ["OPENBLAS_NUM_THREADS"] == "8"
