"""Tests for the shared Report + Finding types used by all deterministic
validators (echolon/strategy/validators/*).

The types are pure data — no I/O, no logic. Tests lock the public shape:
accumulate findings, report any_errors, round-trip through to_dict().
"""
from echolon.strategy.validators._report import Finding, Report


def test_finding_has_code_message_context_fields():
    f = Finding(code="STR-003", message="method missing", context={"component": "entry"})
    assert f.code == "STR-003"
    assert f.message == "method missing"
    assert f.context == {"component": "entry"}


def test_finding_context_defaults_to_empty_dict():
    f = Finding(code="STR-003", message="x")
    assert f.context == {}


def test_report_can_accumulate_findings():
    r = Report()
    r.add(Finding(code="STR-003", message="method missing", context={"component": "entry"}))
    r.add(Finding(code="PRM-003", message="hardcoded", context={"line": 42}))
    assert len(r.findings) == 2
    assert r.any_errors


def test_report_is_empty_when_no_findings():
    r = Report()
    assert not r.any_errors
    assert r.findings == []


def test_report_to_dict_round_trip():
    r = Report()
    r.add(Finding(code="VAL-003", message="key missing", context={"file": "x"}))
    d = r.to_dict()
    assert d["any_errors"] is True
    assert len(d["findings"]) == 1
    assert d["findings"][0]["code"] == "VAL-003"
    assert d["findings"][0]["message"] == "key missing"
    assert d["findings"][0]["context"] == {"file": "x"}


def test_report_to_dict_empty():
    d = Report().to_dict()
    assert d == {"any_errors": False, "findings": []}


def test_finding_is_a_dataclass_and_can_be_constructed_positionally():
    # Validates we can write Finding("VAL-001", "msg", {}) — positional args.
    f = Finding("VAL-001", "msg", {"k": "v"})
    assert f.code == "VAL-001"


def test_reimports_from_package_init():
    """The package-level import path must work: ``from echolon.strategy.validators
    import Finding, Report``. Validators in later tasks (B1-3..B1-7) will use
    this path."""
    from echolon.strategy.validators import Finding as F, Report as R
    r = R()
    r.add(F(code="VAL-001", message="x"))
    assert r.any_errors
