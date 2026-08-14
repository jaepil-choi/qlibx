"""`domain/identifiers.py` — 이름."""

from __future__ import annotations

import pytest

from vqapr.domain.identifiers import dataset_id, instrument_id, source_id


@pytest.mark.parametrize(
    "raw",
    [
        "A005930",  # KRX
        "BRK/B",  # NYSE — 경로 구분자가 티커의 일부다
        "BRK.B",  # 같은 종목의 다른 표기
        "_KOSPI",  # 종목 축이 없는 시계열의 합성 instrument
        "005930.KS",
        "ES=F",
    ],
)
def test_instrument_id_takes_what_the_venue_gives(raw: str) -> None:
    """venue가 주는 형태를 그대로 받는다. 문자를 막으면 그 시장을 못 쓰게 된다."""
    assert instrument_id(raw) == raw


@pytest.mark.parametrize("raw", ["", " ", "A005930 ", " A005930", "A 005930"])
def test_instrument_id_rejects_whitespace(raw: str) -> None:
    """공백만 거부한다 — 식별자의 일부인 경우가 없고 파싱 사고의 흔적이다."""
    with pytest.raises(ValueError):
        instrument_id(raw)


def test_instrument_id_rejects_non_strings() -> None:
    with pytest.raises(TypeError):
        instrument_id(5930)  # type: ignore[arg-type]


@pytest.mark.parametrize("factory", [dataset_id, source_id])
def test_project_scoped_ids_are_stricter(factory) -> None:
    """dataset_id와 source_id는 사람이 고르는 이름이라 공백을 허용할 이유가 없다."""
    assert factory("price_daily") == "price_daily"
    with pytest.raises(ValueError):
        factory("price daily")
    with pytest.raises(ValueError):
        factory("")
