"""Resource ownership begins at acquisition, including failures before the loop starts."""

from pathlib import Path

import pytest

from tests.flow.datamodel.test_a_datamodel_is_a_run import _definition, _prepared
from tests.flow.declaration.test_preflight import _setup
from vqapr.flow import orchestration as runtime
from vqapr.record import DATAMODEL_KIND, STRATEGY_KIND, RunRecordLive, RunRecordWriter
from vqapr.project.run import DataModelEntry


@pytest.fixture(params=["strategy", "datamodel"])
def member(request, tmp_path: Path, model_price_parquet: Path):
    kind = request.param
    if kind == "strategy":
        workspace, definition = _setup(tmp_path, model_price_parquet)
        frozen = runtime.preflight_run(workspace, definition)
        layer = frozen.strategies[0]
    else:
        _prepared(tmp_path, model_price_parquet, ("reversal", "ReversalModel"))
        frozen = runtime.preflight_run(
            tmp_path, _definition("review", DataModelEntry("reversal", "scores", ("score",)))
        )
        layer = frozen.datamodels[0]
    store = tmp_path / "records"

    def execute():
        if kind == "strategy":
            return runtime._run_strategy(
                tmp_path,
                frozen,
                layer,
                store=store,
                replace_record=False,
                record_account_positions=True,
                roster=None,
            )
        return runtime._run_datamodel(tmp_path, frozen, layer, store=store, replace_record=False)

    return kind, frozen, layer, store, execute


@pytest.mark.parametrize("failure_at", ["store", "constructor", "open"])
def test_pre_loop_failure_closes_session_and_releases_only_owned_writer(
    member, monkeypatch, failure_at
):
    kind, _, _, _, execute = member
    closed, released = [], []
    original_close = runtime.ScanSession.close
    original_release = RunRecordWriter.release

    def close(session):
        closed.append(session)
        original_close(session)

    def release(writer):
        released.append(writer)
        original_release(writer)

    monkeypatch.setattr(runtime.ScanSession, "close", close)
    monkeypatch.setattr(RunRecordWriter, "release", release)
    failure = ValueError("construction stopped")

    def fail(*args, **kwargs):
        raise failure

    if failure_at == "store":
        monkeypatch.setattr(runtime, "DuckDbObservationStore", fail)
    elif failure_at == "open":
        monkeypatch.setattr(RunRecordWriter, "open", fail)
    else:
        monkeypatch.setattr(
            runtime, "StrategyEventLoop" if kind == "strategy" else "DataModelEventLoop", fail
        )
    with pytest.raises(ValueError) as caught:
        execute()
    assert caught.value is failure
    assert len(closed) == 1
    assert len(released) == (1 if failure_at == "constructor" else 0)


def test_an_open_refusal_does_not_release_the_other_runs_claim(member):
    kind, frozen, layer, store, execute = member
    owner = RunRecordWriter(
        store,
        frozen.run_id,
        layer.record_ref,
        member_kind=STRATEGY_KIND if kind == "strategy" else DATAMODEL_KIND,
    )
    owner.open()
    try:
        # Two consecutive refusals prove the first attempt did not unlock the owner.
        for _ in range(2):
            with pytest.raises(RunRecordLive):
                execute()
    finally:
        owner.release()
