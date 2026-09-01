"""`workspace.py` — project 선언을 명령 사이에 보존한다."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest

from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data import scan
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.sources import SourceSpec
from vqapr.domain.errors import VqaprError
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import StrategyConfig
from vqapr.runtime.agendas import OperationAgenda, OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig
from vqapr.workspace import Workspace

# A span these tests supply directly. Persistence requires one, because the span is measured
# during validation and a stored registration missing it would force the next reader to re-read
# the whole source. These cases exercise the metadata write in isolation against a path that
# deliberately does not exist, so they attach the measurement rather than perform it.
_SPAN = (
    datetime(2024, 1, 2, 15, 30, tzinfo=UTC),
    datetime(2025, 1, 2, 15, 30, tzinfo=UTC),
)


def _registration(raw_id: str = "price_daily", **overrides) -> DatasetRegistration:
    # Field ids are unique across a workspace, so a helper that builds several registrations has
    # to give each one its own names. The default dataset keeps the bare ones the assertions
    # below read; every other dataset carries its id in them.
    suffix = "" if raw_id == "price_daily" else f"_{raw_id.replace('-', '_')}"
    kwargs = {
        "instrument_field": "instrument",
        "available_at": "available_at",
        "key_fields": ("session_date", "instrument"),
        "fields": {f"close{suffix}": "close", f"session_date{suffix}": "session_date"},
    }
    kwargs.update(overrides)
    return DatasetRegistration.of(raw_id, "prices", **kwargs).with_span(*_SPAN)


def _source(**overrides) -> SourceSpec:
    kwargs = {"hive_partitioned": True}
    kwargs.update(overrides)
    return SourceSpec.of("prices", "prepared/price_daily", **kwargs)


def _execution(
    path: Path, raw_id: str = "krx-daily", *, trade_price: str = "close"
) -> ExecutionInputRegistration:
    return ExecutionInputRegistration.of(
        raw_id,
        ExecutionTableSpec(
            source=SourceSpec.of("krx-execution", path),
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={"open": "open", "close": "close"},
        ),
        FillConvention(
            selector=FillSelector.NEXT_ELIGIBLE,
            local_time=time(15, 30),
            timezone="Asia/Seoul",
            trade_price=trade_price,
        ),
    )


def _agenda(raw_id: str, role: OperationRole) -> OperationAgenda:
    return OperationAgenda.from_occurrences(
        agenda_id=raw_id,
        role=role,
        timezone="Asia/Seoul",
        occurrences=(
            OperationOccurrence(
                f"{raw_id}-1",
                role,
                LocalInstantDeclaration(date(2024, 3, 5), time(15, 30), "Asia/Seoul", 0, "+09:00"),
            ),
        ),
        provenance="test fixture",
    )


def test_registration_survives_reopening_the_workspace(tmp_path: Path) -> None:
    expected = _registration()
    workspace = Workspace.create(tmp_path)

    assert workspace.register_dataset(expected, _source()) is True

    reopened = Workspace.open(tmp_path)
    assert reopened.dataset("price_daily") == expected


def test_two_datasets_are_both_queryable_after_reopen(tmp_path: Path) -> None:
    first = _registration()
    # Field ids are unique across the workspace, so a second dataset over the same source
    # exposes its own name rather than shadowing the first one's.
    second = _registration("price_adjusted", fields={"adjusted_close": "adjusted_close"})
    workspace = Workspace.create(tmp_path)

    workspace.register_dataset(first, _source())
    workspace.register_dataset(second, _source())

    reopened = Workspace.open(tmp_path)
    assert {item.dataset_id: item for item in reopened.datasets} == {
        first.dataset_id: first,
        second.dataset_id: second,
    }


def test_identical_reregistration_is_an_idempotent_noop(tmp_path: Path) -> None:
    registration = _registration()
    workspace = Workspace.create(tmp_path)
    assert workspace.register_dataset(registration, _source()) is True
    before = workspace.path.read_bytes()

    assert workspace.register_dataset(_registration(), _source()) is False
    assert workspace.path.read_bytes() == before


def test_conflicting_reregistration_fails_without_mutation(tmp_path: Path) -> None:
    original = _registration()
    workspace = Workspace.create(tmp_path)
    workspace.register_dataset(original, _source())
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        workspace.register_dataset(_registration(fields={"open": "open"}), _source())

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["stage"] == "workspace.dataset.register"
    assert [failure["code"] for failure in payload["failures"]] == [
        "workspace.dataset.register.conflict"
    ]
    assert workspace.path.read_bytes() == before
    assert Workspace.open(tmp_path).dataset("price_daily") == original


def test_opening_a_missing_workspace_is_a_structured_failure(tmp_path: Path) -> None:
    with pytest.raises(VqaprError) as caught:
        Workspace.open(tmp_path)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.open.missing"


def test_opening_malformed_yaml_is_a_structured_failure(tmp_path: Path) -> None:
    path = tmp_path / ".vqapr" / "workspace.yaml"
    path.parent.mkdir()
    path.write_text("datasets: [not, a, mapping]", encoding="utf-8")

    with pytest.raises(VqaprError) as caught:
        Workspace.open(tmp_path)

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.open.invalid"


def test_explicit_workspaces_do_not_share_declarations(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = Workspace.create(first_root)
    second = Workspace.create(second_root)

    first.register_dataset(_registration(), _source())
    second.register_dataset(_registration("fundamentals"), _source())

    assert [str(item.dataset_id) for item in Workspace.open(first_root).datasets] == ["price_daily"]
    assert [str(item.dataset_id) for item in Workspace.open(second_root).datasets] == [
        "fundamentals"
    ]


def test_direct_construction_cannot_bypass_an_existing_workspace(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    workspace.register_dataset(_registration(), _source())
    before = workspace.path.read_bytes()

    with pytest.raises(TypeError, match=r"Workspace\.create.*Workspace\.open"):
        Workspace(tmp_path, {})

    assert workspace.path.read_bytes() == before


def test_stale_instance_merges_with_current_durable_state(tmp_path: Path) -> None:
    current = Workspace.create(tmp_path)
    current.register_dataset(_registration("one"), _source())
    stale = Workspace.open(tmp_path)

    current.register_dataset(_registration("two"), _source())
    stale.register_dataset(_registration("three"), _source())

    assert [str(item.dataset_id) for item in Workspace.open(tmp_path).datasets] == [
        "one",
        "three",
        "two",
    ]


def test_idempotent_registration_rechecks_that_workspace_still_exists(tmp_path: Path) -> None:
    registration = _registration()
    workspace = Workspace.create(tmp_path)
    workspace.register_dataset(registration, _source())
    workspace.path.unlink()

    with pytest.raises(VqaprError) as caught:
        workspace.register_dataset(registration, _source())

    payload = caught.value.as_dict()
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.open.missing"
    assert not workspace.path.exists()


def test_source_spec_survives_reopening_the_workspace(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    source = _source()

    workspace.register_dataset(_registration(), source)

    assert Workspace.open(tmp_path).source("prices") == source


def test_invalid_dataset_id_lookup_is_a_structured_failure(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)

    with pytest.raises(VqaprError) as caught:
        workspace.dataset("bad id")

    payload = caught.value.as_dict()
    assert payload["stage"] == "workspace.dataset.lookup"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.dataset.lookup.invalid"


def test_missing_dataset_lookup_is_a_structured_failure(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)

    with pytest.raises(VqaprError) as caught:
        workspace.dataset("missing")

    payload = caught.value.as_dict()
    assert payload["stage"] == "workspace.dataset.lookup"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.dataset.lookup.missing"


def test_registration_rejects_a_mismatched_source_without_mutation(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        workspace.register_dataset(_registration(), SourceSpec.of("other", "prepared/other"))

    payload = caught.value.as_dict()
    assert payload["stage"] == "workspace.dataset.register"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.dataset.register.source_mismatch"
    assert workspace.path.read_bytes() == before


def test_conflicting_source_spec_fails_without_mutation(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    workspace.register_dataset(_registration(), _source())
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        workspace.register_dataset(
            _registration("price_adjusted"),
            _source(hive_partitioned=False),
        )

    payload = caught.value.as_dict()
    assert payload["stage"] == "workspace.dataset.register"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == "workspace.dataset.register.source_conflict"
    assert workspace.path.read_bytes() == before


@pytest.mark.parametrize(
    ("raw_source_id", "code"),
    [
        ("bad id", "workspace.source.lookup.invalid"),
        ("missing", "workspace.source.lookup.missing"),
    ],
)
def test_source_lookup_failures_are_structured(
    tmp_path: Path, raw_source_id: str, code: str
) -> None:
    workspace = Workspace.create(tmp_path)

    with pytest.raises(VqaprError) as caught:
        workspace.source(raw_source_id)

    payload = caught.value.as_dict()
    assert payload["stage"] == "workspace.source.lookup"
    assert payload["mutation"] is False
    assert payload["failures"][0]["code"] == code


def test_execution_input_round_trips_through_workspace(
    tmp_path: Path, execution_parquet: Path
) -> None:
    workspace = Workspace.create(tmp_path)
    expected = _execution(execution_parquet)

    assert workspace.register_execution_input(expected) is True

    reopened = Workspace.open(tmp_path)
    assert reopened.execution_input("krx-daily") == expected
    assert reopened.execution_inputs == (expected,)
    assert reopened.source("krx-execution") == expected.table.source


def test_execution_input_round_trips_fill_dst_proof(
    tmp_path: Path, execution_parquet: Path
) -> None:
    workspace = Workspace.create(tmp_path)
    base = _execution(execution_parquet)
    expected = ExecutionInputRegistration.of(
        str(base.execution_input_id),
        base.table,
        FillConvention(
            selector=base.fill.selector,
            local_time=base.fill.local_time,
            timezone=base.fill.timezone,
            trade_price=base.fill.trade_price,
            fold=1,
            offset="+09:00",
        ),
    )

    assert workspace.register_execution_input(expected) is True
    assert Workspace.open(tmp_path).execution_input("krx-daily") == expected


def test_workspace_rejects_old_fill_schema_without_dst_proof(
    tmp_path: Path, execution_parquet: Path
) -> None:
    workspace = Workspace.create(tmp_path)
    workspace.register_execution_input(_execution(execution_parquet))
    path = workspace.path
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("      fold: null\n", "")
        .replace("      offset: null\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(VqaprError, match="old fill schema"):
        Workspace.open(tmp_path)


def test_execution_input_registration_is_idempotent(
    tmp_path: Path, execution_parquet: Path
) -> None:
    workspace = Workspace.create(tmp_path)
    registration = _execution(execution_parquet)

    assert workspace.register_execution_input(registration) is True
    before = workspace.path.read_bytes()
    assert workspace.register_execution_input(registration) is False
    assert workspace.path.read_bytes() == before


def test_conflicting_execution_input_fails_without_mutation(
    tmp_path: Path, execution_parquet: Path
) -> None:
    workspace = Workspace.create(tmp_path)
    workspace.register_execution_input(_execution(execution_parquet))
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        workspace.register_execution_input(_execution(execution_parquet, trade_price="open"))

    assert caught.value.stage == "workspace.execution_input.register"
    assert caught.value.mutation is False
    assert caught.value.failures[0].code == "workspace.execution_input.register.conflict"
    assert workspace.path.read_bytes() == before


def test_legacy_workspace_without_execution_inputs_still_opens(tmp_path: Path) -> None:
    workspace_path = tmp_path / ".vqapr" / "workspace.yaml"
    workspace_path.parent.mkdir(parents=True)
    workspace_path.write_text("sources: {}\ndatasets: {}\n", encoding="utf-8")

    workspace = Workspace.open(tmp_path)

    assert workspace.datasets == ()
    assert workspace.execution_inputs == ()


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

    assert workspace.register_component(expected) is True
    assert Workspace.open(tmp_path).component("reversal") == expected
    assert Workspace.open(tmp_path).components == (expected,)


def test_legacy_workspace_without_components_still_opens(tmp_path: Path) -> None:
    workspace_path = tmp_path / ".vqapr" / "workspace.yaml"
    workspace_path.parent.mkdir(parents=True)
    workspace_path.write_text("sources: {}\ndatasets: {}\nexecution_inputs: {}\n", encoding="utf-8")

    workspace = Workspace.open(tmp_path)

    assert workspace.components == ()


def test_operation_declarations_round_trip_with_registered_references(tmp_path: Path) -> None:
    workspace = Workspace.create(tmp_path)
    component = ComponentRef.of(
        "strategy",
        ComponentKind.STRATEGY_MODEL,
        tmp_path / "strategy.py",
        "Strategy",
        fingerprint="b" * 64,
    )
    strategy_agenda = _agenda("strategy-agenda", OperationRole.STRATEGY_CALLBACK)
    valuation_agenda = _agenda("valuation-agenda", OperationRole.VALUATION)
    monitoring_agenda = _agenda("monitoring-agenda", OperationRole.MONITORING)
    workspace.register_component(component)
    workspace.register_dataset(_registration(), _source())
    for agenda in (strategy_agenda, valuation_agenda, monitoring_agenda):
        assert workspace.register_agenda(agenda) is True
    strategy = StrategyConfig(component, strategy_agenda.agenda_id, OperationRole.STRATEGY_CALLBACK)
    valuation = ValuationConfig(
        valuation_agenda.agenda_id,
        OperationRole.VALUATION,
    )
    monitoring = MonitoringPolicy(monitoring_agenda.agenda_id, OperationRole.MONITORING)

    assert workspace.register_strategy_config(strategy) is True
    assert workspace.register_valuation_config(valuation) is True
    assert workspace.register_monitoring_policy(monitoring) is True
    before = workspace.path.read_bytes()
    assert workspace.register_agenda(strategy_agenda) is False
    assert workspace.path.read_bytes() == before

    reopened = Workspace.open(tmp_path)
    assert reopened.agenda("strategy-agenda") == strategy_agenda
    assert reopened.strategy_config("strategy-agenda") == strategy
    assert reopened.valuation_config("valuation-agenda") == valuation
    assert reopened.monitoring_policy("monitoring-agenda") == monitoring


def test_agenda_conflict_and_invalid_persisted_identity_leave_workspace_unchanged(
    tmp_path: Path,
) -> None:
    workspace = Workspace.create(tmp_path)
    agenda = _agenda("strategy-agenda", OperationRole.STRATEGY_CALLBACK)
    workspace.register_agenda(agenda)
    before = workspace.path.read_bytes()

    with pytest.raises(VqaprError) as caught:
        workspace.register_agenda(
            OperationAgenda.from_occurrences(
                agenda_id="strategy-agenda",
                role=OperationRole.STRATEGY_CALLBACK,
                timezone="Asia/Seoul",
                occurrences=(),
                provenance="different",
            )
        )

    assert caught.value.failures[0].code == "workspace.agenda.register.conflict"
    assert workspace.path.read_bytes() == before
    workspace.path.write_text(
        workspace.path.read_text(encoding="utf-8").replace(agenda.content_identity, "0" * 64),
        encoding="utf-8",
    )
    with pytest.raises(VqaprError) as invalid:
        Workspace.open(tmp_path)
    assert invalid.value.failures[0].code == "workspace.open.invalid"


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
        workspace.register_dataset(_registration(name), _source())
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
        workspace.register_dataset(_registration(name), _source())
    _make_legacy(workspace, 1)
    reopened = Workspace.open(tmp_path)

    with pytest.raises(VqaprError) as refused:
        reopened.dataset("alpha")

    failure = refused.value.failures[0]
    assert failure.code == "dataset.register.span.absent"
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
        workspace.register_dataset(_registration(name), _source())
    _make_legacy(workspace, 2)

    Workspace.open(tmp_path).register_dataset(_registration("alpha"), _source())

    repaired = Workspace.open(tmp_path)
    assert repaired.span("alpha") == _SPAN
    assert repaired.span("gamma") == _SPAN, "repairing one dataset disturbed a healthy one"
    with pytest.raises(VqaprError) as still_stale:
        repaired.dataset("beta")
    assert still_stale.value.failures[0].code == "dataset.register.span.absent"

    Workspace.open(tmp_path).register_dataset(_registration("beta"), _source())
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
    workspace.register_dataset(_registration("alpha"), _source())
    _make_legacy(workspace, 1)

    with pytest.raises(VqaprError) as refused:
        Workspace.open(tmp_path).register_dataset(
            _registration("alpha", key_fields=("instrument",)), _source()
        )

    assert refused.value.failures[0].code == "workspace.dataset.register.conflict"


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
    workspace.register_dataset(_registration(), _source())

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
        key_fields=("session_date", "instrument"),
        fields={"close": "close"},
    )

    with pytest.raises(VqaprError) as refused:
        workspace.register_dataset(unmeasured, _source())

    assert refused.value.failures[0].code == "dataset.register.span.absent"
    assert "register_dataset" in (refused.value.retry_precondition or "")
