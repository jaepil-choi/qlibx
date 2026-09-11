"""Running several runs at once (`vqapr run --jobs`).

A batch is refused unless its runs are independent -- none reads a dataset another writes, and no
two write the same one (`require_independent_batch`). Each worker process runs with one BLAS thread
(`one_blas_thread_for_workers`), and the datasets several members read are baked once into
memory-mapped cubes under the workspace, kept alive by a heartbeat and swept when stale
(`batch_cubes`). One run itself is `assemble.py`'s.
"""

from __future__ import annotations

import multiprocessing
import os
import secrets
import shutil
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor
from contextlib import contextmanager, suppress
from pathlib import Path

from vqapr.component.base import Component
from vqapr.component.loading import (
    load_compliance,
    load_data_model,
    load_strategy_model,
)
from vqapr.data import cube as cube_module
from vqapr.data.dataset import Grain
from vqapr.data.scan import ScanSession
from vqapr.domain.errors import Failure, FailureSource, InputError, Stage, Status, VqaprError
from vqapr.workspace.registry import WORKSPACE_DIRECTORY, Workspace
from vqapr.workspace.run_definition import RunDefinition

__all__ = [
    "BLAS_THREAD_VARIABLES",
    "CUBES_DIRECTORY",
    "CUBE_HEARTBEAT",
    "CUBE_LOCK",
    "CUBE_STALE_AFTER",
    "RUN_BATCH_DEPENDENT",
    "RUN_BATCH_WRITES_COLLIDE",
    "_bake_for_batch",
    "_keep_alive",
    "_reads",
    "_sweep_stale_cubes",
    "batch_cubes",
    "batch_reads",
    "in_workers",
    "one_blas_thread_for_workers",
    "require_independent_batch",
]


def in_workers[Returned](
    run_ids: Sequence[str],
    worker: Callable[..., Returned],
    arguments: tuple[object, ...],
    *,
    jobs: int,
    store: Path | None,
    root_path: Path,
) -> dict[str, Returned | Exception]:
    """One RUN per worker, in `jobs` spawned processes; what each returned OR raised, by run id.

    The one pool behind `--jobs`. It spread the members of a single run until 2026-09-09; a run
    holds one model now, so the unit is the run (`docs/design/two-clocks-and-the-wiring-table.md`
    §2.3). That is the more general unit as well -- two runs need share nothing, where two members
    shared a frozen layer -- and it is what a graph scheduler will hand this function later.

    `worker` is a module-level function taking `(project_root, run_id, store_root, *arguments)` as
    strings and bools, because it crosses a `spawn` boundary. The
    `docs/issues/archive/073` rule still holds: a worker's failure has to be something
    `concurrent.futures` can pickle, which is why the strategy worker returns its outcome.

    **A worker's exception is that run's entry, not the batch's end.** Until
    `docs/issues/report-2026-09-10-run-jobs-does-not-parallelise-datamodel-runs.md` this
    re-raised the first worker's exception out of the comprehension, which dropped every other
    worker's result on the floor -- and was the reason the CLI kept datamodel runs OUT of the pool
    (their worker raises its refusal, which is right: a `VqaprError` pickles and is the same
    exception the sequential path raises). Now each run comes back as what its worker returned
    or what it raised, and the caller renders each. Only a broken pool still propagates: it is
    not any one run's news.
    """
    if store is None:
        raise ValueError(
            "jobs > 1 needs a store_root: a worker's result comes back through the record store"
        )
    context = multiprocessing.get_context("spawn")
    with (
        one_blas_thread_for_workers(),
        ProcessPoolExecutor(max_workers=min(jobs, len(run_ids)), mp_context=context) as pool,
    ):
        futures = {
            run_id: pool.submit(worker, str(root_path), run_id, str(store), *arguments)
            for run_id in run_ids
        }
        outcomes: dict[str, Returned | Exception] = {}
        for run_id, future in futures.items():
            try:
                outcomes[run_id] = future.result()
            except BrokenExecutor:
                raise
            except Exception as raised:
                outcomes[run_id] = raised
        return outcomes


BLAS_THREAD_VARIABLES = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
"""The thread counts numpy's BLAS builds read when they load (record `257`)."""


@contextmanager
def one_blas_thread_for_workers() -> Iterator[None]:
    """Start a batch's workers with one BLAS thread each, unless the user set a count.

    Record `257` (owner decision 2026-09-11). numpy's OpenBLAS commits a working buffer for every
    core it may use when it loads -- about 0.8 GB of private memory on the 32-core machine the
    2026-09-11 memory report was measured on, 27 MB of it ever touched -- and every `--jobs`
    worker is its own process loading its own. N workers already use the cores; N x 32 BLAS
    threads only fight over them. A spawned worker copies the environment when it starts, so the
    variables are set around the pool and put back after it: the parent -- a Python caller's own
    process -- is left as it was, and a count the user set is theirs and is not touched. A single
    run is not a batch and keeps whatever its process has.
    """
    set_here = [name for name in BLAS_THREAD_VARIABLES if name not in os.environ]
    for name in set_here:
        os.environ[name] = "1"
    try:
        yield
    finally:
        for name in set_here:
            os.environ.pop(name, None)


