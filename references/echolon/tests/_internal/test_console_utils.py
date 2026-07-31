"""Smoke tests for echolon._internal.console_utils.

The actual Windows console-mode manipulation can only be verified on a
real Windows console. These tests confirm the helper:
- Returns False (no-op) on non-Windows platforms.
- Doesn't raise on import or call.
- Has the correct constants per WinBase.h.
"""
import sys

from echolon._internal.console_utils import (
    disable_quickedit_mode,
    _ENABLE_EXTENDED_FLAGS,
    _ENABLE_QUICK_EDIT_MODE,
    _ENABLE_INSERT_MODE,
    _STD_INPUT_HANDLE,
)


def test_constants_match_winbase_h():
    """Constants must match Microsoft's WinBase.h definitions exactly.

    Source: https://learn.microsoft.com/en-us/windows/console/setconsolemode
    Wrong values would silently fail to disable QuickEdit on Windows.
    """
    assert _ENABLE_EXTENDED_FLAGS == 0x0080
    assert _ENABLE_QUICK_EDIT_MODE == 0x0040
    assert _ENABLE_INSERT_MODE == 0x0020
    assert _STD_INPUT_HANDLE == -10


def test_returns_false_on_non_windows():
    """On Linux/macOS the helper is a no-op returning False."""
    if sys.platform == "win32":
        return  # not applicable
    assert disable_quickedit_mode() is False


def test_does_not_raise_on_repeated_calls():
    """Calling repeatedly is safe (idempotent best-effort)."""
    for _ in range(3):
        disable_quickedit_mode()
