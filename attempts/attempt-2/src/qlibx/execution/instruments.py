"""Concrete instrument boundary models and compiled runtime terms."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from qlibx.models import QlibxModel


class StockInstrument(QlibxModel):
    kind: Literal["stock"] = "stock"
    instrument_id: str = Field(min_length=1)
    exchange_id: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    lot_size: int = Field(gt=0)


class EtfInstrument(QlibxModel):
    kind: Literal["etf"] = "etf"
    instrument_id: str = Field(min_length=1)
    exchange_id: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    lot_size: int = Field(gt=0)


class IndexInstrument(QlibxModel):
    kind: Literal["index"] = "index"
    instrument_id: str = Field(min_length=1)
    exchange_id: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    tracking_only: Literal[True] = True


class FactorInstrument(QlibxModel):
    kind: Literal["factor"] = "factor"
    instrument_id: str = Field(min_length=1)
    exchange_id: str = Field(min_length=1)
    return_native: Literal[True] = True


Instrument = Annotated[
    StockInstrument | EtfInstrument | IndexInstrument | FactorInstrument,
    Field(discriminator="kind"),
]


@dataclass(frozen=True, slots=True)
class CompiledInstrument:
    index: int
    instrument_id: str
    product_type: str
    lot_size: int
    currency: str


@dataclass(frozen=True, slots=True)
class CompiledInstrumentSet:
    instruments: tuple[CompiledInstrument, ...]

    def by_id(self) -> dict[str, CompiledInstrument]:
        return {instrument.instrument_id: instrument for instrument in self.instruments}
