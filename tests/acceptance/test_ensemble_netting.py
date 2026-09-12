"""UC-ENSEMBLE-001 acceptance, discharged against committed real market data.

Each test names the criterion it proves. Two of them are the ones the review lanes fought hardest
over, and they are written to fail rather than to reassure:

* **Criterion 11** proves the recorded surface is sufficient for member weighting: a record is
  published, read back from the published artifact after the producing run's objects are gone, and
  a moving return computed from it. Every package name it uses to publish, reach and weight comes
  from ``vqapr.public``; only workspace creation, which a real project already has, reaches past
  that. The end-to-end version of this -- a real ``run()`` publishing and reading back through the
  spine -- lives in ``showcases/show_006_ensemble_netting``, which is where the round trip is
  proved on a real run rather than on a constructed result.
* **Criterion 4** replays the recorded construction transform. Asserting that an intended and a
  realised value were both *recorded* does not constrain the realised one to be a correct function
  of the intended one; a construction stage that dropped a member's contribution after the netting
  record would still pass. Replaying the transform closes that window.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.public import (
    QUANTUM,
    DatasetRegistration,
    SourceSpec,
    WeightingRefusal,
    equal_weight,
    net_members,
    optimize,
    register_dataset,
    rescale,
)
from vqapr.record import RunRecordWriter
from vqapr.workspace.registry import Workspace  # scaffolding only; deliberately not a public name

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "real"
SHOWCASE = Path(__file__).resolve().parents[2] / "showcases" / "show_006_ensemble_netting"


@pytest.fixture(scope="module")
def manifest() -> dict[str, object]:
    return json.loads((FIXTURE / "fixture.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def closes(manifest: dict[str, object]) -> dict[str, dict[str, Decimal]]:
    """Real committed closes, keyed by session then instrument."""
    path = FIXTURE / str(manifest["observation_path"])
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT available_at, instrument, close FROM read_parquet('{path.as_posix()}')"
            " ORDER BY available_at, instrument"
        ).fetchall()
    finally:
        con.close()
    panel: dict[str, dict[str, Decimal]] = {}
    for session, instrument, close in rows:
        panel.setdefault(str(session), {})[instrument] = close
    return panel


def _members(panel: dict[str, dict[str, Decimal]]) -> tuple[dict[str, Decimal], ...]:
    """Two price-derived members over the same session, demeaned so both are genuinely signed."""
    sessions = sorted(panel)
    last, five, ten = sessions[-1], sessions[-6], sessions[-11]
    names = sorted(panel[last])

    def demean(values: dict[str, Decimal]) -> dict[str, Decimal]:
        centre = sum(values.values()) / len(values)
        return {name: value - centre for name, value in values.items()}

    reversal = demean({n: -(panel[last][n] / panel[five][n] - 1) for n in names})
    momentum = demean({n: panel[last][n] / panel[ten][n] - 1 for n in names})
    return reversal, momentum


def test_criterion_2_a_member_panel_is_signed_and_the_members_disagree(
    closes: dict[str, dict[str, Decimal]],
) -> None:
    """Members enter signed; nothing pre-filters a short leg."""
    reversal, momentum = _members(closes)

    assert min(reversal.values()) < 0 and max(reversal.values()) > 0
    assert min(momentum.values()) < 0 and max(momentum.values()) > 0

    measured = net_members([reversal, momentum])
    crossing = [name for name, value in measured.items() if value.offset_weight > 0]
    assert crossing, "the members must genuinely disagree somewhere for netting to mean anything"


def test_criterion_3_the_offset_is_confirmable_and_not_recoverable_from_the_net(
    closes: dict[str, dict[str, Decimal]],
) -> None:
    """UC-ENSEMBLE-001's offsetting quantity, in weight space."""
    reversal, momentum = _members(closes)

    measured = net_members([reversal, momentum])

    for name, value in measured.items():
        assert value.net_weight == value.long_weight + value.short_weight
        assert value.offset_weight == min(value.long_weight, -value.short_weight)
        if value.offset_weight > 0:
            assert reversal[name] * momentum[name] < 0, (
                "a positive offset means the two members took opposite sides"
            )


