"""Both members of the lookback pair are reachable from the scaffold, and both run.

`docs/issues/033`. `RowsLookback` and `CalendarLookback` are a deliberate pair -- one indexed by
rows per name, one by calendar time -- and only the first was reachable by following the package:

* `RowsLookback` had no docstring, `CalendarLookback` documented only `lower_bound`;
* `vqapr new datamodel --lookback N` emitted `RowsLookback` unconditionally, with no flag for the
  other;
* the skill named neither class.

The cost is not aesthetic. A rows lookback returns each instrument's own last N observations, so on
an unbalanced panel the batch's calendar span is set by the sparsest name: a real materialization
asked for 313 rows over 1,637 names and got rows spanning **1,865 distinct sessions**, back to 2016.
Consumed the scaffold's way -- accumulate per name, take the last N -- a 2024 correlation matrix
then mixes a liquid name's 2023-24 returns with a delisted name's 2016-19 returns. It is
well-formed, non-null, passes every check, and is wrong.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vqapr.calls import DataModelContext
from vqapr.cli.new import run as new_command
from vqapr.data.datasets import DatasetRegistration
from vqapr.data.lookback import CalendarLookback, RowsLookback
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.extension.component import ComponentKind
from vqapr.extension.loading import load_data_model
from vqapr.extension.scaffold import render
from vqapr.public import Workspace, register_data_model, register_dataset

KST = ZoneInfo("Asia/Seoul")
EVALUATION_TIME = datetime(2024, 3, 7, 16, tzinfo=KST)


def _namespace(**overrides: object) -> argparse.Namespace:
    """The flags `vqapr new` parses, defaulted the way `add_arguments` defaults them."""
    args = {
        "kind": "datamodel",
        "component_id": "cross-sectional",
        "dataset": "price_daily",
        "field": "close",
        # `None` is what argparse now supplies when the flag is absent, so "was it given" is a
        # presence question rather than a value comparison.
        "lookback": None,
        "calendar_lookback": None,
        "out": None,
        "cap": "0.2",
    }
    args.update(overrides)
    return argparse.Namespace(**args)


def test_the_pair_is_documented_at_the_call_site() -> None:
    """Neither class had a docstring, and the batch's span is what one of them has to state."""
    from vqapr.data.lookback import InstantsLookback

    # Since record `137` the per-name count is `InstantsLookback`; `RowsLookback` counts the
    # table's rows, the same instants for every name, and its docstring says both.
    assert RowsLookback.__doc__ and "same instants for every name" in RowsLookback.__doc__
    assert "InstantsLookback" in RowsLookback.__doc__
    assert InstantsLookback.__doc__ and "each instrument independently" in InstantsLookback.__doc__
    assert "sparsest" in InstantsLookback.__doc__, (
        "the unbounded calendar span is the property that makes a cross-sectional model wrong"
    )
    assert CalendarLookback.__doc__ and "every instrument" in CalendarLookback.__doc__


def test_the_calendar_flavour_declares_the_other_member() -> None:
    """What the emitted file imports, declares and guards on."""
    source = render(
        ComponentKind.DATA_MODEL,
        "cross-sectional",
        dataset_id="price_daily",
        lookback=180,
        lookback_kind="calendar",
    )

    assert "CalendarLookback(days=LOOKBACK_DAYS, timezone=TIMEZONE)" in source
    assert "RowsLookback" not in source, "the calendar scaffold must not import the other member"
    assert "LOOKBACK_DAYS = 180" in source
    assert "len(values) >= 2" in source, (
        "a calendar window does not promise a row count, so the row-count guard cannot survive"
    )
    assert "cross-section" in source, "the emitted file has to say what this window is for"


def test_the_rows_flavour_still_emits_what_it_always_did() -> None:
    """The default is unchanged, and now says what the number means."""
    source = render(ComponentKind.DATA_MODEL, "reversal", dataset_id="price_daily", lookback=6)

    assert "RowsLookback(rows=LOOKBACK)" in source
    assert "LOOKBACK = 6" in source
    assert "len(values) == LOOKBACK" in source
    assert "--calendar-lookback" in source, (
        "the rows scaffold is the one an author lands on by default, so it names the other member"
    )


