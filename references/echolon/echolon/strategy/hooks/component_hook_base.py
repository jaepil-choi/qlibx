"""
Component Hook Base Interface
=============================

Abstract base class for component hooks.

Hooks provide a clean extension mechanism for adding market-specific
or frequency-specific functionality to BaseComponent without modifying
the core component code.

Lifecycle:
    1. on_init(): Called when hook is added via component.add_hook()
    2. on_initialize(): Called during component.initialize()

Hook Types:
    SessionAwareComponentHook: Adds session context helpers (intraday)
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from ..component import BaseComponent

logger = logging.getLogger(__name__)


class IComponentHook(ABC):
    """
    Abstract interface for component hooks.

    Hooks customize component behavior without modifying
    the core BaseComponent implementation.

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
    def on_init(self, component: 'BaseComponent') -> None:
        """
        Called when hook is added to component.

        Use for injecting methods/properties into the component instance.
        This is where session helpers are added.

        Args:
            component: BaseComponent instance
        """
        pass

    @abstractmethod
    def on_initialize(self, component: 'BaseComponent') -> None:
        """
        Called during component.initialize().

        Use for hook initialization that requires component to be initialized.

        Args:
            component: BaseComponent instance
        """
        pass


class NullComponentHook(IComponentHook):
    """
    No-op component hook for testing or as a base for partial implementations.
    """

    @property
    def name(self) -> str:
        return "NullComponentHook"

    def on_init(self, component: 'BaseComponent') -> None:
        pass

    def on_initialize(self, component: 'BaseComponent') -> None:
        pass