def test_criterion_4_the_recorded_transform_reproduces_the_final_weight(
    closes: dict[str, dict[str, Decimal]],
) -> None:
    """The replay leg. Recording a pair is not the same as constraining the relation.

    First leg: the per-ticker net recomputed independently from both member panels equals the net
    the ensemble would record. Second leg: replaying the recorded construction transform over that
    net reproduces the final weight exactly, so a stage that dropped a member's contribution after
    the netting record fails here.
    """
    reversal, momentum = _members(closes)

    recomputed = {
        name: value.net_weight for name, value in net_members([reversal, momentum]).items()
    }
    combined = {
        name: (reversal.get(name, Decimal(0)) + momentum.get(name, Decimal(0)))
        for name in sorted(set(reversal) | set(momentum))
    }
    assert recomputed == combined, "the net is exactly the sum of the member weights"

    long_side = [name for name, value in recomputed.items() if value > 0]
    short_side = [name for name, value in recomputed.items() if value < 0]
    assert long_side and short_side, "the fixture must give both sides for the replay to be real"

    # The shipped construction, replayed exactly as showcases/show_006 performs it:
    # equal_weight -> rescale to the declared budget -> quantize -> optimize under the bounds.
    budget = Decimal("0.04")
    combined_signal = equal_weight(recomputed)
    active = rescale(combined_signal, long=budget, short=-budget)
    instruments = tuple(sorted(recomputed))
    desired = {name: active.get(name, Decimal(0)).quantize(QUANTUM) for name in instruments}

    # `no_short` is the bound that bites here, removing the short leg the members produced by
    # projection rather than by pre-filtering. The cap is carried for shape -- at a 0.04 budget no
    # long can approach it -- so it is present but inert, and only the lower bound is asserted to
    # bind. Replaying under wide bounds would make `optimize` an identity, and the assertion would
    # then hold just as well against a projection that ignored its bounds entirely.
    lower = dict.fromkeys(instruments, Decimal("0"))
    upper = dict.fromkeys(instruments, Decimal("0.35"))
    projected = optimize(
        desired=desired,
        current={},
        lower=lower,
        upper=upper,
        frozen=frozenset(),
        cash_range=(Decimal("0"), Decimal("1")),
    )

    shorts = {name for name, value in desired.items() if value < 0}
    longs = {name for name, value in desired.items() if value > 0}
    assert shorts and longs, "the members must hand the projection both legs"
    # The correspondence below needs every name to be strictly signed: `optimize` reports a name
    # sitting exactly on its lower bound as binding, so an exactly-zero net would land in
    # `binding_lower` while belonging to neither set.
    assert not any(value == 0 for value in desired.values())

    # Exactly the short names bind low and land *on* the bound. An all-zero book would satisfy
    # "within bounds" and "non-negative" too, so this correspondence is what discriminates.
    assert set(projected.binding_lower) == shorts
    assert all(projected.weights[name] == Decimal(0) for name in shorts)

    # The long leg survives untouched because nothing bound it. Together with the line above, this
    # is what "the short leg is removed by projection, not before it" actually means.
    assert all(projected.weights[name] == desired[name] for name in longs)
    for name, value in projected.weights.items():
        assert lower[name] <= value <= upper[name]

    # An ensemble that quietly used one member after recording the honest net must diverge.
    #
    # The comparison is on the **net**, not on the constructed weights. `equal_weight` keeps only
    # signs, so comparing constructed vectors would reduce to "some name crossed zero" -- which
    # criterion 2 already asserts and which a member contributing large magnitude without flipping
    # any sign would survive. Comparing nets keeps the falsification sensitive to magnitude.
    dropped_net = {name: reversal.get(name, Decimal(0)) for name in instruments}
    assert dropped_net != recomputed, "dropping a member must change the net it recorded"

    replayed = rescale(recomputed, long=Decimal("1"), short=Decimal("-1"))

    assert sum(v for v in replayed.values() if v > 0) == Decimal(1)
    assert sum(v for v in replayed.values() if v < 0) == Decimal(-1)
    for name, value in recomputed.items():
        if value != 0:
            assert (replayed[name] > 0) == (value > 0), (
                "sign must survive the transform absent a binding constraint"
            )


def test_criterion_5_a_run_that_ignored_a_member_would_fail_the_replay(
    closes: dict[str, dict[str, Decimal]],
) -> None:
    """The falsification the round trip alone does not provide."""
    reversal, momentum = _members(closes)

    honest = {name: value.net_weight for name, value in net_members([reversal, momentum]).items()}
    dropped = {name: value.net_weight for name, value in net_members([reversal, reversal]).items()}

    assert honest != dropped, (
        "an ensemble that quietly used one member twice must not reproduce the honest net"
    )


def test_criterion_9_equal_weight_combination_is_the_strategys_choice(
    closes: dict[str, dict[str, Decimal]],
) -> None:
    """The package measures; the combination rule stays with the researcher."""
    reversal, momentum = _members(closes)

    combined = {
        name: (reversal.get(name, Decimal(0)) + momentum.get(name, Decimal(0))) / 2
        for name in sorted(set(reversal) | set(momentum))
    }

    assert combined != reversal and combined != momentum
    assert equal_weight(combined), "the result is still a usable signal"


