"""
Strategy Hook Base Interface
============================

Abstract base class for strategy hooks.

Hooks provide a clean extension mechanism for adding market-specific
or frequency-specific functionality to BaseStrategy without modifying
the core strategy code.

Lifecycle:
    1. on_init(): Called when hook is added via strategy.add_hook()
    2. on_start(): Called during strategy.on_start()
    3. on_bar_start(): Called at beginning of each bar
    4. on_bar_end(): Called at end of each bar
    5. on_stop(): Called during strategy.on_stop()

Hook Types:
    SessionAwareStrategyHook: Adds session context helpers (intraday)
    ForcedExitStrategyHook: Adds forced exit infrastructure (interday futures)
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from ..base import BaseStrategy

logger = logging.getLogger(__name__)


class IStrategyHook(ABC):
    """
    Abstract interface for strategy hooks.

    Hooks customize strategy behavior at specific lifecycle points
    without modifying the core BaseStrategy implementation.

    Subclasses must implement all abstract methods, but can use
    pass for methods that don't need customization.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Hook name for logging and identification.

        Returns:
            Human-readable hook name
        """
        pass

    @abstractmethod
    def on_init(self, strategy: 'BaseStrategy') -> None:
        """
        Called when hook is added to strategy.

        Use for injecting methods/properties into the strategy instance.
        This is where session helpers or forced exit methods are added.

        Args:
            strategy: BaseStrategy instance
        """
        pass

    @abstractmethod
    def on_start(self, strategy: 'BaseStrategy') -> None:
        """
        Called during strategy.on_start().

        Use for hook initialization that requires strategy to be started.

        Args:
            strategy: BaseStrategy instance
        """
        pass

    @abstractmethod
    def on_bar_start(self, strategy: 'BaseStrategy') -> bool:
        """
        Called at the beginning of each bar, before strategy logic.

        Use for:
        - Processing forced exits (ForcedExitStrategyHook)
        - Pre-bar validation

        Args:
            strategy: BaseStrategy instance

        Returns:
            True if bar processing should continue, False to skip rest of bar
            (e.g., if forced exit was processed)
        """
        pass

    @abstractmethod
    def on_bar_end(self, strategy: 'BaseStrategy') -> None:
        """
        Called at the end of each bar, after strategy logic.

        Use for:
        - Post-bar cleanup
        - State updates

        Args:
            strategy: BaseStrategy instance
        """
        pass

    @abstractmethod
    def on_stop(self, strategy: 'BaseStrategy') -> None:
        """
        Called during strategy.on_stop().

        Use for:
        - Cleanup
        - Final state persistence

        Args:
            strategy: BaseStrategy instance
        """
        pass


class NullStrategyHook(IStrategyHook):
    """
    No-op strategy hook for testing or as a base for partial implementations.

    All methods do nothing. Useful for creating hooks that only
    need to implement a subset of lifecycle methods.
    """

    @property
    def name(self) -> str:
        return "NullStrategyHook"

    def on_init(self, strategy: 'BaseStrategy') -> None:
        pass

    def on_start(self, strategy: 'BaseStrategy') -> None:
        pass

    def on_bar_start(self, strategy: 'BaseStrategy') -> bool:
        return True  # Continue processing

    def on_bar_end(self, strategy: 'BaseStrategy') -> None:
        pass

    def on_stop(self, strategy: 'BaseStrategy') -> None:
        pass
