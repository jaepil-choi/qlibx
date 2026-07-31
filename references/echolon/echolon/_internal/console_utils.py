"""Windows console hardening — disable QuickEdit Mode.

QuickEdit Mode is the default-on Windows CMD behavior where any click in
the window (or accidental drag) puts the console into Mark/Select mode,
which causes the Windows console subsystem to **stop draining the
process's stdout pipe**. Once stdout's ~4KB buffer fills, the Python
process blocks in the kernel on the next ``print()`` or ``logger.info()``
call. APScheduler jobs running in worker threads freeze mid-execution
and look exactly like "the daily run didn't trigger". Pressing Enter
exits Select mode and unblocks the process.

This module disables QuickEdit Mode at process startup so accidental
clicks no longer pause the trader. It is a no-op on non-Windows OSes
and on consoles that aren't attached to a CMD/PowerShell window
(e.g. when launched via Task Scheduler with no console).

Reference:
- Microsoft docs: SetConsoleMode (kernel32) ENABLE_QUICK_EDIT_MODE flag
- Reproducible bug: 2026-04-30 daily run did not trigger; pressing Enter
  in the operator's CMD window unblocked the job mid-execution.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


# Win32 console-mode flags — see WinBase.h.
_ENABLE_EXTENDED_FLAGS = 0x0080
_ENABLE_QUICK_EDIT_MODE = 0x0040
_ENABLE_INSERT_MODE = 0x0020
_STD_INPUT_HANDLE = -10  # GetStdHandle(STD_INPUT_HANDLE)


def disable_quickedit_mode() -> bool:
    """Disable QuickEdit Mode + Insert Mode on the current console.

    Returns True on success, False on non-Windows, no-console-attached,
    or a Win32 API failure. The Win32 console APIs return BOOL / handle
    integers (they don't raise), so the only realistic exception sources
    are the ``ctypes`` import and ``windll.kernel32`` attribute access —
    those are caught narrowly. Everything past those is checked via the
    API return values.
    """
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
    except (ImportError, AttributeError) as exc:
        # Stripped Python without ctypes, or non-CPython interpreter
        # lacking ``windll`` — extremely rare on a real Windows install.
        logger.debug("disable_quickedit_mode: ctypes/windll unavailable: %s", exc)
        return False

    h_stdin = kernel32.GetStdHandle(_STD_INPUT_HANDLE)
    if h_stdin == 0 or h_stdin == ctypes.c_void_p(-1).value:
        logger.debug("disable_quickedit_mode: no stdin handle (no console attached)")
        return False

    mode = wintypes.DWORD()
    if not kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
        logger.debug(
            "disable_quickedit_mode: GetConsoleMode failed (errno=%d)",
            ctypes.get_last_error(),
        )
        return False

    # Clear QuickEdit + Insert; set Extended (required for the QuickEdit
    # bit to take effect).
    new_mode = (mode.value | _ENABLE_EXTENDED_FLAGS) & ~(
        _ENABLE_QUICK_EDIT_MODE | _ENABLE_INSERT_MODE
    )
    if not kernel32.SetConsoleMode(h_stdin, new_mode):
        logger.debug(
            "disable_quickedit_mode: SetConsoleMode failed (errno=%d)",
            ctypes.get_last_error(),
        )
        return False

    logger.info(
        "Console QuickEdit Mode DISABLED — accidental clicks "
        "will no longer pause the process."
    )
    return True
