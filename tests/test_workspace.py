"""`workspace.py` — project 선언을 명령 사이에 보존한다."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from vqapr.data import scan
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import VqaprError
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.project.store import Workspace

# A span these tests supply directly. Persistence requires one, because the span is measured
# during validation and a stored registration missing it would force the next reader to re-read
# the whole source. These cases exercise the metadata write in isolation against a path that
# deliberately does not exist, so they attach the measurement rather than perform it.
_SPAN = (
    datetime(2024, 1, 2, 15, 30, tzinfo=UTC),
    datetime(2025, 1, 2, 15, 30, tzinfo=UTC),
)


def _registration(raw_id: str = "price_daily", **overrides) -> DatasetRegistration:
    kwargs = {
        "instrument_field": "instrument",
        "available_at": "available_at",
        "key_fields": ("session_date", "instrument"),
        "grain": "rows",
        "fields": {"close": "close", "session_date": "session_date"},
        "field_types": {"close": "INTEGER", "session_date": "DATE"},
    }
    kwargs.update(overrides)
    return DatasetRegistration.of(raw_id, "prices", **kwargs).with_span(*_SPAN)


def _source(**overrides) -> SourceSpec:
    kwargs = {"hive_partitioned": True}
    kwargs.update(overrides)
    return SourceSpec.of("prices", "prepared/price_daily", **kwargs)


def _venue(raw_id: str = "krx-daily") -> DatasetRegistration:
    """A venue table: a dataset with an execution role (record 185). The fill is the run's."""
    return DatasetRegistration.of(
        raw_id,
        'krx-execution',
        instrument_field="instrument",
        available_at="trade_at",
        grain="instrument_instant",
        key_fields=("trade_at", "instrument"),
        fields={"open": "open", "close": "close", "is_tradable": "is_tradable"},
        field_types={"open": "DOUBLE", "close": "DOUBLE", "is_tradable": "BOOLEAN"},
        execution={"is_tradable": "is_tradable"},
    ).with_span(*_SPAN)


def test_registration_survives_reopening_the_workspace(tmp_path: Path) -> None:
    expected = _registration()
    workspace = Workspace.create(tmp_path)

    with Workspace.transaction(workspace) as t:
        assert t.register_dataset(expected, _source()) is True

    reopened = Workspace.open(tmp_path)
    assert reopened.dataset("price_daily") == expected


def test_two_datasets_are_both_queryable_after_reopen(tmp_path: Path) -> None:
    first = _registration()
    second = _registration(
        "price_adjusted", fields={"close": "adjusted_close"}, field_types={"close": "INTEGER"}
    )
    workspace = Workspace.create(tmp_path)

    with Workspace.transaction(workspace) as t:
        t.register_dataset(first, _source())
    with Workspace.transaction(workspace) as t:
        t.register_dataset(second, _source())

    reopened = Workspace.open(tmp_path)
    assert {item.dataset_id: item for item in reopened.datasets} == {
        first.dataset_id: first,
        second.dataset_id: second,
    }


def test_identical_reregistration_is_an_idempotent_noop(tmp_path: Path) -> None:
    registration = _registration()
    workspace = Workspace.create(tmp_path)
    with Workspace.transaction(workspace) as t:
        assert t.register_dataset(registration, _source()) is True
    before = workspace.path.read_bytes()

    with Workspace.transaction(workspace) as t:
        assert t.register_dataset(_registration(), _source()) is False
    assert workspace.path.read_bytes() == before


def test_conflicting_reregistration_fails_without_mutation(tmp_path: Path) -> None:
    original = _registration()
    workspace = Workspace.create(tmp_path)
    with Workspace.transaction(workspace) as t:
        t.register_dataset(original, _source())
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught, Workspace.transaction(workspace) as t:
        t.register_dataset(
            _registration(fields={"open": "open"}, field_types={"open": "INTEGER"}), _source()
        )

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["stage"] == "register"
    assert [failure["code"] for failure in payload["failures"]] == [
        "dataset.registered"
    ]
    assert workspace.path.read_bytes() == before
    assert Workspace.open(tmp_path).dataset("price_daily") == original


def test_opening_a_missing_workspace_is_a_structured_failure(tmp_path: Path) -> None:
    with pytest.raises(VqaprError) as caught:
        Workspace.open(tmp_path)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.missing"


def test_opening_malformed_yaml_is_a_structured_failure(tmp_path: Path) -> None:
    path = tmp_path / ".vqapr" / "workspace.yaml"
    path.parent.mkdir()
    path.write_text("datasets: [not, a, mapping]", encoding="utf-8")

    with pytest.raises(VqaprError) as caught:
        Workspace.open(tmp_path)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.invalid"