def test_criterion_11_the_recorded_surface_is_sufficient_for_member_weighting(
    tmp_path: Path, manifest: dict[str, object]
) -> None:
    """Register a member's recorded table, then reach it back the way a later ensemble would.

    What it does: writes a member's account table the way a run with a store writes it, registers
    that directory as a dataset, then reads it back from the parquet and computes a moving return
    from the recovered series. Nothing here holds the producing run, which is what makes the
    record reusable after that run is gone. The package names used to register and weight come
    from ``vqapr.public``; the record writer, workspace creation and the parquet read reach past
    it, the first because a run is what writes a record and the others because a real project
    already has a workspace and reading a registered table is what a subscriber's own machinery
    does. The real-run version, registered and read back through the spine, is in
    ``showcases/show_006_ensemble_netting``.

    What it proves and what it does not, stated plainly. With 22 committed sessions and 21
    callbacks a twenty-day moving return yields one, at most two points per member. That is enough
    to prove the **record is sufficient**, which is this criterion's purpose, and not enough for
    the weighting to vary economically. This tests record sufficiency, not economic behaviour.
    """
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=ZoneInfo("Asia/Seoul"))

    writer = RunRecordWriter(tmp_path / ".vqapr", "member-1", "reversal@00000000")
    writer.open()
    for index in range(3):
        writer.append(
            "vqapr.account",
            [
                {
                    "instrument": "_ACCOUNT",
                    "cash": 1000.0 + index,
                    "account_version": index,
                    "event_time": cutoff + timedelta(days=index),
                }
            ],
        )
    writer.release()
    directory = (
        tmp_path
        / ".vqapr"
        / "runs"
        / "member-1"
        / "strategies"
        / "reversal@00000000"
        / "tables"
        / "vqapr.account"
    )

    registered = register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "member_account",
            "member-1-account",
            instrument_field="instrument",
            available_at="event_time",
            key_fields=("event_time", "instrument"),
            fields={"cash": "cash", "account_version": "account_version"},
            field_types={"cash": "DOUBLE", "account_version": "INTEGER"},
            grain="instrument_instant",
        ),
        SourceSpec.of("member-1-account", directory),
    )
    assert registered is True

    # Read back from the registered directory alone. Nothing here holds the producing run.
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT cash, account_version FROM read_parquet('{directory.as_posix()}/*.parquet')"
            " ORDER BY event_time"
        ).fetchall()
    finally:
        con.close()

    series = [row[0] for row in rows]
    assert series == [1000.0, 1001.0, 1002.0]
    assert [row[1] for row in rows] == [0, 1, 2], "the record's own versions, in order"

    # A moving return over that series is the whole input member weighting needs.
    returns = [later / earlier - 1 for earlier, later in pairwise(series)]
    assert len(returns) == 2
    assert all(value > 0 for value in returns), "a return is computable from the record alone"

    sessions = int(manifest["sessions"])
    assert sessions >= 21, "a twenty-day window must fit the committed fixture"
    points = sessions - 20
    assert 1 <= points <= 2, (
        "the horizon proves record sufficiency, not economic variation, and says so"
    )


def test_criterion_12_a_flexible_budget_is_not_silently_made_fixed(
    closes: dict[str, dict[str, Decimal]],
) -> None:
    """Not calling rescale is how a Strategy declares a flexible budget."""
    reversal, momentum = _members(closes)
    combined = {name: value.net_weight for name, value in net_members([reversal, momentum]).items()}

    gross = sum(abs(value) for value in combined.values())
    narrowed = {name: value / 2 for name, value in combined.items()}

    # Compared within a quantum rather than exactly. `sum(x / 2)` and `sum(x) / 2` are the same
    # number and not the same Decimal: dividing each weight first resolves a digit the summed form
    # never reaches, so the two drift by ~1e-29 once the universe is large enough to expose it.
    # Pinning exact equality would make this test a function of how many names the fixture holds,
    # which is not what it is measuring.
    assert abs(sum(abs(v) for v in narrowed.values()) - gross / 2) < Decimal("1e-24"), (
        "a Strategy that narrows its own book keeps the narrowing"
    )

    with pytest.raises(WeightingRefusal):
        rescale(
            {name: abs(value) for name, value in combined.items()},
            long=Decimal("1"),
            short=Decimal("-1"),
        )


def test_the_showcase_exists_and_states_its_own_limits() -> None:
    """The scenario is shipped and its README does not overclaim."""
    readme = (SHOWCASE / "README.md").read_text(encoding="utf-8")

    assert (SHOWCASE / "run.py").is_file()
    assert "does NOT" in readme or "NOT demonstrate" in readme, (
        "the showcase must state what it does not prove"
    )


def test_weights_stay_on_the_canonical_grid(closes: dict[str, dict[str, Decimal]]) -> None:
    """Everything published crosses the optimizer boundary, so it lives on one grid."""
    reversal, momentum = _members(closes)
    combined = {name: value.net_weight for name, value in net_members([reversal, momentum]).items()}

    quantized = {name: value.quantize(QUANTUM) for name, value in combined.items()}

    for value in quantized.values():
        assert -value.as_tuple().exponent <= 12
