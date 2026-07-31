"""IndicatorConfig — technical indicator period caps."""

from pydantic import BaseModel, Field

_DEFAULT_INTERDAY_CAPS = {
    "tema": 62, "trix": 62, "adxr": 62,
    "adx": 93, "dema": 93,
    "default": 180,
}

_DEFAULT_INTRADAY_CAPS = {
    "tema": 500, "trix": 500, "adxr": 500,
    "adx": 750, "dema": 750,
    "default": 1000,
}


class IndicatorConfig(BaseModel):
    """Period caps for technical indicators."""

    interday_caps: dict[str, int] = Field(
        default_factory=lambda: dict(_DEFAULT_INTERDAY_CAPS),
    )
    intraday_caps: dict[str, int] = Field(
        default_factory=lambda: dict(_DEFAULT_INTRADAY_CAPS),
    )

    def get_interday_cap(self, indicator_name: str) -> int:
        return self.interday_caps.get(indicator_name, self.interday_caps["default"])

    def get_intraday_cap(self, indicator_name: str) -> int:
        return self.intraday_caps.get(indicator_name, self.intraday_caps["default"])