def test_the_calendar_scaffold_computes_over_a_shared_window(
    tmp_path: Path, model_price_parquet: Path
) -> None:
    """A template must run as written -- the same gate the rows flavour already passes.

    Three calendar days back from 2024-03-07 16:00 KST is 2024-03-04 00:00, so both names
    contribute their 03-05, 03-06 and 03-07 rows: A rises 100 -> 105 and B rises 50 -> 53.
    """
    register_dataset(
        tmp_path,
        DatasetRegistration.of(
            "price_daily",
            "prices",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
        ),
        SourceSpec.of("prices", model_price_parquet),
    )
    source = tmp_path / "cross_sectional.py"
    source.write_text(
        render(
            ComponentKind.DATA_MODEL,
            "cross-sectional",
            dataset_id="price_daily",
            lookback=3,
            lookback_kind="calendar",
        ),
        encoding="utf-8",
    )
    ref = register_data_model(tmp_path, "cross-sectional", source, "CrossSectional")
    model = load_data_model(ref, project_root=tmp_path)
    requirement = model.requirements()[0]

    assert isinstance(requirement.lookback, CalendarLookback)

    rows = model.compute(
        DataModelContext(
            window=ModelWindow(
                evaluation_time=EVALUATION_TIME,
                instruments=("A", "B"),
                store=DuckDbObservationStore(Workspace.open(tmp_path)),
                allowed_requirements=(requirement,),
                consumer_id="test-consumer",
            ),
            reads=model.inputs(),
        )
    )

    assert rows == [
        {"instrument": "A", "value": 0.05},
        {"instrument": "B", "value": 0.06},
    ]


def test_the_flag_reaches_the_scaffold(tmp_path: Path) -> None:
    """End to end through the verb, because the flag is the thing that was missing."""
    envelope = new_command(_namespace(calendar_lookback=90), project_root=tmp_path)

    emitted = Path(envelope["path"]).read_text(encoding="utf-8")
    assert "LOOKBACK_DAYS = 90" in emitted
    assert "CalendarLookback" in emitted


def test_declaring_both_windows_is_refused_rather_than_resolved(tmp_path: Path) -> None:
    """No precedence rule, because a reader would have to know it to predict their own command."""
    from vqapr.inputs import InputError

    with pytest.raises(InputError) as refused:
        new_command(_namespace(lookback=313, calendar_lookback=365), project_root=tmp_path)

    assert "two different windows" in refused.value.requirement
    assert not list(tmp_path.glob("*.py")), "a refused scaffold must write nothing"


def test_the_conflict_is_caught_even_when_rows_is_typed_at_its_default(tmp_path: Path) -> None:
    """`--lookback 6 --calendar-lookback 30` is two flags, and 6 is the default value.

    Found by the structural audit (`docs/refactoring/`, C3). The check compared
    `args.lookback != _LOOKBACK_DEFAULT`, so a user who typed the default explicitly gave both
    windows, was not refused, and had `--lookback` silently ignored -- the exact outcome the
    refusal's own docstring promises cannot happen. Presence, not value, is the question.
    """
    from vqapr.cli.new import _LOOKBACK_DEFAULT
    from vqapr.inputs import InputError

    with pytest.raises(InputError) as refused:
        new_command(
            _namespace(lookback=_LOOKBACK_DEFAULT, calendar_lookback=30), project_root=tmp_path
        )

    assert "two different windows" in refused.value.requirement
    assert not list(tmp_path.glob("*.py"))


def test_neither_flag_still_scaffolds_the_rows_default(tmp_path: Path) -> None:
    """The default survives the move to presence-detection: no flags means six rows."""
    envelope = new_command(_namespace(), project_root=tmp_path)

    assert "LOOKBACK = 6" in Path(envelope["path"]).read_text(encoding="utf-8")


def test_a_strategy_is_told_why_the_flag_does_not_apply(tmp_path: Path) -> None:
    """The strategy body counts observations per name, so a day count would leave it meaningless."""
    from vqapr.inputs import InputError

    with pytest.raises(InputError) as refused:
        new_command(
            _namespace(kind="strategy", component_id="alpha", calendar_lookback=90),
            project_root=tmp_path,
        )

    assert "datamodel scaffold" in refused.value.requirement
    assert "counts observations per name" in refused.value.fix
