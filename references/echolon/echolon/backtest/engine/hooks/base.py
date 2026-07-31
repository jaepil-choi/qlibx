"""
Engine Hook Base Interface
==========================

Abstract base class for BacktraderEngine hooks.

Hooks provide a clean extension mechanism for adding market-specific
or frequency-specific functionality to BacktraderEngine without
modifying the core engine code.

Lifecycle:
    1. on_init(): Called when hook is added via engine.add_hook()
    2. on_setup(): Called during engine.setup(), before strategy added
    3. on_post_setup(): Called after strategy and analyzers added
    4. on_pre_run(): Called just before cerebro.run()
    5. on_post_run(): Called after cerebro.run() completes

Design Pattern:
    Template Method pattern - engine defines the algorithm skeleton,
    hooks fill in specific steps.

Example:
    class MyCustomHook(IEngineHook):
        def on_setup(self, cerebro, engine):
            # Add custom observer
            cerebro.addobserver(MyObserver)
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    import backtrader as bt
    from ..backtrader_engine import BacktraderEngine

logger = logging.getLogger(__name__)


class IEngineHook(ABC):
    """
    Abstract interface for BacktraderEngine hooks.

    Hooks customize engine behavior at specific lifecycle points
    without modifying the core engine implementation.

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
    def on_init(self, engine: 'BacktraderEngine') -> None:
        """
        Called when hook is added to engine.

        Use for early initialization that doesn't require Cerebro.
        Examples: setting up session context providers, registering callbacks.

        Args:
            engine: BacktraderEngine instance
        """
        pass

    @abstractmethod
    def on_setup(self, cerebro: 'bt.Cerebro', engine: 'BacktraderEngine') -> None:
        """
        Called during engine.setup(), before strategy is added.

        Use for:
        - Replacing default broker with custom broker
        - Adding observers
        - Pre-loading data

        Args:
            cerebro: Backtrader Cerebro instance
            engine: BacktraderEngine instance
        """
        pass

    @abstractmethod
    def on_post_setup(self, cerebro: 'bt.Cerebro', engine: 'BacktraderEngine') -> None:
        """
        Called after strategy and analyzers are added.

        Use for:
        - Final configuration that depends on strategy
        - Adding analyzers that need strategy reference

        Args:
            cerebro: Backtrader Cerebro instance
            engine: BacktraderEngine instance
        """
        pass

    @abstractmethod
    def on_pre_run(self, engine: 'BacktraderEngine') -> None:
        """
        Called just before cerebro.run().

        Use for:
        - Final validation
        - Logging run start

        Args:
            engine: BacktraderEngine instance
        """
        pass

    @abstractmethod
    def on_post_run(
        self,
        engine: 'BacktraderEngine',
        strategy: 'bt.Strategy',
        results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Called after cerebro.run() completes.

        Use for:
        - Extracting hook-specific results
        - Cleanup

        Args:
            engine: BacktraderEngine instance
            strategy: Executed strategy instance
            results: Results dictionary to augment

        Returns:
            Augmented results dictionary
        """
        pass


class NullHook(IEngineHook):
    """
    No-op hook for testing or as a base for partial implementations.

    All methods do nothing. Useful for creating hooks that only
    need to implement a subset of lifecycle methods.
    """

    @property
    def name(self) -> str:
        return "NullHook"

    def on_init(self, engine: 'BacktraderEngine') -> None:
        pass

    def on_setup(self, cerebro: 'bt.Cerebro', engine: 'BacktraderEngine') -> None:
        pass

    def on_post_setup(self, cerebro: 'bt.Cerebro', engine: 'BacktraderEngine') -> None:
        pass

    def on_pre_run(self, engine: 'BacktraderEngine') -> None:
        pass

    def on_post_run(
        self,
        engine: 'BacktraderEngine',
        strategy: 'bt.Strategy',
        results: Dict[str, Any]
    ) -> Dict[str, Any]:
        return results