RUN_BATCH_DEPENDENT = "run.batch_dependent"


RUN_BATCH_WRITES_COLLIDE = "run.batch_writes_collide"


def batch_reads(workspace: Workspace, run_ids: Sequence[str]) -> dict[str, dict[str, set[str]]]:
    """What each run of a batch reads, by run id: asked of each run's components once.

    Both doors of a `--jobs` batch need it -- the independence judgment and the bake -- and
    each used to load every component again to ask (record `238`); the CLI asks here once and
    hands the answer to both.
    """
    return {run_id: _reads(workspace, workspace.run_definition(run_id)) for run_id in run_ids}


def require_independent_batch(
    workspace: Workspace,
    run_ids: Sequence[str],
    reads: Mapping[str, Mapping[str, set[str]]] | None = None,
) -> None:
    """Refuse a batch that one pool cannot hold: a run reading what another in it writes.

    The pool starts every run at once and promises nothing about order, so a strategy whose
    dataset a datamodel in the same batch writes would read the dataset as it stood before --
    stale under `--force`, absent otherwise -- or race the writer. Owner decision (2026-09-10):
    such a batch is refused whole before anything is spawned, rather than ordered; the graph's
    order is `vqapr run <producer>` first, then the batch without it, which is what the fix says.
    Two runs naming one `writes` are the other thing a pool cannot hold, and are refused by the
    same door with their own code.

    What a run reads is what preflight would freeze as its `requirements` (the model's and its
    Compliance rules'), plus the two datasets the run layer itself names -- `agenda.days_from`
    and `execution.dataset`. A component that does not load contributes nothing here: its own
    worker refuses it by name, and a run that cannot start cannot race anything. `reads` is
    `batch_reads` already asked; absent, it is asked here.
    """
    definitions = {run_id: workspace.run_definition(run_id) for run_id in run_ids}
    if reads is None:
        reads = batch_reads(workspace, run_ids)
    writers: dict[str, list[str]] = {}
    for run_id, definition in definitions.items():
        writers.setdefault(definition.writes, []).append(run_id)
    failures: list[Failure] = []
    for dataset_id, writing in sorted(writers.items()):
        if len(writing) < 2:
            continue
        named = ", ".join(writing)
        failures.append(
            Failure.bounded(
                RUN_BATCH_WRITES_COLLIDE,
                "runs in one --jobs batch write different datasets",
                observed=f"{dataset_id!r} is the `writes` of {len(writing)} runs: {named}",
                fix=(
                    f"register a different `writes` for all but one of {named}, or run them "
                    "one at a time"
                ),
                status=Status.INVALID,
                source=FailureSource(key_path=f"runs.{writing[0]}.writes"),
            )
        )
    for run_id in definitions:
        for dataset_id in sorted(reads[run_id]):
            producers = [other for other in writers.get(dataset_id, ()) if other != run_id]
            if not producers:
                continue
            producer = producers[0]
            failures.append(
                Failure.bounded(
                    RUN_BATCH_DEPENDENT,
                    "a run in a --jobs batch does not read what another run in it writes",
                    observed=(
                        f"{run_id!r} reads {dataset_id!r}, which {producer!r} writes; a pool "
                        "starts both at once and promises no order between them"
                    ),
                    fix=(
                        f"vqapr run {producer} first, then this batch without it -- or run "
                        f"{run_id} after the batch"
                    ),
                    status=Status.INVALID,
                    source=FailureSource(key_path=f"runs.{run_id}"),
                )
            )
    if failures:
        raise VqaprError(stage=Stage.CHECK, failures=failures)


