"""qmt strategy logger writes under slots/{slot_id}/ (deployment-identity relocation)."""
import echolon.live.platforms.miniqmt.qmt_engine as qe


def test_get_strategy_logger_writes_under_slot_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = {}

    class FakeLogger:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(qe, "CSVStrategyLogger", FakeLogger)

    # Bypass the heavy __init__; exercise only get_strategy_logger().
    engine = qe.QMTEngine.__new__(qe.QMTEngine)
    engine._strategy_logger = None
    engine._symbol = "al"
    engine._slot_id = "al_s1"

    engine.get_strategy_logger()

    assert captured["strategy_name"] == "qmt_al"
    assert captured["output_dir"].replace("\\", "/").endswith(
        "workspace/deploy/slots/al_s1"
    )


def test_get_strategy_logger_defaults_to_symbol_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = {}

    class FakeLogger:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(qe, "CSVStrategyLogger", FakeLogger)
    engine = qe.QMTEngine.__new__(qe.QMTEngine)
    engine._strategy_logger = None
    engine._symbol = "al"
    engine._slot_id = "al"  # what __init__ sets when slot_id is absent (slot_id or self._symbol)

    engine.get_strategy_logger()
    assert captured["output_dir"].replace("\\", "/").endswith(
        "workspace/deploy/slots/al"
    )