def test_explicit_workspaces_do_not_share_declarations(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = Workspace.create(first_root)
    second = Workspace.create(second_root)

    with Workspace.transaction(first) as t:
        t.register_dataset(_registration(), _source())
    with Workspace.transaction(second) as t:
        t.register_dataset(_registration("fundamentals"), _source())

    assert [str(item.dataset_id) for item in Workspace.open(first_root).datasets] == ["price_daily"]
    assert [str(item.dataset_id) for item in Workspace.open(second_root).datasets] == [
        "fundamentals"
    ]


def test_direct_construction_cannot_bypass_an_existing_workspace(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    with Workspace.transaction(workspace) as t:
        t.register_dataset(_registration(), _source())
    before = workspace.path.read_bytes()

    with pytest.raises(TypeError, match=r"Workspace\.create.*Workspace\.open"):
        Workspace(tmp_path, {})

    assert workspace.path.read_bytes() == before


def test_stale_instance_merges_with_current_durable_state(tmp_path: Path) -> None:
    current = Workspace.create(tmp_path)
    with Workspace.transaction(current) as t:
        t.register_dataset(_registration("one"), _source())
    stale = Workspace.open(tmp_path)

    with Workspace.transaction(current) as t:
        t.register_dataset(_registration("two"), _source())
    with Workspace.transaction(stale) as t:
        t.register_dataset(_registration("three"), _source())

    assert [str(item.dataset_id) for item in Workspace.open(tmp_path).datasets] == [
        "one",
        "three",
        "two",
    ]


def test_idempotent_registration_rechecks_that_workspace_still_exists(tmp_path: Path) -> None:
    registration = _registration()
    workspace = Workspace.create(tmp_path)
    with Workspace.transaction(workspace) as t:
        t.register_dataset(registration, _source())
    workspace.path.unlink()

    with pytest.raises(VqaprError) as caught, Workspace.transaction(workspace) as t:
        t.register_dataset(registration, _source())

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.missing"
    assert not workspace.path.exists()


def test_source_spec_survives_reopening_the_workspace(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    source = _source()

    with Workspace.transaction(workspace) as t:
        t.register_dataset(_registration(), source)

    assert Workspace.open(tmp_path).source("prices") == source


def test_invalid_dataset_id_lookup_is_a_structured_failure(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)

    with pytest.raises(VqaprError) as caught:
        workspace.dataset("bad id")

    payload = caught.value.as_dict()
    assert payload["stage"] == "lookup"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "dataset.reference_invalid"


def test_missing_dataset_lookup_is_a_structured_failure(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)

    with pytest.raises(VqaprError) as caught:
        workspace.dataset("missing")

    payload = caught.value.as_dict()
    assert payload["stage"] == "lookup"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "dataset.unregistered"


def test_registration_rejects_a_mismatched_source_without_mutation(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught, Workspace.transaction(workspace) as t:
        t.register_dataset(_registration(), SourceSpec.of("other", "prepared/other"))

    payload = caught.value.as_dict()
    assert payload["stage"] == "register"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "dataset.source_mismatch"
    assert workspace.path.read_bytes() == before


def test_conflicting_source_spec_fails_without_mutation(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    with Workspace.transaction(workspace) as t:
        t.register_dataset(_registration(), _source())
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught, Workspace.transaction(workspace) as t:
        t.register_dataset(
            _registration("price_adjusted"),
            _source(hive_partitioned=False),
        )

    payload = caught.value.as_dict()
    assert payload["stage"] == "register"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "dataset.source_conflict"
    assert workspace.path.read_bytes() == before


@pytest.mark.parametrize(
    ("raw_source_id", "code"),
    [
        ("bad id", "source.reference_invalid"),
        ("missing", "source.unregistered"),
    ],
)
def test_source_lookup_failures_are_structured(
    tmp_path: Path, raw_source_id: str, code: str
) -> None:
    workspace = Workspace.create(tmp_path)

    with pytest.raises(VqaprError) as caught:
        workspace.source(raw_source_id)

    payload = caught.value.as_dict()
    assert payload["stage"] == "lookup"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == code


def test_a_venue_dataset_round_trips_its_execution_role(
    tmp_path: Path, execution_parquet: Path
) -> None:
    workspace = Workspace.create(tmp_path)
    expected = _venue()
    source = SourceSpec.of("krx-execution", execution_parquet)

    with Workspace.transaction(workspace) as t:
        assert t.register_dataset(expected, source) is True

    reopened = Workspace.open(tmp_path)
    assert reopened.dataset("krx-daily") == expected
    assert reopened.dataset("krx-daily").execution is not None
    assert reopened.dataset("krx-daily").execution.is_tradable == "is_tradable"
    assert reopened.source("krx-execution") == source


def test_a_document_still_declaring_execution_inputs_is_refused_by_name(
    tmp_path: Path,
) -> None:
    """`execution_inputs:` is retired (record 185); the refusal says where the fill went."""
    workspace_path = tmp_path / ".vqapr" / "workspace.yaml"
    workspace_path.parent.mkdir(parents=True)
    workspace_path.write_text(
        "sources: {}\ndatasets: {}\nexecution_inputs:\n  krx-daily:\n    trade_price: close\n",
        encoding="utf-8",
    )

    with pytest.raises(VqaprError, match="execution_inputs is retired"):
        Workspace.open(tmp_path)


def test_legacy_workspace_without_components_or_runs_still_opens(tmp_path: Path) -> None:
    workspace_path = tmp_path / ".vqapr" / "workspace.yaml"
    workspace_path.parent.mkdir(parents=True)
    workspace_path.write_text("sources: {}\ndatasets: {}\n", encoding="utf-8")

    workspace = Workspace.open(tmp_path)

    assert workspace.datasets == ()


def test_datamodel_component_round_trips_through_workspace(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    expected = ComponentRef.of(
        "reversal",
        ComponentKind.DATA_MODEL,
        tmp_path / "reversal.py",
        "ReversalModel",
        config={"window": 20},
        fingerprint="a" * 64,
    )

    with Workspace.transaction(workspace) as t:
        assert t.register_component(expected) is True
    assert Workspace.open(tmp_path).component("reversal") == expected
    assert Workspace.open(tmp_path).components == (expected,)


def test_legacy_workspace_without_components_still_opens(tmp_path: Path) -> None:
    workspace_path = tmp_path / ".vqapr" / "workspace.yaml"
    workspace_path.parent.mkdir(parents=True)
    workspace_path.write_text("sources: {}\ndatasets: {}\nruns: {}\n", encoding="utf-8")

    workspace = Workspace.open(tmp_path)

    assert workspace.components == ()


def _make_legacy(workspace: Workspace, count: int) -> None:
    """Rewrite the first `count` registrations into the exact shape they had before spans.

    The `span:` key and its two quoted ISO entries are removed and nothing else, so the result is
    valid YAML carrying exactly the five legacy keys -- a genuinely old document rather than a
    corrupt one.
    """
    kept: list[str] = []
    dropping = False
    stripped = 0
    for line in workspace.path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "span:" and stripped < count:
            dropping = True
            stripped += 1
            continue
        if dropping:
            if line.lstrip().startswith("- '"):
                continue
            dropping = False
        kept.append(line)
    assert stripped == count, "the fixture did not strip the spans it meant to"
    workspace.path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def test_a_workspace_holding_a_pre_span_registration_still_opens(tmp_path: Path) -> None:
    """The migration path must not take the workspace offline to repair the workspace.

    Decode enforces exact key-set equality across the whole document, and `open` and `create`
    both read before they write. A refusal here would therefore block `list` from reporting what
    needs fixing AND block `register` from fixing it -- the refusal would be advertising a
    command it had itself disabled. Stale entries are quarantined instead.
    """
    workspace = Workspace.create(tmp_path)
    for name in ("alpha", "beta", "gamma"):
        with Workspace.transaction(workspace) as t:
            t.register_dataset(_registration(name), _source())
    _make_legacy(workspace, 2)

    reopened = Workspace.open(tmp_path)

    assert sorted(str(item.dataset_id) for item in reopened.datasets) == [
        "alpha",
        "beta",
        "gamma",
    ], "a quarantined registration must still be enumerable, or nothing can report it"


def test_using_a_quarantined_registration_names_the_command_that_repairs_it(
    tmp_path: Path,
) -> None:
    """Admitted at decode, refused at use. Nothing may consume a registration without a span."""
    workspace = Workspace.create(tmp_path)
    for name in ("alpha", "gamma"):
        with Workspace.transaction(workspace) as t:
            t.register_dataset(_registration(name), _source())
    _make_legacy(workspace, 1)
    reopened = Workspace.open(tmp_path)

    with pytest.raises(VqaprError) as refused:
        reopened.dataset("alpha")

    failure = refused.value.failures[0]
    assert failure.code == "dataset.span_absent"
    assert "alpha" in (failure.observed or "")
    assert "vqapr register <declaration.yaml>" in (refused.value.retry_precondition or "")

    # The healthy registration is untouched by its neighbour's quarantine.
    assert reopened.span("gamma") == _SPAN


def test_the_advertised_repair_command_actually_runs(tmp_path: Path) -> None:
    """The property the whole quarantine design exists for.

    A refusal naming a repair that its own refusal blocks is worse than no message at all: it
    sends the reader in a circle. This drives the repair for real, one dataset at a time, and
    checks the others survive it -- `register_dataset` rewrites the entire document, so a
    neighbour's missing span must not fail the write.
    """
    workspace = Workspace.create(tmp_path)
    for name in ("alpha", "beta", "gamma"):
        with Workspace.transaction(workspace) as t:
            t.register_dataset(_registration(name), _source())
    _make_legacy(workspace, 2)

    with Workspace.transaction(tmp_path) as t:
        t.register_dataset(_registration("alpha"), _source())

    repaired = Workspace.open(tmp_path)
    assert repaired.span("alpha") == _SPAN
    assert repaired.span("gamma") == _SPAN, "repairing one dataset disturbed a healthy one"
    with pytest.raises(VqaprError) as still_stale:
        repaired.dataset("beta")
    assert still_stale.value.failures[0].code == "dataset.span_absent"

    with Workspace.transaction(tmp_path) as t:
        t.register_dataset(_registration("beta"), _source())
    final = Workspace.open(tmp_path)
    assert all(final.span(name) == _SPAN for name in ("alpha", "beta", "gamma"))


def test_repairing_a_quarantined_registration_may_not_change_its_declaration(
    tmp_path: Path,
) -> None:
    """Adding the measurement is a repair; changing what the dataset means is a new dataset.

    The conflict check compares whole registrations, so it has to ignore the span to let a repair
    through. Ignoring the rest along with it would let a re-registration silently redefine the
    dataset under cover of the migration.
    """
    workspace = Workspace.create(tmp_path)
    with Workspace.transaction(workspace) as t:
        t.register_dataset(_registration("alpha"), _source())
    _make_legacy(workspace, 1)

    with pytest.raises(VqaprError) as refused, Workspace.transaction(tmp_path) as t:
        t.register_dataset(_registration("alpha", key_fields=("instrument",)), _source())

    assert refused.value.failures[0].code == "dataset.registered"


def _make_undeclared(workspace: Workspace, count: int) -> None:
    """Rewrite the first `count` registrations into the shape they had before `field_types`.

    The `field_types:` key and its indented entries are removed and nothing else: a document
    written before `docs/issues/archive/088`, not a corrupt one.
    """
    kept: list[str] = []
    dropping = False
    stripped = 0
    for line in workspace.path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "field_types:" and stripped < count:
            dropping = True
            stripped += 1
            continue
        if dropping:
            if len(line) - len(line.lstrip()) > 4:
                continue
            dropping = False
        kept.append(line)
    assert stripped == count, "the fixture did not strip the field_types it meant to"
    workspace.path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def test_a_registration_without_field_types_is_quarantined_not_a_deadlock(tmp_path: Path) -> None:
    """`docs/issues/archive/088`: the same quarantine as a missing span, for the key it introduced.

    An entry that predates `field_types` still opens and lists (or nothing could report it),
    every read on it is refused by name until its author declares the types, and registering it
    again with them is the repair -- through the same `register` the refusal advertises.
    """
    from vqapr.data.datasets import require_declared

    workspace = Workspace.create(tmp_path)
    for name in ("alpha", "gamma"):
        with Workspace.transaction(workspace) as t:
            t.register_dataset(_registration(name), _source())
    _make_undeclared(workspace, 1)

    reopened = Workspace.open(tmp_path)
    assert sorted(str(item.dataset_id) for item in reopened.datasets) == ["alpha", "gamma"]
    assert reopened.dataset("alpha").field_types is None
    assert reopened.dataset("gamma") == _registration("gamma")

    with pytest.raises(VqaprError) as refused:
        require_declared(reopened.dataset("alpha"))
    failure = refused.value.failures[0]
    assert failure.code == "dataset.field_types_undeclared"
    assert "alpha" in (failure.observed or "")
    assert "field_types:" in failure.fix, "the refusal must name the key that repairs it"

    with Workspace.transaction(tmp_path) as t:
        assert t.register_dataset(_registration("alpha"), _source()) is True
    assert Workspace.open(tmp_path).dataset("alpha") == _registration("alpha")


def test_reading_a_span_does_not_touch_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason the span is persisted at all.

    `evaluation_times` answers a neighbouring question by scanning the source. If reading two
    endpoints also required a scan, persisting them would have bought nothing. The registered
    path here does not exist, but absence alone is weak evidence -- a future implementation could
    open the file only when some cache missed. So the scan entry points are replaced with traps:
    reaching one is the failure, not merely being slow.
    """
    workspace = Workspace.create(tmp_path)
    with Workspace.transaction(workspace) as t:
        t.register_dataset(_registration(), _source())

    def _trap(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("reading a persisted span must not open the source")

    for name in ("span_check", "distinct_values", "describe", "key_check"):
        monkeypatch.setattr(scan, name, _trap)

    assert Workspace.open(tmp_path).span("price_daily") == _SPAN


def test_persistence_refuses_a_registration_whose_span_was_never_measured(
    tmp_path: Path,
) -> None:
    """Storing a span-less registration would oblige the decoder to accept one forever.

    The refusal names the entry point that measures it rather than measuring here: this method is
    a metadata write and opens no source, and re-measuring would be a second read of a file
    validation already read end to end.
    """
    workspace = Workspace.create(tmp_path)
    unmeasured = DatasetRegistration.of(
        "price_daily",
        "prices",
        instrument_field="instrument",
        available_at="available_at",
        grain="rows",
        key_fields=("session_date", "instrument"),
        fields={"close": "close"},
        field_types={"close": "INTEGER"},
    )

    with pytest.raises(VqaprError) as refused, Workspace.transaction(workspace) as t:
        t.register_dataset(unmeasured, _source())

    assert refused.value.failures[0].code == "dataset.span_absent"
    assert "register_dataset" in (refused.value.retry_precondition or "")


def test_a_workspace_reads_a_datasets_instants_and_hashes_its_file_once_per_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record `238`: the judgments and the freeze both derive the run's agenda from the execution
    table's distinct instants, and both verify the file's digest. The sample project's `vqapr
    run` scanned that column twice for the agenda and three times for the horizon, and a changed
    file was hashed once by the judgment that refused it and again by preflight
    (`experiments/exp_238`). A workspace object is one command's snapshot, so each fact is read
    once for its life -- including the digest of a file whose compare FAILS."""
    import duckdb

    from vqapr.data.validation import verify_source
    from vqapr.project import store as store_module

    path = tmp_path / "prices.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (SELECT * FROM (VALUES
                (TIMESTAMPTZ '2024-01-02 15:30:00+00', 'A', 1.0::DOUBLE),
                (TIMESTAMPTZ '2024-01-03 15:30:00+00', 'A', 2.0::DOUBLE),
                (TIMESTAMPTZ '2024-01-03 15:30:00+00', 'B', 3.0::DOUBLE)
            ) AS t(available_at, instrument, close))
            TO '{path.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        con.close()
    registration = DatasetRegistration.of(
        "prices",
        "prices-source",
        instrument_field="instrument",
        available_at="available_at",
        grain="instrument_instant",
        key_fields=("available_at", "instrument"),
        fields={"close": "close"},
        field_types={"close": "DOUBLE"},
    )
    source = SourceSpec.of("prices-source", path)
    diagnosis, _, measured = verify_source(registration, source)
    diagnosis.raise_if_failed()
    with Workspace.transaction(tmp_path) as t:
        t.register_dataset(measured, source)

    scans: list[str] = []
    original_scan = store_module.scan.distinct_values

    def counted_scan(spec, field, **kwargs):
        scans.append(field)
        return original_scan(spec, field, **kwargs)

    hashes: list[str] = []
    original_hash = store_module.physical_digest

    def counted_hash(target):
        hashes.append(str(target))
        return original_hash(target)

    monkeypatch.setattr(store_module.scan, "distinct_values", counted_scan)
    monkeypatch.setattr(store_module, "physical_digest", counted_hash)

    workspace = Workspace.open(tmp_path)
    instants = workspace.evaluation_times("prices")
    assert [moment.astimezone(UTC).isoformat() for moment in instants] == [
        "2024-01-02T15:30:00+00:00",
        "2024-01-03T15:30:00+00:00",
    ]
    assert workspace.evaluation_times("prices") is instants
    assert scans == ["available_at"], f"the instants were scanned {len(scans)} times"
    workspace.require_verified("prices")
    workspace.require_verified("prices")
    assert len(hashes) == 1, f"the file was hashed {len(hashes)} times"

    # The compare fails on other bytes -- and still hashes once, however many doors ask.
    path.write_bytes(path.read_bytes() + b"\n")
    changed = Workspace.open(tmp_path)
    hashes.clear()
    for _ in range(2):
        with pytest.raises(VqaprError) as refused:
            changed.require_verified("prices")
        assert refused.value.failures[0].code == "dataset.source_changed"
    assert len(hashes) == 1, f"a failed compare hashed the file {len(hashes)} times"
