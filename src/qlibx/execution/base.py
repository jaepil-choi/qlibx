"""Generic Exchange lifecycle contract."""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from qlibx.errors import OperationOutcome

RequestT = TypeVar("RequestT")
ResultT = TypeVar("ResultT")


class BaseExchange(ABC, Generic[RequestT, ResultT]):
    """Match one immutable venue-specific request without mutating package state."""

    @property
    @abstractmethod
    def exchange_id(self) -> str:
        """Return the stable venue identity."""

    @property
    @abstractmethod
    def config_fingerprint(self) -> str:
        """Return the deterministic economic configuration identity."""

    @abstractmethod
    def match_batch(self, request: RequestT) -> OperationOutcome[ResultT]:
        """Return a typed venue result without mutating Account or Memory."""