def _reads(workspace: Workspace, definition: RunDefinition) -> dict[str, set[str]]:
    """What a run would read: each dataset id with the field ids its components declare on it.

    The two datasets the run layer itself names -- `agenda.days_from`, `execution.dataset` --
    are read whole by the framework and carry no field set here.
    """
    read: dict[str, set[str]] = {}
    if definition.agenda.days_from is not None:
        read.setdefault(definition.agenda.days_from, set())
    if definition.execution is not None:
        read.setdefault(definition.execution.dataset, set())
    loaders: list[tuple[str, Callable[..., Component]]] = []
    if definition.strategy is not None:
        loaders.append((definition.strategy.component_id, load_strategy_model))
    if definition.datamodel is not None:
        loaders.append((definition.datamodel.component_id, load_data_model))
    loaders.extend((rule_id, load_compliance) for rule_id in definition.compliance)
    for component_id, loader in loaders:
        try:
            component = loader(
                workspace.component(component_id), project_root=workspace.project_root
            )
        except Exception:
            # Its own worker refuses it by name; a component that cannot load reads nothing.
            continue
        for requirement in component.requirements() or ():
            dataset_id = str(getattr(requirement, "dataset_id", ""))
            if dataset_id:
                field_id = str(getattr(requirement, "field_id", ""))
                fields = read.setdefault(dataset_id, set())
                if field_id:
                    fields.add(field_id)
    return read


CUBES_DIRECTORY = "cubes"


CUBE_LOCK = "batch.lock"


CUBE_STALE_AFTER = 600.0


CUBE_HEARTBEAT = 30.0


@contextmanager
def batch_cubes(
    workspace: Workspace,
    run_ids: Sequence[str],
    reads: Mapping[str, Mapping[str, set[str]]] | None = None,
) -> Iterator[Path | None]:
    """Bake what a `--jobs` batch reads once, hand the directory to its workers, remove it after.

    Record `236` (`docs/issues/098`). Every panel-grain dataset any run in the batch reads is
    scanned once here, in the driver, into `<project>/.vqapr/cubes/<batch>/<dataset_id>/` --
    one memory-mappable matrix per numeric field over every instrument -- and each worker takes
    its panel as a slice of those files (`data/cube.py`). The OS page cache holds the bytes once
    per machine; the 671 scans a 671-run sweep used to make are one.

    **Nothing accumulates** (owner decision 2026-09-10). The directory goes when the batch
    returns, on success, refusal or interrupt; a directory a hard-killed driver left behind is
    swept by the next batch once its lock is stale. A heartbeat thread keeps this batch's lock
    fresh for as long as the batch runs, so a batch of long runs is never mistaken for a dead
    one. What cannot be baked -- an unverified registration, a non-numeric field, a `rows`
    grain, a source that will not scan -- is simply not there, and the worker scans and refuses
    exactly as it does outside a batch. `reads` is `batch_reads` already asked (record `238`).
    """
    root = workspace.project_root / WORKSPACE_DIRECTORY / CUBES_DIRECTORY
    root.mkdir(parents=True, exist_ok=True)
    _sweep_stale_cubes(root)
    directory = root / f"{os.getpid()}-{secrets.token_hex(4)}"
    directory.mkdir()
    lock = directory / CUBE_LOCK
    lock.write_text(str(os.getpid()), encoding="ascii")
    stop = threading.Event()
    beat = threading.Thread(target=_keep_alive, args=(lock, stop), daemon=True)
    beat.start()
    try:
        _bake_for_batch(
            workspace, reads if reads is not None else batch_reads(workspace, run_ids), directory
        )
        yield directory
    finally:
        stop.set()
        beat.join(timeout=CUBE_HEARTBEAT)
        shutil.rmtree(directory, ignore_errors=True)


def _keep_alive(lock: Path, stop: threading.Event) -> None:
    while not stop.wait(CUBE_HEARTBEAT):
        with suppress(OSError):
            os.utime(lock, None)


def _sweep_stale_cubes(root: Path) -> None:
    """Remove batch directories whose lock nobody has refreshed inside the stale window."""
    now = time.time()
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            age = now - (child / CUBE_LOCK).stat().st_mtime
        except OSError:
            age = CUBE_STALE_AFTER + 1.0
        if age > CUBE_STALE_AFTER:
            shutil.rmtree(child, ignore_errors=True)


def _bake_for_batch(
    workspace: Workspace, reads: Mapping[str, Mapping[str, set[str]]], directory: Path
) -> None:
    """One cube per panel-grain dataset the batch reads, over the union of the fields it names."""
    wanted: dict[str, set[str]] = {}
    for run_reads in reads.values():
        for dataset_id, fields in run_reads.items():
            wanted.setdefault(dataset_id, set()).update(fields)
    with ScanSession() as session:
        for dataset_id, fields in sorted(wanted.items()):
            if not fields:
                continue
            try:
                registration = workspace.dataset(dataset_id)
                if registration.grain is None or registration.grain is Grain.ROWS:
                    continue
                source = workspace.source(str(registration.source))
                cube_module.bake(
                    directory,
                    registration=registration,
                    source=source,
                    source_digest=workspace.source_digest(source),
                    fields=sorted(fields),
                    session=session,
                )
            except (VqaprError, InputError, KeyError, OSError):
                # Its worker scans and refuses it by name; a cube is a shortcut, not a door.
                continue
