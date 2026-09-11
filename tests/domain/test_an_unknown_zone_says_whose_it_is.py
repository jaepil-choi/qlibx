"""An unknown time zone says whether the name or the machine is missing it.

Report 2026-09-11 (`docs/issues/report-2026-09-11-on-windows-a-strategy-naming-asia-seoul-fails-
registration-as-a-502-blamed-on-user-code-until-tzdata-is-installed.md`): on Windows, with no
`tzdata`, `CalendarLookback(timezone="Asia/Seoul")` was refused as an unknown zone and blamed on
the user's file. vqapr now depends on `tzdata` on Windows, and the three places that named a zone
refuse through one door that tells a missing database from a misspelt name (record `263`).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from vqapr.data.lookback import CalendarLookback
from vqapr.domain import values
from vqapr.domain.values import iana_zone
from vqapr.exchange.conventions import FillRule


def test_the_zone_of_every_krx_example_resolves() -> None:
    assert iana_zone("Asia/Seoul").key == "Asia/Seoul"


def test_a_misspelt_zone_is_the_names_fault() -> None:
    with pytest.raises(ValueError, match=r"^unknown IANA timezone: 'Asia/Seol'$"):
        iana_zone("Asia/Seol")


def test_a_machine_with_no_database_is_told_to_install_tzdata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(values, "available_timezones", set)

    with pytest.raises(ValueError, match=r"no IANA time zone database.*`uv add tzdata`"):
        iana_zone("Asia/Seol")


@pytest.mark.parametrize(
    "construct",
    [
        lambda zone: CalendarLookback(days=5, timezone=zone),
        lambda zone: FillRule("close", zone),
    ],
    ids=["calendar-lookback", "fill-rule"],
)
def test_every_door_that_names_a_zone_refuses_the_same_way(construct) -> None:
    with pytest.raises(ValueError, match="unknown IANA timezone: 'Asia/Seol'"):
        construct("Asia/Seol")


def test_windows_installs_get_the_database() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    dependencies = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]

    assert "tzdata; sys_platform == 'win32'" in dependencies
